from dataclasses import dataclass, replace
from typing import Optional
import json
import os
import tempfile
import time
import uuid
from pathlib import Path

import PyQt5.Qt
from PyQt5 import QtWidgets, QtGui, QtCore
from PyQt5.Qt import QMainWindow
from PyQt5.QtCore import Qt, QPoint
import qtawesome as qta
from pyfcstm.model import parse_dsl_node_to_state_machine
from pyfcstm.dsl import parse_with_grammar_entry

from app.ui import UIMainWindow
from ..model import State, StateManager
from app.application.document import (
    DocumentDependencyLoadError,
    DocumentDependencyStaleError,
    DocumentService,
    DocumentValidationError,
    InvalidDocumentSaveError,
    TextEdit,
)
from app.application.commands import CommandStateError, DocumentCommandStack
from app.application.events import (
    EventConflictError,
    EventProjectionError,
    EventProjectionService,
    EventReadOnlyError,
)
from app.application.diagnostics import (
    DiagnosticService,
    DiagnosticSourceKind,
)
from app.application.dynamic_validation import DynamicValidationService
from app.application.export import ExportService
from app.application.generation import GenerationService
from app.application.simulation import SimulationService
from app.application.task_runner import (
    TaskResult,
    TaskRunner,
    TaskStamp,
    TaskStaleError,
    TaskStatus,
)
from app.application.tasks import (
    TaskArtifact,
    TaskBoundary,
    TaskCenter,
    TaskRecord,
    TaskStatus as HistoryTaskStatus,
)
from app.model.session import ValidationState
from app.source import SourceEncodingAmbiguityError, canonical_path
from app.utils.dsl_to_ui import (
    convert_state_machine_to_state_manager,
    extract_variable_definitions,
    update_ui_from_state_manager,
)
from app.utils.export_to_word import export_statechart_to_word
from app.utils.export_to_excel import export_statechart_to_excel
from app.utils.ui_to_dsl import (
    format_lifecycle_item,
    format_state,
    format_transition_item,
)
from .dialog_edit_state import DialogEditState
from app.utils.ui_to_dsl import state_manager_to_dsl
from .dialog_show_error import DialogShowError
from .dialog_code_gen import DialogCodeGen
from .dialog_export import DialogExport
from .dialog_add_lifecycle import DialogAddLifecycle
from .dialog_add_transition import DialogAddTransition
from .task_result_dock import TaskResultDock
from .diagnostics_panel import DiagnosticsPanel
from .dynamic_validation_workspace import DynamicValidationWorkspace
from .simulation_workspace import SimulationWorkspace
from .graph_workspace import GraphWorkspace
import re


@dataclass(frozen=True)
class DocumentLoadOutcome:
    operation_id: str
    task_result: TaskResult
    ui_error: Optional[BaseException] = None
    logical_status: Optional[TaskStatus] = None

    @property
    def status(self):
        if self.logical_status is not None:
            return self.logical_status
        return TaskStatus.FAILED if self.ui_error is not None else self.task_result.status

    @property
    def value(self):
        return self.task_result.value

    @property
    def error(self):
        return self.ui_error if self.ui_error is not None else self.task_result.error


class DocumentLoadOperation(QtCore.QObject):
    finished = QtCore.pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.operation_id = uuid.uuid4().hex
        self.current_attempt = None
        self.result = None

    def cancel(self):
        if self.current_attempt is not None:
            self.current_attempt.cancel()

    def finish(self, outcome):
        if self.result is not None:
            return
        self.result = outcome
        self.finished.emit(outcome)


class _StampedTaskToken(object):
    def __init__(self, token, stamp_is_current):
        self._token = token
        self._stamp_is_current = stamp_is_current

    @property
    def cancelled(self):
        return self._token.cancelled

    def raise_if_cancelled(self):
        self._token.raise_if_cancelled()
        current = self._stamp_is_current()
        if isinstance(current, tuple):
            valid, detail = current
        else:
            valid, detail = bool(current), ""
        if not valid:
            suffix = ": " + detail if detail else ""
            raise TaskStaleError(
                "task stamp became stale before artifact publication" + suffix
            )


class AppMainWindow(QMainWindow, UIMainWindow):
    document_load_finished = QtCore.pyqtSignal(object)
    document_validation_finished = QtCore.pyqtSignal(object)
    model_check_finished = QtCore.pyqtSignal(object)
    simulation_task_finished = QtCore.pyqtSignal(object)
    dynamic_validation_finished = QtCore.pyqtSignal(object)
    graph_task_finished = QtCore.pyqtSignal(object)
    generation_finished = QtCore.pyqtSignal(object)
    unified_export_finished = QtCore.pyqtSignal(object)
    state_manager: Optional[StateManager]

    def __init__(
        self,
        settings=None,
        document_service=None,
        task_runner=None,
        task_center=None,
    ):
        QMainWindow.__init__(self)
        self.setupUi(self)
        self.workspace_tabs = self.workbench_tabs
        self.frame_all_state = self.model_explorer_panel
        self.at_page_initial = True
        #self.fcstm_state_chart = None
        self.code_file_path = "./"
        self.state_machine_file_path = "./"
        self.document_service = document_service or DocumentService()
        self.diagnostic_service = DiagnosticService()
        self.event_service = EventProjectionService(self.document_service)
        self.simulation_service = SimulationService()
        self.dynamic_validation_service = DynamicValidationService()
        self.generation_service = GenerationService()
        self.export_service = ExportService()
        self._simulation_session = None
        self._workspace_task_actions = {}
        self.document_session = None
        self.settings = settings if settings is not None else QtCore.QSettings(
            "zhougut", "fcstm-gui"
        )
        self.task_runner = task_runner or TaskRunner(
            stamp_validator=self._task_stamp_current, parent=self
        )
        self.command_stack = DocumentCommandStack(service=self.document_service)
        if task_center is None and settings is not None:
            settings_dir = os.path.dirname(os.path.abspath(settings.fileName()))
            task_center = TaskCenter(
                data_location_provider=lambda: os.path.join(settings_dir, "task-data"),
                workspace=os.getcwd(),
            )
        self.task_center = task_center or TaskCenter(workspace=os.getcwd())
        self._task_history_warnings = self.task_center.load()
        self._logical_load_operations = {}
        self._task_handles = {}
        self._setting_source_text = False
        self._setting_projection = False
        self._document_load_requests = {}
        self._variable_edit_timer = QtCore.QTimer(self)
        self._variable_edit_timer.setSingleShot(True)
        self._variable_edit_timer.setInterval(300)
        self._variable_edit_timer.timeout.connect(self._commit_variable_editor)
        
        # 初始化工具提示相关的实例变量
        self._current_tooltip_item = None
        self._current_tooltip_table = None
        
        self._init()

    def _init(self):
        #初始化窗口格式
        self._init_window_style()
        #初始化菜单栏
        self._init_menu_bar()
        self._init_source_editor()
        self._init_diagnostics_panel()
        self._init_workbench_layout()
        self._init_graph_workspace()
        self._init_simulation_workspace()
        self._init_dynamic_validation_workspace()
        self._init_event_panel()
        self._init_task_result_dock()
        self._publish_history_warnings()
        #初始化导入状态机按钮
        self._init_import_state_chart()
        self._init_tree_all_state_context_menu()
        #初始化文本框变化操作
        self._init_edit_text_change()
        #初始化添加状态按钮
        self._init_button_state_machine_add_state()
        #初始化新建状态机按钮
        self._init_button_initial_new_state_machine()
        #展开所有状态按钮
        self._init_button_state_machine_expand_all()
        #折叠所有状态按钮
        self._init_button_state_machine_fold_all()
        #初始化生命周期按钮
        self._init_button_lifecycle()
        #初始化转移按钮
        self._init_button_transition()
        self._init_keyboard_navigation()
        self._finalize_button_accessibility()
        '''
        self._init_button_save_state()
        '''

    def _init_window_style(self):
        self.stackedWidget_state_machine.setCurrentIndex(0)
        self.document_name_label.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred
        )
        self.document_name_label.setMinimumWidth(80)
        self.document_status_layout.setStretch(0, 1)
        self._document_display_name = "未打开文档"
        for widget, accessible_name in (
            (self.tree_all_state, "模型状态树"),
            (self.edit_var_def, "变量定义编辑器"),
            (self.table_lifecycle, "生命周期操作表"),
            (self.table_transition, "迁移表"),
            (self.button_initial_import_state_machine, "导入状态机"),
            (self.button_initial_new_state_machine, "新建状态机"),
            (self.button_add_state, "新增状态"),
            (self.button_lifecycle, "新增生命周期操作"),
            (self.button_transition, "新增迁移"),
            (self.button_fold_all_state, "折叠全部状态"),
            (self.button_expand_all_state, "展开全部状态"),
        ):
            widget.setAccessibleName(accessible_name)
            if not widget.toolTip():
                widget.setToolTip(accessible_name)
        self._init_tree_style()
        self._init_button_style()
        self._init_text_edit_style()
        self._init_table_style()
        for button in self.findChildren(QtWidgets.QAbstractButton):
            if button.icon().isNull():
                continue
            fallback = button.text() or button.toolTip() or button.objectName()
            if not button.accessibleName():
                button.setAccessibleName(fallback)
            if not button.toolTip():
                button.setToolTip(button.accessibleName())

    def _init_menu_bar(self):
        """初始化菜单栏"""
        # 文件菜单
        self.menu_file.addAction(self.action_import_state_machine)
        self.action_import_state_machine.setShortcut(QtGui.QKeySequence.Open)
        self.action_save_state_machine = QtWidgets.QAction("保存", self)
        self.action_save_state_machine.setShortcut(QtGui.QKeySequence.Save)
        self.menu_file.addAction(self.action_save_state_machine)
        self.menu_file.addAction(self.action_export_state_machine)
        self.action_unified_export = QtWidgets.QAction("统一导出", self)
        self.action_unified_export.setObjectName("action_unified_export")
        self.action_unified_export.setShortcut("Ctrl+Shift+X")
        self.menu_file.addAction(self.action_unified_export)

        self.menu_edit = self.menuBar().addMenu("编辑")
        self.action_undo = QtWidgets.QAction("撤销", self)
        self.action_undo.setObjectName("action_undo")
        self.action_undo.setShortcut(QtGui.QKeySequence.Undo)
        self.action_redo = QtWidgets.QAction("重做", self)
        self.action_redo.setObjectName("action_redo")
        self.action_redo.setShortcut(QtGui.QKeySequence.Redo)
        self.action_find = QtWidgets.QAction("查找", self)
        self.action_find.setObjectName("action_find")
        self.action_find.setShortcut(QtGui.QKeySequence.Find)
        self.menu_edit.addAction(self.action_undo)
        self.menu_edit.addAction(self.action_redo)
        self.menu_edit.addAction(self.action_find)
        self.menu_view = self.menuBar().addMenu("视图")
        
        # 工具菜单
        self.menu_tool.addAction(self.action_validate_state_machine)
        self.action_validate_state_machine.setShortcut("F5")
        self.action_stop_task = QtWidgets.QAction("停止当前任务", self)
        self.action_stop_task.setObjectName("action_stop_task")
        self.action_stop_task.setShortcut("Shift+F5")
        self.menu_tool.addAction(self.action_stop_task)
        self.menu_tool.addAction(self.action_graph_gen)
        self.menu_tool.addAction(self.action_code_gen)
        
        # 连接菜单项信号
        self.action_import_state_machine.triggered.connect(self._import_statechart)
        self.action_save_state_machine.triggered.connect(self._save_current_document)
        self.action_export_state_machine.triggered.connect(self._export_statechart)
        self.action_unified_export.triggered.connect(self._show_unified_export)
        self.action_validate_state_machine.triggered.connect(self._validate_statechart)
        self.action_graph_gen.triggered.connect(self._graph_gen)
        self.action_code_gen.triggered.connect(self._code_gen)
        self.action_undo.triggered.connect(self._undo_document)
        self.action_redo.triggered.connect(self._redo_document)
        self.action_find.triggered.connect(self._focus_find_target)
        self.action_stop_task.triggered.connect(self._cancel_active_task)

    def _init_task_result_dock(self):
        self.task_result_dock = TaskResultDock(self.task_center, self)
        self._task_result_dock_sized = False
        self.task_result_dock.setAllowedAreas(Qt.BottomDockWidgetArea)
        self.task_result_dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetClosable
            | QtWidgets.QDockWidget.DockWidgetMovable
        )
        self.addDockWidget(Qt.BottomDockWidgetArea, self.task_result_dock)
        self.task_result_dock.retry_requested.connect(self._retry_task_record)
        self.task_result_dock.cancel_requested.connect(self._cancel_task_record)
        self.task_result_dock.visibilityChanged.connect(
            self._size_task_result_dock_on_first_show
        )
        self.task_result_dock.show_full_paths_action.toggled.connect(
            lambda _checked: self._update_document_actions()
        )
        self.task_result_dock.hide()
        self.action_toggle_task_results = self.task_result_dock.toggleViewAction()
        self.action_toggle_task_results.setText("任务结果")
        self.action_toggle_task_results.setObjectName("action_toggle_task_results")
        self.action_toggle_task_results.setShortcut("Ctrl+Shift+J")
        self.menu_view.addAction(self.action_toggle_task_results)

    def _size_task_result_dock_on_first_show(self, visible):
        if not visible or self._task_result_dock_sized:
            return
        self._task_result_dock_sized = True
        target_height = min(220, max(160, int(self.height() * 0.28)))
        QtCore.QTimer.singleShot(
            0,
            lambda: self.resizeDocks(
                [self.task_result_dock], [target_height], Qt.Vertical
            ),
        )

    def _publish_history_warnings(self):
        for warning in self._task_history_warnings:
            now = time.time()
            self.task_center.add(
                TaskRecord(
                    task_id="history-warning-{}".format(uuid.uuid4().hex),
                    kind="task-history",
                    session_id="",
                    source_revision=0,
                    dependency_fingerprints={},
                    created_at=now,
                    started_at=now,
                    finished_at=now,
                    status=HistoryTaskStatus.FAILED,
                    summary="任务历史已隔离：{}".format(warning.reason),
                    messages=(
                        {
                            "severity": "warning",
                            "message": warning.reason,
                            "quarantine_path": str(warning.quarantine_path),
                        },
                    ),
                    artifacts=(),
                    retry_descriptor=None,
                    exception_chain=(),
                    boundary=TaskBoundary.EXPLICIT,
                )
            )
        if self._task_history_warnings:
            try:
                self.task_center.save()
            except OSError:
                pass
            self._refresh_task_result_dock()

    def _init_source_editor(self):
        self.setWindowTitle("fcstm[*]")
        self.source_editor.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.source_editor.textChanged.connect(self._on_source_text_changed)
        self.action_save_state_machine.setEnabled(False)

    def _init_diagnostics_panel(self):
        layout = self.diagnostics_workspace.layout()
        if layout is None:
            layout = QtWidgets.QVBoxLayout(self.diagnostics_workspace)
            layout.setContentsMargins(0, 0, 0, 0)
        self.diagnostics_panel = DiagnosticsPanel(
            self.diagnostics_workspace,
            redactor=self.task_center.redactor.redact_text,
        )
        layout.addWidget(self.diagnostics_panel)
        self.diagnostics_panel.locate_requested.connect(
            self._locate_diagnostic
        )
        self.diagnostics_panel.suggested_fix_requested.connect(
            self._apply_diagnostic_suggested_fix
        )

    def _init_workbench_layout(self):
        self.model_explorer_dock.hide()
        self.property_inspector_dock.hide()
        self.action_toggle_model_explorer = (
            self.model_explorer_dock.toggleViewAction()
        )
        self.action_toggle_model_explorer.setText("模型资源管理器")
        self.action_toggle_model_explorer.setObjectName(
            "action_toggle_model_explorer"
        )
        self.action_toggle_model_explorer.setShortcut("Ctrl+Shift+E")
        self.action_toggle_property_inspector = (
            self.property_inspector_dock.toggleViewAction()
        )
        self.action_toggle_property_inspector.setText("属性检查器")
        self.action_toggle_property_inspector.setObjectName(
            "action_toggle_property_inspector"
        )
        self.action_toggle_property_inspector.setShortcut("Ctrl+Shift+P")
        self.menu_view.addAction(self.action_toggle_model_explorer)
        self.menu_view.addAction(self.action_toggle_property_inspector)
        self.setCorner(Qt.BottomLeftCorner, Qt.BottomDockWidgetArea)
        self.setCorner(Qt.BottomRightCorner, Qt.BottomDockWidgetArea)

    def _init_graph_workspace(self):
        layout = self.graph_workspace.layout()
        if layout is None:
            layout = QtWidgets.QVBoxLayout(self.graph_workspace)
            layout.setContentsMargins(0, 0, 0, 0)
        self.graph_panel = GraphWorkspace(self.graph_workspace)
        layout.addWidget(self.graph_panel)
        self.graph_panel.refresh_requested.connect(self._refresh_graph)
        self.graph_panel.export_requested.connect(self._export_graph_kind)
        self.graph_panel.cancel_requested.connect(
            lambda: self._cancel_workspace_kind("graph-render")
        )

    def _init_simulation_workspace(self):
        layout = self.simulation_workspace.layout()
        if layout is None:
            layout = QtWidgets.QVBoxLayout(self.simulation_workspace)
            layout.setContentsMargins(0, 0, 0, 0)
        self.simulation_panel = SimulationWorkspace(self.simulation_workspace)
        layout.addWidget(self.simulation_panel)
        self.simulation_panel.initialize_requested.connect(
            self._initialize_simulation
        )
        self.simulation_panel.cycle_requested.connect(self._cycle_simulation)
        self.simulation_panel.run_requested.connect(self._run_simulation)
        self.simulation_panel.reset_requested.connect(self._reset_simulation)
        self.simulation_panel.cancel_requested.connect(
            lambda: self._cancel_workspace_kind("ordinary-simulation")
        )

    def _init_dynamic_validation_workspace(self):
        provenance = self.dynamic_validation_service._load_provenance()
        layout = self.dynamic_validation_workspace.layout()
        if layout is None:
            layout = QtWidgets.QVBoxLayout(self.dynamic_validation_workspace)
            layout.setContentsMargins(0, 0, 0, 0)
        self.dynamic_validation_panel = DynamicValidationWorkspace(
            sorted(provenance["cases"]), self.dynamic_validation_workspace
        )
        layout.addWidget(self.dynamic_validation_panel)
        self.dynamic_validation_panel.run_requested.connect(
            self._run_dynamic_validation
        )
        self.dynamic_validation_panel.cancel_requested.connect(
            lambda: self._cancel_workspace_kind("dynamic-validation")
        )
        self.dynamic_validation_panel.export_requested.connect(
            self._export_dynamic_validation_report
        )

    def _init_event_panel(self):
        self.event_group = QtWidgets.QGroupBox("事件", self.model_workspace)
        self.event_group.setObjectName("event_group")
        self.event_group.setAccessibleName("事件编辑器")
        self.event_group.setMinimumHeight(190)
        event_layout = QtWidgets.QVBoxLayout(self.event_group)
        self.event_table = QtWidgets.QTableWidget(self.event_group)
        self.event_table.setObjectName("event_table")
        self.event_table.setAccessibleName("事件列表")
        self.event_table.setMinimumHeight(70)
        self.event_table.setColumnCount(7)
        self.event_table.setHorizontalHeaderLabels(
            ("所属状态", "名称", "显示名", "作用域", "引用", "物理来源", "权限")
        )
        self.event_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows
        )
        self.event_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self.event_table.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers
        )
        event_header = self.event_table.horizontalHeader()
        for column in (0, 1, 3, 4, 6):
            event_header.setSectionResizeMode(
                column, QtWidgets.QHeaderView.ResizeToContents
            )
        for column in (2, 5):
            event_header.setSectionResizeMode(column, QtWidgets.QHeaderView.Stretch)
        event_layout.addWidget(self.event_table)
        self.event_reference_table = QtWidgets.QTableWidget(self.event_group)
        self.event_reference_table.setObjectName("event_reference_table")
        self.event_reference_table.setAccessibleName("事件迁移引用")
        self.event_reference_table.setMinimumHeight(70)
        self.event_reference_table.setToolTip("所选事件的迁移或 import 映射引用，双击定位源码")
        self.event_reference_table.setColumnCount(4)
        self.event_reference_table.setHorizontalHeaderLabels(
            ("类型", "声明", "位置", "物理来源")
        )
        self.event_reference_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows
        )
        self.event_reference_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self.event_reference_table.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers
        )
        self.event_reference_table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.Stretch
        )
        event_layout.addWidget(self.event_reference_table)
        event_commands = QtWidgets.QHBoxLayout()
        self.event_add_button = QtWidgets.QPushButton("新增", self.event_group)
        self.event_edit_button = QtWidgets.QPushButton("编辑", self.event_group)
        self.event_delete_button = QtWidgets.QPushButton("删除", self.event_group)
        self.event_open_source_button = QtWidgets.QPushButton(
            "打开来源", self.event_group
        )
        for button, name, tooltip in (
            (self.event_add_button, "event_add_button", "新增当前状态的事件"),
            (self.event_edit_button, "event_edit_button", "编辑所选事件"),
            (self.event_delete_button, "event_delete_button", "删除所选事件声明"),
            (
                self.event_open_source_button,
                "event_open_source_button",
                "在源码工作区定位事件声明",
            ),
        ):
            button.setObjectName(name)
            button.setToolTip(tooltip)
            button.setAccessibleName(button.text())
            event_commands.addWidget(button)
        event_commands.addStretch(1)
        event_layout.addLayout(event_commands)
        self.verticalLayout_3.insertWidget(1, self.event_group)
        self._event_projections = ()
        self.event_add_button.clicked.connect(self._add_event)
        self.event_edit_button.clicked.connect(self._edit_event)
        self.event_delete_button.clicked.connect(self._delete_event)
        self.event_open_source_button.clicked.connect(self._open_event_source)
        self.action_open_event_source = QtWidgets.QAction("打开事件来源", self)
        self.action_open_event_source.setObjectName("action_open_event_source")
        self.action_open_event_source.setShortcut("Ctrl+Return")
        self.action_open_event_source.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        self.event_group.addAction(self.action_open_event_source)
        self.action_open_event_source.triggered.connect(self._open_event_source)
        self.event_table.itemSelectionChanged.connect(
            self._update_event_actions
        )
        self.event_table.itemDoubleClicked.connect(
            lambda item: self._edit_event()
        )
        self.event_reference_table.itemDoubleClicked.connect(
            self._open_event_reference_source
        )
        self._update_event_actions()

    def _init_keyboard_navigation(self):
        order = (
            self.tree_all_state,
            self.button_add_state,
            self.button_fold_all_state,
            self.button_expand_all_state,
            self.event_table,
            self.event_add_button,
            self.event_edit_button,
            self.event_delete_button,
            self.event_open_source_button,
            self.button_lifecycle,
            self.button_transition,
            self.edit_var_def,
            self.table_lifecycle,
            self.table_transition,
            self.source_editor,
            self.task_result_dock.status_filter,
            self.task_result_dock.search_edit,
            self.task_result_dock.table,
        )
        for current, following in zip(order, order[1:]):
            self.setTabOrder(current, following)

    def _finalize_button_accessibility(self):
        internal_names = {
            "qt_dockwidget_floatbutton": "浮动面板",
            "qt_dockwidget_closebutton": "关闭面板",
        }
        for button in self.findChildren(QtWidgets.QAbstractButton):
            parent = button.parentWidget()
            table_name = ""
            if isinstance(parent, QtWidgets.QAbstractItemView):
                table_name = parent.accessibleName() or parent.objectName()
            fallback = (
                button.text()
                or button.toolTip()
                or internal_names.get(button.objectName())
                or button.objectName()
                or (table_name + "全选" if table_name else "")
                or "图标按钮"
            )
            if not button.accessibleName():
                button.setAccessibleName(fallback)
            if not button.toolTip():
                button.setToolTip(button.accessibleName())

    def _focus_find_target(self):
        self.workspace_tabs.setCurrentWidget(self.source_workspace)
        self.source_editor.setFocus(Qt.ShortcutFocusReason)

    def _cancel_active_task(self):
        record = self.task_result_dock.selected_record
        active = {
            HistoryTaskStatus.QUEUED,
            HistoryTaskStatus.RUNNING,
            HistoryTaskStatus.CANCEL_REQUESTED,
        }
        if record is None or record.status not in active:
            record = next(
                (
                    item
                    for item in reversed(self.task_center.records)
                    if item.status in active
                ),
                None,
            )
        return bool(record and self._cancel_task_record(record.task_id))

    def _init_import_state_chart(self):
        self._init_button_initial_import_state_machine()

    def _init_button_initial_import_state_machine(self):
        self.button_initial_import_state_machine.clicked.connect(lambda: self._import_statechart())

    def _init_button_initial_new_state_machine(self):
        self.button_initial_new_state_machine.clicked.connect(lambda: self._new_state_machine())

    def _new_state_machine(self):
        self.state_manager = StateManager()
        self.model_explorer_dock.show()
        self.property_inspector_dock.show()
        if self.at_page_initial:
            self.stackedWidget_state_machine.setCurrentIndex(1)
            self.at_page_initial = False

    def _init_tree_style(self):
        self.tree_all_state.header().hide()
        self.tree_all_state.setTextElideMode(Qt.ElideMiddle)
        self.tree_all_state.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        #self.tree_all_state.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.tree_all_state.header().setMinimumSectionSize(80)
        self.tree_all_state.header().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeToContents
        )
        self.tree_all_state.setAutoScroll(False)

    def _init_button_style(self):
        button_style = """
            QToolButton {
                border: none;
                background-color: #FFFACD;
                font-size: 20px;
                padding: 50px 16px 8px 16px;  /* 上 右 下 左 的内边距 */
                border-radius: 6px;
                spacing: 5px;  /* 图标和文字之间的间距 */
            }

            QToolButton:hover {
                background-color: #ADD8E6;
            }

            QToolButton:pressed {
                background-color: #ADD8E6;
            }
        """
        self.button_initial_new_state_machine.setMinimumSize(300, 300)
        self.button_initial_import_state_machine.setMinimumSize(300, 300)
        self.button_initial_new_state_machine.setStyleSheet(button_style)
        self.button_initial_import_state_machine.setStyleSheet(button_style)
        
        # 设置按钮图标和文字
        new_icon = qta.icon('fa5s.plus-circle', color='#000000')
        import_icon = qta.icon('fa5s.file-import', color='#000000')
        
        self.button_initial_new_state_machine.setIcon(new_icon)
        self.button_initial_import_state_machine.setIcon(import_icon)
        
        # 设置图标大小
        icon_size = 64
        self.button_initial_new_state_machine.setIconSize(PyQt5.Qt.QSize(icon_size, icon_size))
        self.button_initial_import_state_machine.setIconSize(PyQt5.Qt.QSize(icon_size, icon_size))
        
        # 设置文字在图标下方
        self.button_initial_new_state_machine.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.button_initial_import_state_machine.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)

    def _init_text_edit_style(self):
        # 设置字体为微软雅黑，大小为11号
        font = QtGui.QFont("微软雅黑", 11)

        # 设置字体
        self.edit_var_def.setFont(font)

        # 设置tab为4个空格
        self.edit_var_def.setTabStopWidth(
            QtGui.QFontMetrics(font).width(' ') * 4
        )

    def _init_table_style(self):
        """
        初始化表格样式
        """
        # 设置列宽拉伸模式，让所有列填满表格宽度
        header = self.table_transition.horizontalHeader()
        header.setStretchLastSection(True)  # 最后一列拉伸填满剩余空间
        header.setSectionResizeMode(QtWidgets.QHeaderView.Stretch)  # 所有列均匀拉伸

        # 禁止编辑表格内容
        self.table_transition.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        # 设置选择模式为整行选择
        self.table_transition.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)

        # 设置表格样式
        self.table_transition.setAlternatingRowColors(True)  # 交替行颜色
        self.table_transition.setGridStyle(QtCore.Qt.SolidLine)  # 网格线样式
        
        # 设置文本换行和自动调整行高
        self.table_transition.setWordWrap(True)  # 启用文本换行
        self.table_transition.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)  # 行高自适应内容
        
        # 优化工具提示显示速度
        self.table_transition.setMouseTracking(True)  # 启用鼠标追踪
        # 禁用默认的工具提示行为，完全由事件过滤器控制
        self.table_transition.setAttribute(QtCore.Qt.WA_AlwaysShowToolTips, False)
        
        # 安装自定义事件过滤器以实现快速工具提示
        self.table_transition.installEventFilter(self)
        self.table_transition.viewport().installEventFilter(self)

        # 配置生命周期信息表格
        # 设置列宽拉伸模式，让所有列填满表格宽度
        header = self.table_lifecycle.horizontalHeader()
        header.setStretchLastSection(True)  # 最后一列拉伸填满剩余空间
        header.setSectionResizeMode(QtWidgets.QHeaderView.Stretch)  # 所有列均匀拉伸

        # 禁止编辑表格内容
        self.table_lifecycle.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        # 设置选择模式为整行选择
        self.table_lifecycle.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)

        # 设置表格样式
        self.table_lifecycle.setAlternatingRowColors(True)  # 交替行颜色
        self.table_lifecycle.setGridStyle(QtCore.Qt.SolidLine)  # 网格线样式
        
        # 设置文本换行和自动调整行高
        self.table_lifecycle.setWordWrap(True)  # 启用文本换行
        self.table_lifecycle.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)  # 行高自适应内容
        
        # 优化工具提示显示速度
        self.table_lifecycle.setMouseTracking(True)  # 启用鼠标追踪
        # 禁用默认的工具提示行为，完全由事件过滤器控制
        self.table_lifecycle.setAttribute(QtCore.Qt.WA_AlwaysShowToolTips, False)
        
        # 安装自定义事件过滤器以实现快速工具提示
        self.table_lifecycle.installEventFilter(self)
        self.table_lifecycle.viewport().installEventFilter(self)
        
        # 设置生命周期表格的右键菜单
        self._init_lifecycle_context_menu()
        
        # 设置转移表格的右键菜单
        self._init_transition_context_menu()
        
        # 设置全局工具提示延迟时间（毫秒）
        QtWidgets.QApplication.instance().setAttribute(QtCore.Qt.AA_DisableWindowContextHelpButton, True)
        # 减少工具提示显示延迟，默认是700ms，我们设置为200ms
        self._setup_tooltip_timing()

    def _setup_tooltip_timing(self):
        """
        设置工具提示的显示和隐藏时间
        """
        # 获取应用程序实例
        app = QtWidgets.QApplication.instance()
        if app:
            # 设置工具提示的显示延迟为200毫秒（默认700毫秒）
            app.setAttribute(QtCore.Qt.AA_DisableWindowContextHelpButton, True)
            
        # 为表格设置更快的工具提示响应
        style_sheet = """
        QTableWidget {
            alternate-background-color: #f0f0f0;
        }
        QTableWidget::item:hover {
            background-color: #e0e0e0;
        }
        QToolTip {
            background-color: #ffffcc;
            color: #000000;
            border: 1px solid #999999;
            border-radius: 3px;
            padding: 5px;
            font-size: 9pt;
        }
        """
        self.table_transition.setStyleSheet(style_sheet)
        self.table_lifecycle.setStyleSheet(style_sheet)

    def _init_lifecycle_context_menu(self):
        """初始化生命周期表格的右键菜单"""
        self.table_lifecycle.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_lifecycle.customContextMenuRequested.connect(self._show_lifecycle_context_menu)

    def _init_transition_context_menu(self):
        """初始化转移表格的右键菜单"""
        self.table_transition.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_transition.customContextMenuRequested.connect(self._show_transition_context_menu)

    def _init_edit_text_change(self):
        # 连接变量定义文本框的内容变化信号
        self.edit_var_def.textChanged.connect(self._on_var_def_text_changed)

    def _init_tree_all_state_context_menu(self):
        self.tree_all_state.setContextMenuPolicy(Qt.CustomContextMenu)

        self.tree_all_state.customContextMenuRequested.connect(lambda pos: self.show_tree_all_state_context_menu(pos))
        
        # 连接树形控件的选择变化信号
        self.tree_all_state.itemSelectionChanged.connect(self._on_tree_item_selection_changed)

    def show_tree_all_state_context_menu(self, position: QPoint):
        item = self.tree_all_state.itemAt(position)
        if item is None:
            return

        state = item.data(0, Qt.UserRole)
        if state is None:
            return

        menu = QtWidgets.QMenu()
        edit_action = QtWidgets.QAction("修改状态名", self)
        add_action = QtWidgets.QAction("添加子状态", self)
        delete_action = QtWidgets.QAction("删除状态", self)
        export_cur_state_action = QtWidgets.QAction("导出状态", self)

        edit_action.triggered.connect(lambda: self.edit_state(item, state))
        add_action.triggered.connect(lambda: self.add_sub_state(item, state))
        delete_action.triggered.connect(lambda: self.delete_state(item, state))
        export_cur_state_action.triggered.connect(lambda: self.export_cur_state(item, state))

        menu.addAction(edit_action)
        menu.addAction(add_action)
        menu.addAction(delete_action)
        menu.addAction(export_cur_state_action)

        menu.exec_(self.tree_all_state.viewport().mapToGlobal(position))

    def edit_state(self, item, state):
        self._add_state(father_state=None, is_edit=True)

    def add_sub_state(self, parent_item, parent_state):
        self._add_state(father_state=parent_state, is_edit=False)

    def delete_state(self, item, state: State):
        if state.name == self.state_manager.root_state.name:
            QtWidgets.QMessageBox.warning(
                self,
                "警告",
                "状态机根节点不能删除！",
                QtWidgets.QMessageBox.Ok
            )
            return

        reply = QtWidgets.QMessageBox.question(self, "删除确认", f"确定要删除状态 '{state.name}' 和其所有子状态，以及有关的转移吗？",
                                     QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)

        if reply == QtWidgets.QMessageBox.Yes:

            if self.document_session is not None:
                self._delete_projected_state(state)
                return

            self.state_manager.remove_state(state)
            parent_item = item.parent()
            if parent_item:
                parent_item.removeChild(item)
            else:
                index = self.tree_all_state.indexOfTopLevelItem(item)
                self.tree_all_state.takeTopLevelItem(index)

    def export_cur_state(self, item, state: State):
        '''导出当前具体的单个状态'''
        try:
            # 检查上次使用的路径是否存在
            if not os.path.exists(self.state_machine_file_path):
                self.state_machine_file_path = "./"

            options = QtWidgets.QFileDialog.Options()
            file_name, selected_filter = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "导出状态机",
                self.state_machine_file_path,
                "fcstm Files (*.fcstm)",
                options=options
            )

            if not file_name:
                return
            # 更新上次使用的路径
            self.state_machine_file_path = os.path.dirname(file_name)
            if selected_filter == "fcstm Files (*.fcstm)":
                # 确保文件名以 .fcstm 结尾
                if not file_name.endswith('.fcstm'):
                    file_name += '.fcstm'

                # 将具体的某个状态转换为fcstm格式
                cur_state_lines = []
                format_state(state, cur_state_lines, self.state_manager, 0)
                cur_state_str = '\n'.join(cur_state_lines)
                with open(file_name, 'w', encoding='utf-8') as f:
                    f.write(cur_state_str)
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"导出状态机时发生错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _init_button_state_machine_add_state(self):
        self.button_add_state.clicked.connect(lambda: self._buton_add_state())

    def _init_button_state_machine_expand_all(self):
        self.button_expand_all_state.setToolTip("展开所有")
        expand_icon = qta.icon('fa5s.angle-down', color='#000000')
        self.button_expand_all_state.setIcon(expand_icon)
        self.button_expand_all_state.setIconSize(PyQt5.Qt.QSize(25, 25))
        self.button_expand_all_state.clicked.connect(lambda: self._expand_all_state(self.tree_all_state))

    def _init_button_state_machine_fold_all(self):
        self.button_fold_all_state.setToolTip("折叠所有")
        fold_icon = qta.icon('fa5s.angle-up', color='#000000')
        self.button_fold_all_state.setIcon(fold_icon)
        self.button_fold_all_state.setIconSize(PyQt5.Qt.QSize(25, 25))
        self.button_fold_all_state.clicked.connect(lambda: self._fold_all_state(self.tree_all_state))

    def _expand_all_state(self, tree_widget: QtWidgets.QTreeWidget):
        tree_widget.expandAll()

    def _fold_all_state(self, tree_widget: QtWidgets.QTreeWidget):
        tree_widget.collapseAll()

    def _init_button_lifecycle(self):
        """初始化生命周期按钮"""
        self.button_lifecycle.clicked.connect(self._on_button_lifecycle_clicked)

    def _init_button_transition(self):
        """初始化转移按钮"""
        self.button_transition.clicked.connect(self._on_button_transition_clicked)

    def _on_button_lifecycle_clicked(self):
        """处理生命周期按钮点击事件"""
        try:
            # 检查是否有状态管理器
            if self.state_manager is None:
                QtWidgets.QMessageBox.warning(
                    self,
                    "警告",
                    "请先创建或导入状态机！",
                    QtWidgets.QMessageBox.Ok
                )
                return

            # 获取当前选中的状态
            current_state = self._get_pro_state()
            if current_state is None:
                QtWidgets.QMessageBox.warning(
                    self,
                    "警告",
                    "请先选择一个状态！",
                    QtWidgets.QMessageBox.Ok
                )
                return

            # 显示生命周期添加对话框
            dialog = DialogAddLifecycle(
                self,
                self.state_manager,
                current_state,
                mutate_model=self.document_session is None,
            )
            if dialog.exec_() == QtWidgets.QDialog.Accepted:
                if self.document_session is not None:
                    self._insert_state_declaration(
                        current_state,
                        "lifecycle",
                        format_lifecycle_item(dialog.get_lifecycle_data()),
                    )
                else:
                    self._update_lifecycle_table(current_state.lifecycle)
                
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"添加生命周期操作时发生错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _on_button_transition_clicked(self):
        """处理转移按钮点击事件"""
        try:
            # 检查是否有状态管理器
            if self.state_manager is None:
                QtWidgets.QMessageBox.warning(
                    self,
                    "警告",
                    "请先创建或导入状态机！",
                    QtWidgets.QMessageBox.Ok
                )
                return

            # 获取当前选中的状态
            current_state = self._get_pro_state()
            if current_state is None:
                QtWidgets.QMessageBox.warning(
                    self,
                    "警告",
                    "请先选择一个状态！",
                    QtWidgets.QMessageBox.Ok
                )
                return

            # 显示转移添加对话框
            dialog = DialogAddTransition(
                self,
                self.state_manager,
                current_state,
                mutate_model=self.document_session is None,
            )
            if dialog.exec_() == QtWidgets.QDialog.Accepted:
                if self.document_session is not None:
                    declaration = format_transition_item(
                        dialog.get_transition_data()
                    )
                    if declaration and not declaration.rstrip().endswith("}"):
                        declaration += ";"
                    self._insert_state_declaration(
                        current_state, "transition", declaration
                    )
                else:
                    self._update_transition_table(current_state.transitions)
                
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"添加转移操作时发生错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _buton_add_state(self):
        father_state = self._get_pro_state()
        if father_state is None and self.state_manager.get_root_state() is not None:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                "状态机中只能有一个根状态",
                QtWidgets.QMessageBox.Ok
            )
            return
        else:
            self._add_state(father_state, False)

    def _add_state(self, father_state: Optional[State], is_edit = False):
        """
        保存状态信息，并使用QTreeWidget展示状态
        """
        try:
            if self.document_session is not None and not is_edit:
                dialog = DialogEditState(
                    self,
                    state_manager=self.state_manager,
                    is_edit=False,
                    initial_data=None,
                    parent_state=father_state,
                )
                if dialog.exec_() == QtWidgets.QDialog.Accepted:
                    if father_state is None:
                        QtWidgets.QMessageBox.warning(
                            self, "不可编辑", "已有文档不能新增第二个根状态。"
                        )
                        return
                    self._insert_state_declaration(
                        father_state,
                        "state",
                        "state {};".format(dialog.get_state_name()),
                    )
                return
            if is_edit:
                # 获取当前编辑状态
                pro_state = self._get_pro_state()
                if pro_state is None:
                    QtWidgets.QMessageBox.warning(self, "提示", "请先选择要编辑的状态")
                    return
                    
                dialog = DialogEditState(self, state_manager=self.state_manager, is_edit=True, initial_data=pro_state)
                if dialog.exec_() == QtWidgets.QDialog.Accepted:
                    new_state_name = dialog.get_state_name()
                    if self.document_session is not None:
                        self._rename_projected_state(
                            pro_state, new_state_name
                        )
                        return
                    # 改变原状态的名字
                    try:
                        self.state_manager.rename_state(pro_state, new_state_name)
                        cur_tree_item = self.tree_all_state.currentItem()
                        cur_tree_item.setText(0, new_state_name)
                    except Exception as e:
                        QtWidgets.QMessageBox.critical(
                            self,
                            "错误",
                            f"编辑状态时发生错误：\n{str(e)}",
                            QtWidgets.QMessageBox.Ok
                        )
                        return
            else:
                # 添加新状态
                dialog = DialogEditState(self, state_manager=self.state_manager, is_edit=False, initial_data=None, parent_state=father_state)
                if dialog.exec_() == QtWidgets.QDialog.Accepted:
                    new_state_name = dialog.get_state_name()
                    try:
                        new_state = State(new_state_name)
                        if father_state is None and self.state_manager.get_root_state() is None:
                            self.state_manager.root_state = new_state
                        self.state_manager.add_state(father_state, new_state)
                        cur_state_item = QtWidgets.QTreeWidgetItem([new_state_name])
                        cur_state_item.setData(0, Qt.UserRole, new_state)
                        # 如果是添加子状态：
                        if father_state is not None:
                            father_item = self.tree_all_state.currentItem()
                            father_item.addChild(cur_state_item)
                        else:
                            self.tree_all_state.addTopLevelItem(cur_state_item)
                    except Exception as e:
                        QtWidgets.QMessageBox.critical(
                            self,
                            "错误",
                            f"添加状态时发生错误：\n{str(e)}",
                            QtWidgets.QMessageBox.Ok
                        )
                        return
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"操作状态时发生未知错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _import_statechart(self):
        """导入 xml 文件"""
        try:
            # 检查上次使用的路径是否存在
            if not os.path.exists(self.state_machine_file_path):
                self.state_machine_file_path = "./"
                
            file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, 
                "选择fcstm文件",
                self.state_machine_file_path, 
                "fcstm Files (*.fcstm);;All Files (*)"
            )
            if not file_path:
                return
            if not self._confirm_document_replacement():
                return
                
            # 更新上次使用的路径
            self.state_machine_file_path = os.path.dirname(file_path)
            
            return self._start_document_load(file_path)
                
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"导入状态机时发生未知错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _confirm_document_replacement(self):
        if self.document_session is None or not self.document_session.dirty:
            return True
        reply = QtWidgets.QMessageBox.question(
            self,
            "未保存的修改",
            "当前文档有未保存的修改。",
            QtWidgets.QMessageBox.Save
            | QtWidgets.QMessageBox.Discard
            | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Save,
        )
        if reply == QtWidgets.QMessageBox.Cancel:
            return False
        if reply == QtWidgets.QMessageBox.Save:
            return self._save_current_document()
        return True

    def _start_document_load(
        self, file_path, encoding=None, encoding_hints=(), operation=None
    ):
        service = self.document_service
        new_operation = operation is None
        operation = operation or DocumentLoadOperation(parent=self)
        if new_operation:
            record = TaskRecord(
                task_id=operation.operation_id,
                kind="document-load",
                session_id="",
                source_revision=0,
                dependency_fingerprints={},
                created_at=time.time(),
                status=HistoryTaskStatus.QUEUED,
                summary="等待加载 {}".format(file_path),
                messages=(),
                artifacts=(),
                retry_descriptor={
                    "kind": "document-load",
                    "path": str(file_path),
                    "encoding": encoding,
                    "encoding_hints": list(encoding_hints),
                },
                exception_chain=(),
                boundary=TaskBoundary.EXPLICIT,
            )
            self.task_center.add(record)
            self.task_center.transition(
                operation.operation_id,
                HistoryTaskStatus.RUNNING,
                summary="正在加载 {}".format(file_path),
            )
            self._logical_load_operations[operation.operation_id] = operation
            self._refresh_task_result_dock(show=True)

        def load_document(token):
            token.raise_if_cancelled()
            session = service.load(
                file_path,
                encoding=encoding,
                encoding_hints=encoding_hints,
            )
            token.raise_if_cancelled()
            return session

        try:
            handle = self.task_runner.submit(
                "document-load",
                0,
                load_document,
                channel="document-load",
            )
        except BaseException as error:
            result = TaskResult(
                stamp=TaskStamp(
                    task_id=uuid.uuid4().hex,
                    channel="document-load",
                    session_id="",
                    source_revision=0,
                    request_generation=0,
                ),
                status=TaskStatus.FAILED,
                error=error,
            )
            outcome = DocumentLoadOutcome(
                operation_id=operation.operation_id,
                task_result=result,
            )
            operation.finish(outcome)
            self.document_load_finished.emit(outcome)
            self._complete_load_task(outcome, file_path)
            return operation
        operation.current_attempt = handle
        self._document_load_requests[handle.stamp.task_id] = (
            operation,
            file_path,
            encoding,
            tuple(encoding_hints),
        )
        handle.finished.connect(self._finish_document_load)
        return operation

    def _prompt_source_encoding(self, path):
        label, accepted = QtWidgets.QInputDialog.getItem(
            self,
            "选择源码编码",
            "{} 的编码：".format(path),
            ("UTF-8", "GB18030", "Big5"),
            0,
            False,
        )
        if not accepted:
            return None
        return {
            "UTF-8": "utf-8",
            "GB18030": "gb18030",
            "Big5": "big5",
        }[label]

    @QtCore.pyqtSlot(object)
    def _finish_document_load(self, result):
        request = self._document_load_requests.pop(
            result.stamp.task_id, (None, None, None, ())
        )
        operation, file_path, encoding, encoding_hints = request
        retrying = False
        ui_error = None
        logical_status = None
        try:
            if result.status is not TaskStatus.SUCCESS:
                if result.status is TaskStatus.FAILED:
                    if isinstance(
                        result.error, (SourceEncodingAmbiguityError, UnicodeError)
                    ) and file_path is not None:
                        selected = self._prompt_source_encoding(file_path)
                        if selected is not None:
                            retrying = True
                            self._start_document_load(
                                file_path,
                                encoding=selected,
                                encoding_hints=encoding_hints,
                                operation=operation,
                            )
                            return
                        logical_status = TaskStatus.CANCELLED
                    else:
                        QtWidgets.QMessageBox.critical(
                            self,
                            "导入失败",
                            "读取fcstm文件时发生错误：\n{}".format(result.error),
                            QtWidgets.QMessageBox.Ok,
                        )
                return
            session = result.value
            if session.validation_state not in {
                ValidationState.VALID,
                ValidationState.VALID_WITH_WARNINGS,
            }:
                decode_error = next(
                    (
                        item
                        for item in session.current_diagnostics
                        if getattr(item, "operation", None) == "decode"
                        and getattr(item, "path", None)
                    ),
                    None,
                )
                if decode_error is not None and file_path is not None:
                    selected = self._prompt_source_encoding(decode_error.path)
                    if selected is not None:
                        hints = dict(encoding_hints)
                        hints[decode_error.path] = selected
                        retrying = True
                        self._start_document_load(
                            file_path,
                            encoding=encoding,
                            encoding_hints=tuple(hints.items()),
                            operation=operation,
                        )
                        return
                    logical_status = TaskStatus.CANCELLED
                    return
                if session.validation_state is ValidationState.STALE_DEPENDENCY:
                    logical_status = TaskStatus.FAILED
                    ui_error = DocumentDependencyLoadError(session)
                    detail = "\n".join(
                        str(item) for item in session.current_diagnostics
                    )
                    QtWidgets.QMessageBox.critical(
                        self,
                        "依赖加载失败",
                        "源码依赖无法读取，当前文档保持不变：\n{}".format(
                            detail
                        ),
                        QtWidgets.QMessageBox.Ok,
                    )
                    return
                self.command_stack.reset_document(session)
                self._set_active_document_session(session)
                detail = "\n".join(str(item) for item in session.current_diagnostics)
                QtWidgets.QMessageBox.critical(
                    self,
                    "导入失败",
                    "解析fcstm文件时发生错误：\n{}".format(detail),
                    QtWidgets.QMessageBox.Ok,
                )
                return
            self.document_service.require_current_valid_snapshot(session)
            snapshot = session.require_current_valid_snapshot()
            manager = convert_state_machine_to_state_manager(
                snapshot.model,
                extract_variable_definitions(session.source_text),
                source_index=snapshot.source_index,
            )
            self.command_stack.reset_document(session)
            self._set_active_document_session(session, manager=manager)
        except DocumentDependencyStaleError as error:
            ui_error = error
            QtWidgets.QMessageBox.critical(
                self,
                "导入失败",
                "依赖文件在加载期间发生变化：\n{}".format(error),
                QtWidgets.QMessageBox.Ok,
            )
        except BaseException as error:
            ui_error = error
            QtWidgets.QMessageBox.critical(
                self,
                "导入失败",
                "加载结果无法安装到界面：\n{}".format(error),
                QtWidgets.QMessageBox.Ok,
            )
        finally:
            if not retrying and operation is not None:
                outcome = DocumentLoadOutcome(
                    operation_id=operation.operation_id,
                    task_result=result,
                    ui_error=ui_error,
                    logical_status=logical_status,
                )
                operation.finish(outcome)
                self.document_load_finished.emit(outcome)
                self._complete_load_task(outcome, file_path)

    def _set_active_document_session(self, session, manager=None):
        if manager is None and session.current_valid_snapshot is not None:
            snapshot = session.current_valid_snapshot
            manager = convert_state_machine_to_state_manager(
                snapshot.model,
                extract_variable_definitions(session.source_text),
                source_index=snapshot.source_index,
            )

        previous_session = self.document_session
        previous_manager = getattr(self, "state_manager", None)
        previous_source_text = self.source_editor.toPlainText()
        previous_workspace_index = self.workspace_tabs.currentIndex()
        previous_page = self.stackedWidget_state_machine.currentIndex()
        previous_at_initial = self.at_page_initial
        previous_selected_state_path = self._selected_state_path()
        preserve_selected_state_path = (
            previous_selected_state_path
            if previous_session is not None
            and previous_session.session_id == session.session_id
            else None
        )
        try:
            if self.source_editor.toPlainText() != session.source_text:
                self._setting_source_text = True
                try:
                    self.source_editor.setPlainText(session.source_text)
                finally:
                    self._setting_source_text = False
            self._setting_projection = True
            try:
                if manager is None:
                    self._clear_model_projection()
                    self.workspace_tabs.setCurrentWidget(self.source_workspace)
                else:
                    update_ui_from_state_manager(self, manager)
                    self.workspace_tabs.setCurrentWidget(self.model_workspace)
            finally:
                self._setting_projection = False
        except BaseException:
            self.document_session = previous_session
            self.state_manager = previous_manager
            self._setting_source_text = True
            try:
                self.source_editor.setPlainText(previous_source_text)
            finally:
                self._setting_source_text = False
            self._setting_projection = True
            try:
                if previous_manager is None:
                    self._clear_model_projection()
                else:
                    update_ui_from_state_manager(self, previous_manager)
            finally:
                self._setting_projection = False
                self.at_page_initial = previous_at_initial
                self.stackedWidget_state_machine.setCurrentIndex(previous_page)
                self.workspace_tabs.setCurrentIndex(previous_workspace_index)
                self._update_document_actions()
            self._restore_state_tree_selection(previous_selected_state_path)
            raise

        self.document_session = session
        self.state_manager = manager
        self.at_page_initial = False
        self.stackedWidget_state_machine.setCurrentWidget(
            self.page_state_machine_detail
        )
        self._restore_state_tree_selection(preserve_selected_state_path)
        self.model_explorer_dock.show()
        self.property_inspector_dock.show()
        self._record_recent_file(session.path)
        self._update_document_actions()

    def _record_recent_file(self, path):
        canonical = str(canonical_path(path))
        canonical_key = os.path.normcase(canonical)
        recent = list(self.settings.value("recent_files", [], type=list))
        recent = [
            item
            for item in recent
            if os.path.normcase(str(canonical_path(item))) != canonical_key
        ]
        recent.insert(0, canonical)
        self.settings.setValue("recent_files", recent[:10])

    def _clear_model_projection(self):
        self._variable_edit_timer.stop()
        previous = self._setting_projection
        self._setting_projection = True
        try:
            self.state_manager = None
            self.tree_all_state.clear()
            self.edit_var_def.clear()
            self.table_transition.setRowCount(0)
            self.table_lifecycle.setRowCount(0)
        finally:
            self._setting_projection = previous

    def _update_document_actions(self):
        session = self.document_session
        current_valid = (
            session is not None and session.current_valid_snapshot is not None
        )
        self.action_save_state_machine.setEnabled(session is not None)
        self.action_graph_gen.setEnabled(current_valid)
        self.action_code_gen.setEnabled(current_valid)
        self.action_unified_export.setEnabled(current_valid)
        self.action_undo.setEnabled(
            session is not None
            and (
                self.command_stack.can_undo
                or self.source_editor.document().isUndoAvailable()
            )
        )
        self.action_redo.setEnabled(
            session is not None
            and (
                self.command_stack.can_redo
                or self.source_editor.document().isRedoAvailable()
            )
        )
        self.edit_var_def.setReadOnly(session is not None and not current_valid)
        self.button_add_state.setEnabled(session is None or current_valid)
        self.button_lifecycle.setEnabled(session is None or current_valid)
        self.button_transition.setEnabled(session is None or current_valid)
        diagnostics_index = self.workspace_tabs.indexOf(
            self.diagnostics_workspace
        )
        self.workspace_tabs.setTabEnabled(
            diagnostics_index, session is not None
        )
        snapshot = session.current_valid_snapshot if current_valid else None
        for page in (
            self.graph_workspace,
            self.simulation_workspace,
            self.dynamic_validation_workspace,
        ):
            self.workspace_tabs.setTabEnabled(
                self.workspace_tabs.indexOf(page), current_valid
            )
        fingerprint = snapshot.dependency_fingerprint if snapshot is not None else None
        revision = session.source_revision if session is not None else None
        self.simulation_panel.set_document_available(
            current_valid, revision=revision, fingerprint=fingerprint
        )
        self.dynamic_validation_panel.set_document_available(current_valid)
        self.graph_panel.set_available(
            current_valid,
            revision=revision,
            selected_path=self._selected_state_path(),
        )
        if self._simulation_session is not None and not (
            current_valid
            and self._simulation_session.matches(revision, fingerprint)
        ):
            self._simulation_session = None
            self.simulation_panel.invalidate()
        self._refresh_diagnostics_panel()
        self.setWindowModified(bool(session and session.dirty))
        if session is not None:
            self.setWindowFilePath(session.path)
            self._document_display_name = os.path.basename(session.path)
            if self.task_result_dock.show_full_paths_action.isChecked():
                document_tooltip = session.path
            else:
                document_tooltip = self.task_center.redactor.redact_text(
                    session.path
                )
            self.document_name_label.setToolTip(document_tooltip)
            self._update_document_name_label()
            self.document_dirty_label.setText(
                "未保存" if session.dirty else "已保存"
            )
            self.document_revision_label.setText(
                "revision {}".format(session.source_revision)
            )
            self.document_validation_label.setText(
                session.validation_state.value
            )
            snapshot = session.current_valid_snapshot
            dependency_count = (
                len(snapshot.dependency_manifest) if snapshot is not None else 0
            )
            self.document_dependency_label.setText(
                "依赖 {}".format(dependency_count)
            )

    def _refresh_diagnostics_panel(self):
        redactor = (
            (lambda value: value)
            if self.task_result_dock.show_full_paths_action.isChecked()
            else self.task_center.redactor.redact_text
        )
        self.diagnostics_panel.set_redactor(redactor)
        session = self.document_session
        if session is None or not session.current_diagnostics:
            self.diagnostics_panel.clear()
            return
        snapshot = session.current_valid_snapshot or session.last_valid_snapshot
        dependency_fingerprint = (
            snapshot.dependency_fingerprint if snapshot is not None else None
        )
        source_kind = DiagnosticSourceKind(
            session.diagnostic_source_kind
            or (
                "syntax"
                if session.validation_state is ValidationState.INVALID_SYNTAX
                else "model"
            )
        )
        source_uri = Path(
            os.path.normcase(str(canonical_path(session.path)))
        ).as_uri()
        report = self.diagnostic_service.from_native_items(
            session.current_diagnostics,
            source_kind,
            source_uri,
            session.source_revision,
            dependency_fingerprint,
        )
        self.diagnostics_panel.set_report(
            report,
            session.source_revision,
            dependency_fingerprint,
        )

    def _locate_diagnostic(self, item):
        session = self.document_session
        if (
            session is None
            or item.source_revision != session.source_revision
            or item.span is None
        ):
            return False
        if not self._diagnostic_stamp_current(item):
            return False
        snapshot = session.current_valid_snapshot or session.last_valid_snapshot
        root_uri = Path(
            os.path.normcase(str(canonical_path(session.path)))
        ).as_uri()
        if item.source_uri == root_uri:
            editor = self.source_editor
            self.workspace_tabs.setCurrentWidget(self.source_workspace)
        else:
            if snapshot is None:
                return False
            document = next(
                (
                    candidate
                    for candidate in snapshot.source_index.documents.values()
                    if candidate.uri == item.source_uri
                ),
                None,
            )
            if document is None:
                return False
            editor = self._imported_source_editor(document)
        document = editor.document()
        start_block = document.findBlockByNumber(max(0, item.span.line - 1))
        if not start_block.isValid():
            return False
        start = min(
            start_block.position() + max(0, item.span.column),
            start_block.position() + max(0, start_block.length() - 1),
        )
        end = start + max(1, len(item.offending_symbol_text or ""))
        if item.span.end_line is not None and item.span.end_column is not None:
            end_block = document.findBlockByNumber(
                max(0, item.span.end_line - 1)
            )
            if end_block.isValid():
                end = end_block.position() + max(0, item.span.end_column)
        cursor = editor.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(min(end, document.characterCount() - 1), QtGui.QTextCursor.KeepAnchor)
        editor.setTextCursor(cursor)
        QtCore.QTimer.singleShot(0, editor.setFocus)
        return True

    def _diagnostic_stamp_current(self, item):
        session = self.document_session
        if session is None or item.source_revision != session.source_revision:
            return False
        snapshot = session.current_valid_snapshot or session.last_valid_snapshot
        current_dependency_fingerprint = (
            snapshot.dependency_fingerprint if snapshot is not None else None
        )
        if (
            item.dependency_fingerprint != current_dependency_fingerprint
            or (
                snapshot is not None
                and not snapshot.source_index.matches_dependencies_on_disk()
            )
        ):
            return False
        return True

    def _apply_diagnostic_suggested_fix(self, item):
        if not self._diagnostic_stamp_current(item):
            return False
        fix = item.suggested_fix
        if fix is None:
            return False
        preview = fix.text_template or "（删除目标源码）"
        reply = QtWidgets.QMessageBox.question(
            self,
            "建议修复预览",
            "{}\n\n修改：\n{}\n\n确认应用并重新校验？".format(
                fix.rationale, preview
            ),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return False
        refs = item.refs or {}
        if fix.kind == "insert":
            owner_path = refs.get("parent_path") or refs.get("composite_path")
            state = (
                self.state_manager.get_state_by_path(owner_path)
                if self.state_manager is not None and owner_path
                else None
            )
            if state is not None:
                return self._insert_state_declaration(
                    state, "transition", fix.text_template.strip()
                )
        elif fix.kind == "delete":
            snapshot = self.document_session.require_current_valid_snapshot()
            source_ref = None
            if fix.target == "variable_definition":
                name = refs.get("definition_delete_anchor")
                source_ref = next(
                    (
                        candidate
                        for candidate in snapshot.source_index.refs(kind="variable")
                        if candidate.stable_key == "variable:{}".format(name)
                    ),
                    None,
                )
            elif fix.target == "effect_self_assign_statement":
                name = refs.get("effect_self_assign_anchor")
                expected = "{} = {};".format(name, name)
                transition_range = self._diagnostic_ref_offset_range(
                    snapshot.source_index.root_document,
                    refs.get("transition_span"),
                )
                source_ref = next(
                    (
                        candidate
                        for candidate in snapshot.source_index.refs(kind="action")
                        if snapshot.source_index.text_for_ref(candidate).strip()
                        == expected
                        and transition_range is not None
                        and transition_range[0]
                        <= candidate.span.start_offset
                        < candidate.span.end_offset
                        <= transition_range[1]
                    ),
                    None,
                )
            if source_ref is not None and source_ref.editable:
                edit = TextEdit.for_ref(
                    self.document_session.source_revision,
                    source_ref,
                    "",
                    intent="apply suggested fix",
                )
                return self._commit_form_edits(
                    (edit,),
                    preview_title="应用建议修复",
                    declaration_ref=source_ref,
                )
        QtWidgets.QMessageBox.warning(
            self,
            "无法应用建议修复",
            "当前 revision 无法将上游建议安全映射到可编辑源码。",
        )
        return False

    @staticmethod
    def _diagnostic_ref_offset_range(document, span):
        if span is None:
            return None

        def field(name):
            if hasattr(span, "get"):
                return span.get(name)
            return getattr(span, name, None)

        line = field("line")
        column = field("column")
        end_line = field("end_line")
        end_column = field("end_column")
        if not all(
            isinstance(value, int)
            for value in (line, column, end_line, end_column)
        ):
            return None
        if line < 1 or end_line < line or end_line > len(document.line_index):
            return None
        start = document.line_index[line - 1] + max(0, column)
        end = document.line_index[end_line - 1] + max(0, end_column)
        return max(0, start), min(len(document.text), end)

    def _update_document_name_label(self):
        width = max(40, self.document_name_label.width() - 4)
        self.document_name_label.setText(
            self.document_name_label.fontMetrics().elidedText(
                self._document_display_name, Qt.ElideMiddle, width
            )
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "document_name_label"):
            self._update_document_name_label()

    def _on_source_text_changed(self):
        if self._setting_source_text or self.document_session is None:
            return
        source_text = self.source_editor.toPlainText()
        pending = self.document_service.prepare_source_text(
            self.document_session, source_text
        )
        if pending is self.document_session:
            return
        self.command_stack.clear()
        self.task_runner.supersede(
            "model-check", self.document_session.session_id
        )
        self.task_runner.supersede(
            "ordinary-simulation", self.document_session.session_id
        )
        self.task_runner.supersede(
            "dynamic-validation", self.document_session.session_id
        )
        for channel in ("graph-render", "code-generation", "unified-export"):
            self.task_runner.supersede(channel, self.document_session.session_id)
        self.document_session = pending
        self._clear_model_projection()
        self._update_document_actions()
        service = self.document_service

        def validate_document(token):
            token.raise_if_cancelled()
            validated = service.validate(pending)
            token.raise_if_cancelled()
            return validated

        dependency_fingerprint = None
        if pending.last_valid_snapshot is not None:
            dependency_fingerprint = (
                pending.last_valid_snapshot.dependency_fingerprint
            )
        handle = self.task_runner.submit(
            "document-validate",
            pending.source_revision,
            validate_document,
            session_id=pending.session_id,
            channel="document-validate",
            dependency_fingerprint=dependency_fingerprint,
        )
        self.task_center.add(
            TaskRecord(
                task_id=handle.stamp.task_id,
                kind="document-validate",
                session_id=handle.stamp.session_id,
                source_revision=handle.stamp.source_revision,
                dependency_fingerprints={},
                created_at=time.time(),
                status=HistoryTaskStatus.RUNNING,
                summary="正在校验源码",
                messages=(),
                artifacts=(),
                retry_descriptor=None,
                exception_chain=(),
                boundary=TaskBoundary.TRANSIENT,
                started_at=time.time(),
            )
        )
        self._refresh_task_result_dock()
        handle.finished.connect(self._finish_document_validation)

    @QtCore.pyqtSlot(object)
    def _finish_document_validation(self, result):
        try:
            try:
                self.task_center.apply_result(result)
            except KeyError:
                pass
            self._refresh_task_result_dock()
            current = self.document_session
            if result.status is not TaskStatus.SUCCESS or current is None:
                return
            validated = result.value
            if (
                validated.session_id != current.session_id
                or validated.source_revision != current.source_revision
                or validated.source_text != current.source_text
            ):
                return
            self._set_active_document_session(validated)
        finally:
            self.document_validation_finished.emit(result)

    def _save_current_document(self):
        if self.document_session is None:
            return False
        try:
            saved = self.document_service.save(self.document_session)
        except InvalidDocumentSaveError:
            reply = QtWidgets.QMessageBox.question(
                self,
                "保存无效源码",
                "当前源码未通过完整校验，仍保存源码吗？",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if reply != QtWidgets.QMessageBox.Yes:
                return False
            saved = self.document_service.save(
                self.document_session, allow_invalid=True
            )
        except Exception as error:
            QtWidgets.QMessageBox.critical(
                self,
                "保存失败",
                "保存源码时发生错误：\n{}".format(error),
                QtWidgets.QMessageBox.Ok,
            )
            return False
        self.document_session = saved
        self.command_stack.mark_saved(saved)
        self._update_document_actions()
        return True

    def closeEvent(self, event):
        if (
            self.isVisible()
            and self.document_session is not None
            and self.document_session.dirty
        ):
            reply = QtWidgets.QMessageBox.question(
                self,
                "未保存的修改",
                "当前文档有未保存的修改。",
                QtWidgets.QMessageBox.Save
                | QtWidgets.QMessageBox.Discard
                | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Save,
            )
            if reply == QtWidgets.QMessageBox.Cancel:
                event.ignore()
                return
            if reply == QtWidgets.QMessageBox.Save and not self._save_current_document():
                event.ignore()
                return
        self.task_runner.shutdown(wait=False)
        super().closeEvent(event)

    def _export_statechart(self):
        try:
            # 检查上次使用的路径是否存在
            if not os.path.exists(self.state_machine_file_path):
                self.state_machine_file_path = "./"
                
            options = QtWidgets.QFileDialog.Options()
            file_name, selected_filter = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "导出状态机",
                self.state_machine_file_path,
                "fcstm Files (*.fcstm);;Word Documents (*.docx);;Excel Files (*.xlsx);;All Files (*)",
                options=options
            )
            
            if not file_name:
                return
                
            # 更新上次使用的路径
            self.state_machine_file_path = os.path.dirname(file_name)
            try:
                if selected_filter == "fcstm Files (*.fcstm)":
                    # 确保文件名以 .fcstm 结尾
                    if not file_name.endswith('.fcstm'):
                        file_name += '.fcstm'

                    if self.document_session is not None:
                        payload = self.document_session.source_text.encode(
                            self.document_session.encoding
                        )
                    else:
                        payload = state_manager_to_dsl(
                            self.state_manager
                        ).encode("utf-8")
                    with open(file_name, "wb") as file:
                        file.write(payload)

                elif selected_filter == "Word Documents (*.docx)":
                    if self.document_session is not None:
                        if self._require_current_snapshot_for_action("导出") is None:
                            return
                    # 确保文件名以 .docx 结尾
                    if not file_name.endswith('.docx'):
                        file_name += '.docx'
                    export_statechart_to_word(self.state_manager, file_name)
                elif selected_filter == "Excel Files (*.xlsx)":
                    if self.document_session is not None:
                        if self._require_current_snapshot_for_action("导出") is None:
                            return
                    # 确保文件名以 .xlsx 结尾
                    if not file_name.endswith('.xlsx'):
                        file_name += '.xlsx'
                    export_statechart_to_excel(self.state_manager, file_name)
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self,
                    "导出失败",
                    f"导出文件时发生错误：\n{str(e)}",
                    QtWidgets.QMessageBox.Ok
                )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"导出状态机时发生未知错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _validate_statechart(self):
        """验证状态机"""
        try:
            if self.document_session is not None:
                snapshot = self._require_current_snapshot_for_action("模型检查")
                if snapshot is None:
                    return
                session = self.document_session
                service = self.document_service

                def inspect_document(token):
                    token.raise_if_cancelled()
                    current = service.require_current_valid_snapshot(session)
                    report = current.inspect_report
                    token.raise_if_cancelled()
                    service.require_current_valid_snapshot(session)
                    token.raise_if_cancelled()
                    return report

                handle = self.task_runner.submit(
                    "model-check",
                    session.source_revision,
                    inspect_document,
                    session_id=session.session_id,
                    channel="model-check",
                    dependency_fingerprint=snapshot.dependency_fingerprint,
                )
                self._task_handles[handle.stamp.task_id] = handle
                self.task_center.add(
                    TaskRecord(
                        task_id=handle.stamp.task_id,
                        kind="model-check",
                        session_id=session.session_id,
                        source_revision=session.source_revision,
                        dependency_fingerprints=dict(
                            snapshot.dependency_manifest
                        ),
                        created_at=time.time(),
                        started_at=time.time(),
                        status=HistoryTaskStatus.RUNNING,
                        summary="正在检查当前模型",
                        messages=(),
                        artifacts=(),
                        retry_descriptor={"kind": "model-check"},
                        exception_chain=(),
                        boundary=TaskBoundary.EXPLICIT,
                    )
                )
                handle.finished.connect(self._finish_model_check)
                self._refresh_task_result_dock(show=True)
                return handle
            # 获取当前的DSL代码
            dsl_content = state_manager_to_dsl(self.state_manager)
            
            # 解析DSL
            ast_node = parse_with_grammar_entry(dsl_content, entry_name='state_machine_dsl')
            parse_dsl_node_to_state_machine(ast_node)
            
            # 验证成功
            QtWidgets.QMessageBox.information(self, "验证结果", "状态机验证通过！")
            
        except Exception as e:
            error_msg = str(e)
            # 提取错误行号
            error_lines = []
            line_pattern = re.compile(r'line (\d+)')
            matches = line_pattern.findall(error_msg)
            if matches:
                error_lines = [int(line) for line in matches]
            
            # 显示错误对话框
            dsl_content = state_manager_to_dsl(self.state_manager)
            dialog = DialogShowError(
                parent=self,
                dsl_code=dsl_content,
                error_info=error_msg,
                error_lines=error_lines
            )
            dialog.exec_()

    @QtCore.pyqtSlot(object)
    def _finish_model_check(self, result):
        if (
            result.status is TaskStatus.SUCCESS
            and not self._task_stamp_current(result.stamp)
        ):
            result = replace(result, status=TaskStatus.STALE, value=None)
            handle = self._task_handles.get(result.stamp.task_id)
            if handle is not None:
                handle.result = result
        status = {
            TaskStatus.SUCCESS: HistoryTaskStatus.SUCCESS,
            TaskStatus.FAILED: HistoryTaskStatus.FAILED,
            TaskStatus.CANCELLED: HistoryTaskStatus.CANCELLED,
            TaskStatus.STALE: HistoryTaskStatus.STALE,
        }[result.status]
        current = self.document_session
        messages = ()
        if (
            status is HistoryTaskStatus.SUCCESS
            and current is not None
            and self._task_stamp_current(result.stamp)
        ):
            messages = tuple(
                {
                    "severity": getattr(item, "severity", "info"),
                    "message": str(item),
                }
                for item in current.current_diagnostics
            )
        summary = {
            HistoryTaskStatus.SUCCESS: "模型检查完成",
            HistoryTaskStatus.CANCELLED: "模型检查已取消",
            HistoryTaskStatus.STALE: "模型检查结果已过期",
        }.get(status, "模型检查失败：{}".format(result.error))
        try:
            self.task_center.complete_persistent(
                result.stamp.task_id,
                status,
                summary=summary,
                messages=messages,
                exception=result.error,
            )
        except OSError as error:
            self.statusbar.showMessage(
                "任务历史写入失败，原历史保持不变：{}".format(error),
                15000,
            )
        finally:
            self._task_handles.pop(result.stamp.task_id, None)
            self._refresh_task_result_dock(show=True)
            self.model_check_finished.emit(result)

    def _graph_gen(self):
        if self._require_current_snapshot_for_action("状态图") is None:
            return None
        self.workspace_tabs.setCurrentWidget(self.graph_workspace)
        return self._refresh_graph()

    def _code_gen(self):
        snapshot = self._require_current_snapshot_for_action("代码生成")
        if snapshot is None:
            return None
        dialog = DialogCodeGen(
            self,
            self.generation_service.list_templates(),
            state_manager=self.state_manager,
            model=snapshot.model,
        )
        dialog.generate_requested.connect(
            lambda request: self._start_generation(request, dialog)
        )
        dialog.cancel_requested.connect(
            lambda: self._cancel_workspace_kind("code-generation")
        )
        dialog.exec_()
        return dialog

    def _show_unified_export(self):
        if self._require_current_snapshot_for_action("统一导出") is None:
            return None
        dialog = DialogExport(
            self,
            dynamic_available=self.dynamic_validation_panel.report_json() is not None,
        )
        dialog.export_requested.connect(
            lambda request: self._start_unified_export(request, dialog)
        )
        dialog.cancel_requested.connect(
            lambda: self._cancel_workspace_kind("unified-export")
        )
        dialog.exec_()
        return dialog

    def _require_current_snapshot_for_action(self, action_name):
        if self.document_session is None:
            return None
        try:
            return self.document_service.require_current_valid_snapshot(
                self.document_session
            )
        except Exception as error:
            QtWidgets.QMessageBox.warning(
                self,
                "{}不可用".format(action_name),
                "当前源码没有可用的有效快照：\n{}".format(error),
                QtWidgets.QMessageBox.Ok,
            )
            return None

    def _task_stamp_current(self, stamp):
        if stamp.channel not in {
            "model-check",
            "document-validate",
            "ordinary-simulation",
            "dynamic-validation",
            "graph-render",
            "code-generation",
            "unified-export",
        }:
            return True
        session = self.document_session
        if (
            session is None
            or session.session_id != stamp.session_id
            or session.source_revision != stamp.source_revision
        ):
            return False
        if stamp.channel == "document-validate":
            snapshot = session.last_valid_snapshot
            return bool(
                stamp.dependency_fingerprint is None
                or (
                    snapshot is not None
                    and snapshot.dependency_fingerprint
                    == stamp.dependency_fingerprint
                )
            )
        snapshot = session.current_valid_snapshot or session.last_valid_snapshot
        return bool(
            snapshot is not None
            and snapshot.dependency_fingerprint == stamp.dependency_fingerprint
        )

    def _on_tree_item_selection_changed(self):
        """
        当树形控件中的选择发生变化时，更新转移信息和生命周期信息表格
        """
        try:
            if self._setting_projection:
                return
            if self.state_manager is None:
                return

            current_state = self._get_pro_state()

            if current_state is None:
                # 如果没有选中项，清空表格
                self._clear_tables()
                return
                
            # 更新转移信息表格
            self._update_transition_table(current_state.transitions)
            # 更新生命周期信息表格
            self._update_lifecycle_table(current_state.lifecycle)
            self._update_event_table(current_state)
            self._update_property_inspector(current_state)
            self.graph_panel.set_selection(current_state.get_full_path())
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"更新状态信息时发生错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _selected_state_path(self):
        item = self.tree_all_state.currentItem()
        if item is None:
            return None
        state = item.data(0, Qt.UserRole)
        get_full_path = getattr(state, "get_full_path", None)
        if not callable(get_full_path):
            return None
        return get_full_path()

    def _restore_state_tree_selection(self, full_path):
        matching_item = None
        if full_path:
            pending = [
                self.tree_all_state.topLevelItem(index)
                for index in range(self.tree_all_state.topLevelItemCount())
            ]
            while pending:
                item = pending.pop()
                state = item.data(0, Qt.UserRole)
                get_full_path = getattr(state, "get_full_path", None)
                if callable(get_full_path) and get_full_path() == full_path:
                    matching_item = item
                    break
                pending.extend(
                    item.child(index) for index in range(item.childCount())
                )

        if matching_item is None and self.tree_all_state.topLevelItemCount():
            matching_item = self.tree_all_state.topLevelItem(0)

        signals_were_blocked = self.tree_all_state.blockSignals(True)
        try:
            self.tree_all_state.setCurrentItem(matching_item)
            if matching_item is not None:
                self.tree_all_state.scrollToItem(matching_item)
        finally:
            self.tree_all_state.blockSignals(signals_were_blocked)
        self._on_tree_item_selection_changed()
        return matching_item is not None

    def _clear_tables(self):
        """
        清空转移信息和生命周期信息表格
        """
        # 清空转移表格
        if hasattr(self, 'table_transition'):
            self.table_transition.setRowCount(0)
        
        # 清空生命周期表格
        if hasattr(self, 'table_lifecycle'):
            self.table_lifecycle.setRowCount(0)
        if hasattr(self, "event_table"):
            self._event_projections = ()
            self.event_table.setRowCount(0)
            self._update_event_actions()
        if hasattr(self, "property_path_label"):
            self.property_path_label.setText("未选择模型对象")
            self.property_source_label.clear()

    def _update_property_inspector(self, state):
        self.property_path_label.setText("状态：{}".format(state.get_full_path()))
        source_ref = getattr(state, "source_ref", None)
        if source_ref is None:
            self.property_source_label.setText("来源：当前内存模型")
            return
        ownership = "可编辑" if source_ref.editable else "只读"
        self.property_source_label.setText(
            "来源：{}\n所有权：{}".format(
                self.task_center.redactor.redact_text(source_ref.source_uri),
                ownership,
            )
        )

    @property
    def _selected_event(self):
        row = self.event_table.currentRow()
        if row < 0 or row >= len(self._event_projections):
            return None
        return self._event_projections[row]

    def _update_event_table(self, state):
        selected_id = getattr(self._selected_event, "projection_id", None)
        if self.document_session is None or state is None:
            self._event_projections = ()
        else:
            try:
                owner_path = tuple(state.get_full_path().split("."))
                self._event_projections = self.event_service.list_events(
                    self.document_session, owner_path
                )
            except EventProjectionError:
                self._event_projections = ()
        self.event_table.setRowCount(len(self._event_projections))
        selected_row = -1
        for row, event in enumerate(self._event_projections):
            values = (
                ".".join(event.owner_path),
                event.name,
                event.display_name or "",
                event.scope,
                str(len(event.use_refs)),
                self.task_center.redactor.redact_text(event.source_uri),
                "可编辑" if event.editable else "只读",
            )
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                item.setToolTip(value)
                item.setData(Qt.UserRole, event.projection_id)
                self.event_table.setItem(row, column, item)
            if event.projection_id == selected_id:
                selected_row = row
        if selected_row < 0 and self._event_projections:
            selected_row = 0
        if selected_row >= 0:
            self.event_table.setCurrentCell(selected_row, 0)
            self.event_table.selectRow(selected_row)
        self._update_event_actions()

    def _event_owner_editable(self):
        state = self._get_pro_state()
        source_ref = getattr(state, "source_ref", None) if state else None
        return bool(
            self.document_session is not None
            and self.document_session.current_valid_snapshot is not None
            and source_ref is not None
            and source_ref.editable
        )

    def _update_event_actions(self):
        event = self._selected_event
        self._update_event_references(event)
        self.event_add_button.setEnabled(self._event_owner_editable())
        self.event_edit_button.setEnabled(bool(event and event.editable))
        self.event_delete_button.setEnabled(bool(event and event.editable))
        self.event_open_source_button.setEnabled(event is not None)

    def _update_event_references(self, event):
        references = () if event is None else event.use_refs
        self.event_reference_table.setRowCount(len(references))
        if self.document_session is None:
            return
        index = self.document_session.require_current_valid_snapshot().source_index
        for row, source_ref in enumerate(references):
            declaration_ref = self.event_service.source_ref_for_declaration(
                index, source_ref.declaration_ref
            )
            declaration = index.text_for_ref(declaration_ref).strip()
            location = "{}:{}".format(
                source_ref.span.start_line, source_ref.span.start_column
            )
            values = (
                "import 映射"
                if source_ref.kind in {"import_event_source", "import_event_target"}
                else "迁移",
                declaration,
                location,
                self.task_center.redactor.redact_text(source_ref.source_uri),
            )
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                item.setToolTip(value)
                item.setData(Qt.UserRole, declaration_ref)
                self.event_reference_table.setItem(row, column, item)

    def _open_event_reference_source(self, item=None):
        if item is None:
            item = self.event_reference_table.currentItem()
        source_ref = item.data(Qt.UserRole) if item is not None else None
        return self._open_source_ref(source_ref)

    def _prompt_event(self, title, name="", display_name=""):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setObjectName("event_editor_dialog")
        layout = QtWidgets.QFormLayout(dialog)
        name_edit = QtWidgets.QLineEdit(name, dialog)
        name_edit.setObjectName("event_name_edit")
        display_edit = QtWidgets.QLineEdit(display_name or "", dialog)
        display_edit.setObjectName("event_display_name_edit")
        layout.addRow("名称", name_edit)
        layout.addRow("显示名", display_edit)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return None
        return name_edit.text().strip(), display_edit.text()

    def _add_event(self):
        state = self._get_pro_state()
        if state is None or not self._event_owner_editable():
            return False
        values = self._prompt_event("新增事件")
        if values is None:
            return False
        try:
            edits = self.event_service.add_edits(
                self.document_session,
                tuple(state.get_full_path().split(".")),
                values[0],
                values[1] or None,
            )
        except EventProjectionError as error:
            QtWidgets.QMessageBox.warning(self, "事件未添加", str(error))
            return False
        return self._commit_form_edits(edits, preview_title="新增事件")

    def _edit_event(self):
        event = self._selected_event
        if event is None:
            return False
        if not event.editable:
            reply = QtWidgets.QMessageBox.question(
                self,
                "只读事件",
                "该事件来自 import 或生成投影，不能在当前文件中编辑。\n"
                "是否打开声明所在的物理源码？",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.Yes,
            )
            if reply == QtWidgets.QMessageBox.Yes:
                return self._open_source_ref(event.source_ref)
            return False
        values = self._prompt_event(
            "编辑事件", event.name, event.display_name or ""
        )
        if values is None:
            return False
        try:
            edits = self.event_service.edit_edits(
                self.document_session,
                event,
                values[0],
                values[1] or None,
            )
        except (EventReadOnlyError, EventConflictError) as error:
            self._offer_event_conflict_source("事件未修改", error)
            return False
        except EventProjectionError as error:
            QtWidgets.QMessageBox.warning(self, "事件未修改", str(error))
            return False
        if not edits:
            return True
        return self._commit_form_edits(
            edits,
            preview_title="编辑事件",
            declaration_ref=event.source_ref,
        )

    def _delete_event(self):
        event = self._selected_event
        if event is None:
            return False
        if not event.editable:
            error = EventReadOnlyError(
                "该事件声明来自只读的 import 来源",
                source_ref=event.source_ref,
            )
            self._offer_event_conflict_source("事件未删除", error)
            return False
        mapping_refs = tuple(
            ref
            for ref in event.use_refs
            if ref.kind in {"import_event_source", "import_event_target"}
        )
        if mapping_refs:
            error = EventConflictError(
                "事件“{}”被 import 事件映射引用，不能级联删除该 import。".format(
                    event.name
                ),
                source_ref=mapping_refs[0],
                reference_kind=mapping_refs[0].kind,
            )
            self._offer_event_conflict_source("事件未删除", error)
            return False
        delete_references = bool(event.use_refs)
        if delete_references:
            prompt = (
                "事件“{}”被 {} 条迁移引用，不能只删除声明。\n"
                "是否同时删除这些引用迁移？"
            ).format(event.name, len(event.use_refs))
        else:
            prompt = "删除事件声明“{}”？".format(event.name)
        reply = QtWidgets.QMessageBox.question(
            self,
            "删除事件",
            prompt,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return False
        try:
            edits = self.event_service.delete_edits(
                self.document_session,
                event,
                delete_references=delete_references,
            )
        except (EventReadOnlyError, EventConflictError) as error:
            self._offer_event_conflict_source("事件未删除", error)
            return False
        except EventProjectionError as error:
            QtWidgets.QMessageBox.warning(self, "事件未删除", str(error))
            return False
        return self._commit_form_edits(
            edits,
            preview_title="删除事件",
            declaration_ref=event.source_ref,
        )

    def _open_event_source(self):
        event = self._selected_event
        return self._open_source_ref(event.source_ref if event is not None else None)

    def _offer_event_conflict_source(self, title, error):
        source_ref = getattr(error, "source_ref", None)
        if source_ref is None:
            QtWidgets.QMessageBox.warning(self, title, str(error))
            return False
        reference_kind = getattr(error, "reference_kind", None)
        reference_label = (
            "import 事件映射"
            if reference_kind in {"import_event_source", "import_event_target"}
            else "只读声明或迁移引用"
        )
        reply = QtWidgets.QMessageBox.question(
            self,
            title,
            "{}\n\n冲突来源：{}。是否打开来源？".format(
                error, reference_label
            ),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return False
        return self._open_source_ref(source_ref)

    def _open_source_ref(self, source_ref):
        if source_ref is None or self.document_session is None:
            return False
        index = self.document_session.require_current_valid_snapshot().source_index
        document = index.document_for_ref(source_ref)
        if source_ref.file_id == index.root_document_id:
            editor = self.source_editor
            self.workspace_tabs.setCurrentWidget(self.source_workspace)
        else:
            editor = self._imported_source_editor(document)
        cursor = editor.textCursor()
        cursor.setPosition(
            document.python_to_qt_offset(source_ref.span.start_offset)
        )
        cursor.setPosition(
            document.python_to_qt_offset(source_ref.span.end_offset),
            QtGui.QTextCursor.KeepAnchor,
        )
        editor.setTextCursor(cursor)
        editor.setFocus()
        return True

    def _imported_source_editor(self, document):
        for index in range(self.workspace_tabs.count()):
            page = self.workspace_tabs.widget(index)
            if page.objectName() == "imported_source_workspace":
                page.setProperty("source_uri", document.uri)
                editor = page.findChild(QtWidgets.QPlainTextEdit)
                editor.setPlainText(document.text)
                self.workspace_tabs.setTabText(
                    index, os.path.basename(document.path)
                )
                self.workspace_tabs.setCurrentIndex(index)
                return editor
        page = QtWidgets.QWidget(self.workspace_tabs)
        page.setObjectName("imported_source_workspace")
        page.setProperty("source_uri", document.uri)
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        editor = QtWidgets.QPlainTextEdit(page)
        editor.setObjectName("imported_source_editor")
        editor.setReadOnly(True)
        editor.setPlainText(document.text)
        layout.addWidget(editor)
        tab_index = self.workspace_tabs.addTab(
            page, os.path.basename(document.path)
        )
        self.workspace_tabs.setCurrentIndex(tab_index)
        return editor

    def _update_transition_table(self, transitions):
        """
        更新转移信息表格
        transitions: List[Dict[str, str]] - 转移信息列表
        """
        if not hasattr(self, 'table_transition'):
            return
            
        # 设置表格列数和标题
        self.table_transition.setColumnCount(4)
        self.table_transition.setHorizontalHeaderLabels(["源状态", "目标状态", "事件", "条件"])
        
        # 设置行数
        self.table_transition.setRowCount(len(transitions))
        
        # 填充数据
        for row, transition in enumerate(transitions):
            # 源状态
            source_state_name = transition.get("source", "")
            source_item = QtWidgets.QTableWidgetItem(source_state_name)
            source_item.setTextAlignment(QtCore.Qt.AlignCenter)
            source_item.setToolTip(source_state_name)  # 添加工具提示
            self.table_transition.setItem(row, 0, source_item)
            
            # 目标状态
            target_state_name = transition.get("target", "")
            target_item = QtWidgets.QTableWidgetItem(target_state_name)
            target_item.setTextAlignment(QtCore.Qt.AlignCenter)
            target_item.setToolTip(target_state_name)  # 添加工具提示
            self.table_transition.setItem(row, 1, target_item)
            
            # 事件
            event_text = transition.get("event", "")
            event_item = QtWidgets.QTableWidgetItem(event_text)
            event_item.setTextAlignment(QtCore.Qt.AlignCenter)
            event_item.setToolTip(event_text)  # 添加工具提示
            self.table_transition.setItem(row, 2, event_item)
            
            # 条件
            condition_text = transition.get("condition", "")
            condition_item = QtWidgets.QTableWidgetItem(condition_text)
            condition_item.setTextAlignment(QtCore.Qt.AlignCenter)
            
            # 为条件项添加详细的工具提示，包括操作信息
            action_text = transition.get("action", "")
            if action_text:
                tooltip_text = f"条件: {condition_text}\n\n操作:\n{action_text}"
            else:
                tooltip_text = condition_text
            condition_item.setToolTip(tooltip_text)
            
            self.table_transition.setItem(row, 3, condition_item)
        
        # 列宽已通过拉伸模式自动调整，无需手动调整

    def _update_lifecycle_table(self, lifecycle):
        """
        更新生命周期信息表格
        lifecycle: List[Dict[str, str]] - 生命周期信息列表
        """
        if not hasattr(self, 'table_lifecycle'):
            return
            
        # 设置表格列数和标题
        self.table_lifecycle.setColumnCount(3)
        self.table_lifecycle.setHorizontalHeaderLabels(["类型", "名称", "是否抽象"])
        
        # 设置行数
        self.table_lifecycle.setRowCount(len(lifecycle))
        
        # 填充数据
        for row, lifecycle_item in enumerate(lifecycle):
            # 类型
            type_text = lifecycle_item.get("type", "")
            type_item = QtWidgets.QTableWidgetItem(type_text)
            type_item.setTextAlignment(QtCore.Qt.AlignCenter)
            type_item.setToolTip(type_text)  # 添加工具提示
            self.table_lifecycle.setItem(row, 0, type_item)
            
            # 名称 - 如果没有名称，显示"无"
            name_value = lifecycle_item.get("name", "")
            if not name_value or name_value.strip() == "":
                name_value = "无"
            name_item = QtWidgets.QTableWidgetItem(name_value)
            name_item.setTextAlignment(QtCore.Qt.AlignCenter)
            name_item.setToolTip(name_value)  # 添加工具提示
            self.table_lifecycle.setItem(row, 1, name_item)
            
            # 是否抽象 - 将布尔值转换为中文显示
            is_abstract_value = lifecycle_item.get("is_abstract", False)
            is_abstract_text = "是" if is_abstract_value else "否"
            is_abstract_item = QtWidgets.QTableWidgetItem(is_abstract_text)
            is_abstract_item.setTextAlignment(QtCore.Qt.AlignCenter)
            is_abstract_item.setToolTip(is_abstract_text)  # 添加工具提示
            
            # 构建详细的工具提示信息
            tooltip_parts = [is_abstract_text]
            
            # 添加操作信息（如果存在）
            action = lifecycle_item.get("action", "")
            if action and action.strip():
                tooltip_parts.append(f"操作:\n{action}")
            
            # 添加注释信息（如果存在）
            comment = lifecycle_item.get("comment", "")
            if comment and comment.strip():
                tooltip_parts.append(f"注释:\n{comment}")
            
            # 设置工具提示
            if len(tooltip_parts) > 1:
                tooltip_text = "\n\n".join(tooltip_parts)
                is_abstract_item.setToolTip(tooltip_text)
            
            self.table_lifecycle.setItem(row, 2, is_abstract_item)
        
        # 列宽已通过拉伸模式自动调整，无需手动调整

    def _get_state_by_name(self, state_name):
        """
        根据状态名称获取状态对象
        """
        if not self.state_manager or not state_name:
            return None
        return self.state_manager.get_state(state_name)

    def _on_var_def_text_changed(self):
        """
        当变量定义文本框内容变化时，保存到StateManager
        """
        try:
            if self._setting_projection:
                return
            if self.document_session is not None:
                self._variable_edit_timer.start()
                return
            if self.state_manager is None:
                return
                
            # 获取文本框内容并保存到StateManager
            var_def_text = self.edit_var_def.toPlainText()
            self.state_manager.variable_definitions = var_def_text
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"保存变量定义时发生错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _commit_variable_editor(self):
        self._variable_edit_timer.stop()
        session = self.document_session
        if session is None or session.current_valid_snapshot is None:
            return False
        desired = self.edit_var_def.toPlainText().strip()
        index = session.current_valid_snapshot.source_index
        refs = tuple(
            ref
            for ref in index.refs(
                kind="variable", document_id=index.root_document_id
            )
            if ref.editable
        )
        edits = []
        if refs:
            edits.append(
                TextEdit.for_ref(
                    session.source_revision,
                    refs[0],
                    desired,
                    intent="edit variables",
                )
            )
            edits.extend(
                TextEdit.for_ref(
                    session.source_revision,
                    ref,
                    ref.deletion_replacement,
                    intent="remove variable",
                )
                for ref in refs[1:]
            )
        elif desired:
            anchor = index.insertion_anchor("variable")
            edits.append(
                TextEdit.for_anchor(
                    session.source_revision,
                    anchor,
                    desired + "\n",
                    intent="add variables",
                )
            )
        else:
            return True
        if self._commit_form_edits(tuple(edits)):
            return True
        self._set_active_document_session(session)
        return False

    def _get_pro_state(self) -> Optional[State]:
        # 获得当前Tree中选择的item
        selected_state_item = self.tree_all_state.currentItem()
        # 若没有选中状态，则返回None
        if not selected_state_item:
            return None
        pro_state = selected_state_item.data(0, Qt.UserRole)
        return pro_state

    def _show_lifecycle_context_menu(self, position: QPoint):
        """显示生命周期表格的右键菜单"""
        try:
            # 检查是否有选中的状态
            current_state = self._get_pro_state()
            if current_state is None:
                return
            
            # 检查点击位置是否有有效的行
            item = self.table_lifecycle.itemAt(position)
            if item is None:
                return
            
            row = item.row()
            if row < 0 or row >= len(current_state.lifecycle):
                return
            
            # 创建右键菜单
            menu = QtWidgets.QMenu(self)
            edit_action = QtWidgets.QAction("修改生命周期", self)
            delete_action = QtWidgets.QAction("删除生命周期", self)
            
            # 连接菜单项信号
            edit_action.triggered.connect(lambda: self._edit_lifecycle(current_state, row))
            delete_action.triggered.connect(lambda: self._delete_lifecycle(current_state, row))
            
            menu.addAction(edit_action)
            menu.addAction(delete_action)
            
            # 显示菜单
            menu.exec_(self.table_lifecycle.viewport().mapToGlobal(position))
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"显示生命周期菜单时发生错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _edit_lifecycle(self, current_state: State, row: int):
        """编辑生命周期操作"""
        try:
            if row < 0 or row >= len(current_state.lifecycle):
                QtWidgets.QMessageBox.warning(self, "错误", "无效的生命周期操作！")
                return
            
            # 获取要编辑的生命周期数据
            lifecycle_data = current_state.lifecycle[row]
            
            # 显示编辑对话框
            dialog = DialogAddLifecycle(
                parent=self, 
                state_manager=self.state_manager, 
                current_state=current_state,
                is_edit=True,
                lifecycle_data=lifecycle_data,
                lifecycle_index=row,
                mutate_model=self.document_session is None,
            )
            
            if dialog.exec_() == QtWidgets.QDialog.Accepted:
                if self.document_session is not None:
                    self._replace_projected_declaration(
                        lifecycle_data,
                        format_lifecycle_item(dialog.get_lifecycle_data()),
                    )
                else:
                    self._update_lifecycle_table(current_state.lifecycle)
                
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"编辑生命周期操作时发生错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _delete_lifecycle(self, current_state: State, row: int):
        """删除生命周期操作"""
        try:
            if row < 0 or row >= len(current_state.lifecycle):
                QtWidgets.QMessageBox.warning(self, "错误", "无效的生命周期操作！")
                return
            
            # 获取要删除的生命周期数据
            lifecycle_data = current_state.lifecycle[row]
            lifecycle_type = lifecycle_data.get("type", "")
            lifecycle_name = lifecycle_data.get("name", "")
            
            # 构建显示名称
            display_name = f"{lifecycle_type}"
            if lifecycle_name:
                display_name += f" ({lifecycle_name})"
            
            # 确认删除
            reply = QtWidgets.QMessageBox.question(
                self, 
                "删除确认", 
                f"确定要删除生命周期操作 '{display_name}' 吗？",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            )
            
            if reply == QtWidgets.QMessageBox.Yes:
                if self.document_session is not None:
                    self._delete_projected_declaration(lifecycle_data)
                    return
                del current_state.lifecycle[row]
                
                # 刷新生命周期表格显示
                self._update_lifecycle_table(current_state.lifecycle)
                
                QtWidgets.QMessageBox.information(self, "成功", "生命周期操作删除成功！")
                
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"删除生命周期操作时发生错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _show_transition_context_menu(self, position: QPoint):
        """显示转移表格的右键菜单"""
        try:
            # 检查是否有选中的状态
            current_state = self._get_pro_state()
            if current_state is None:
                return
            
            # 检查点击位置是否有有效的行
            item = self.table_transition.itemAt(position)
            if item is None:
                return
            
            row = item.row()
            if row < 0 or row >= len(current_state.transitions):
                return
            
            # 创建右键菜单
            menu = QtWidgets.QMenu(self)
            edit_action = QtWidgets.QAction("修改转移", self)
            delete_action = QtWidgets.QAction("删除转移", self)
            
            # 连接菜单项信号
            edit_action.triggered.connect(lambda: self._edit_transition(current_state, row))
            delete_action.triggered.connect(lambda: self._delete_transition(current_state, row))
            
            menu.addAction(edit_action)
            menu.addAction(delete_action)
            
            # 显示菜单
            menu.exec_(self.table_transition.viewport().mapToGlobal(position))
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"显示转移菜单时发生错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _edit_transition(self, current_state: State, row: int):
        """编辑转移"""
        try:
            if row < 0 or row >= len(current_state.transitions):
                QtWidgets.QMessageBox.warning(self, "错误", "无效的转移！")
                return
            
            # 获取要编辑的转移数据
            transition_data = current_state.transitions[row]
            
            # 显示编辑对话框
            dialog = DialogAddTransition(
                parent=self, 
                state_manager=self.state_manager, 
                current_state=current_state,
                is_edit=True,
                transition_data=transition_data,
                transition_index=row,
                mutate_model=self.document_session is None,
            )
            
            if dialog.exec_() == QtWidgets.QDialog.Accepted:
                if self.document_session is not None:
                    declaration = format_transition_item(
                        dialog.get_transition_data()
                    )
                    if declaration and not declaration.rstrip().endswith("}"):
                        declaration += ";"
                    self._replace_projected_declaration(
                        transition_data, declaration
                    )
                else:
                    self._update_transition_table(current_state.transitions)
                
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"编辑转移时发生错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _delete_transition(self, current_state: State, row: int):
        """删除转移"""
        try:
            if row < 0 or row >= len(current_state.transitions):
                QtWidgets.QMessageBox.warning(self, "错误", "无效的转移！")
                return
            
            # 获取要删除的转移数据
            transition_data = current_state.transitions[row]
            source_state = transition_data.get("source", "")
            target_state = transition_data.get("target", "")
            event = transition_data.get("event", "")
            
            # 构建显示名称
            display_name = f"{source_state} → {target_state}"
            if event:
                display_name += f" ({event})"
            
            # 确认删除
            reply = QtWidgets.QMessageBox.question(
                self, 
                "删除确认", 
                f"确定要删除转移 '{display_name}' 吗？",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            )
            
            if reply == QtWidgets.QMessageBox.Yes:
                if self.document_session is not None:
                    self._delete_projected_declaration(transition_data)
                    return
                del current_state.transitions[row]
                
                # 刷新转移表格显示
                self._update_transition_table(current_state.transitions)
                
                QtWidgets.QMessageBox.information(self, "成功", "转移删除成功！")
                
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"删除转移时发生错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _insert_state_declaration(self, state, kind, declaration):
        snapshot = self._require_current_snapshot_for_action("编辑")
        if snapshot is None:
            return False
        owner_path = tuple(state.get_full_path().split("."))
        try:
            anchor = snapshot.source_index.insertion_anchor(
                kind, owner_path=owner_path
            )
        except Exception as error:
            QtWidgets.QMessageBox.warning(
                self,
                "只读来源",
                "该对象不能在当前文件中编辑：\n{}".format(error),
            )
            return False
        indent = "    " * len(owner_path)
        closing_indent = "    " * max(0, len(owner_path) - 1)
        block = "\n".join(
            indent + line if line else line
            for line in declaration.splitlines()
        )
        before = self.document_session.source_text[:anchor.offset]
        prefix = "" if before.endswith("\n" + closing_indent) else "\n"
        replacement = prefix + block + "\n" + closing_indent
        edit = TextEdit.for_anchor(
            self.document_session.source_revision,
            anchor,
            replacement,
            intent="insert {}".format(kind),
        )
        return self._commit_form_edits((edit,))

    def _rename_projected_state(self, state, new_name):
        source_ref = getattr(state, "source_ref", None)
        if source_ref is None or not source_ref.editable:
            QtWidgets.QMessageBox.warning(
                self, "只读来源", "该状态来自 import 或生成投影，不能重命名。"
            )
            return False
        snapshot = self.document_session.current_valid_snapshot
        declaration = snapshot.source_index.text_for_ref(source_ref)
        if "{" in declaration:
            QtWidgets.QMessageBox.warning(
                self,
                "暂不支持",
                "复合状态请在源码编辑器中重命名，以避免重叠引用。",
            )
            return False
        old_name = state.name
        state_text = re.sub(
            r"(\bstate\s+){}\b".format(re.escape(old_name)),
            r"\g<1>{}".format(new_name),
            declaration,
            count=1,
        )
        edits = [
            TextEdit.for_ref(
                self.document_session.source_revision,
                source_ref,
                state_text,
                intent="rename state",
            )
        ]
        token = re.compile(
            r"(?<![A-Za-z0-9_]){}(?![A-Za-z0-9_])".format(
                re.escape(old_name)
            )
        )
        for ref in snapshot.source_index.refs(
            document_id=snapshot.source_index.root_document_id
        ):
            if (
                ref.editable
                and "transition" in ref.kind
                and not (
                    source_ref.span.start_offset
                    <= ref.span.start_offset
                    < source_ref.span.end_offset
                )
            ):
                text = snapshot.source_index.text_for_ref(ref)
                replacement = token.sub(new_name, text)
                if replacement != text:
                    edits.append(
                        TextEdit.for_ref(
                            self.document_session.source_revision,
                            ref,
                            replacement,
                            intent="rename state reference",
                        )
                    )
        return self._commit_form_edits(tuple(edits))

    def _delete_projected_state(self, state):
        source_ref = getattr(state, "source_ref", None)
        if source_ref is None or not source_ref.editable:
            QtWidgets.QMessageBox.warning(
                self, "只读来源", "该状态来自 import 或生成投影，不能删除。"
            )
            return False
        snapshot = self.document_session.current_valid_snapshot
        token = re.compile(
            r"(?<![A-Za-z0-9_]){}(?![A-Za-z0-9_])".format(
                re.escape(state.name)
            )
        )
        edits = [
            TextEdit.for_ref(
                self.document_session.source_revision,
                source_ref,
                source_ref.deletion_replacement,
                intent="delete state",
            )
        ]
        for ref in snapshot.source_index.refs(
            document_id=snapshot.source_index.root_document_id
        ):
            if (
                ref.editable
                and "transition" in ref.kind
                and not (
                    source_ref.span.start_offset
                    <= ref.span.start_offset
                    < source_ref.span.end_offset
                )
            ):
                text = snapshot.source_index.text_for_ref(ref)
                if token.search(text):
                    edits.append(
                        TextEdit.for_ref(
                            self.document_session.source_revision,
                            ref,
                            ref.deletion_replacement,
                            intent="delete state transition",
                        )
                    )
        return self._commit_form_edits(tuple(edits))

    def _replace_projected_declaration(self, data, declaration):
        source_ref = data.get("source_ref")
        if source_ref is None or not source_ref.editable:
            QtWidgets.QMessageBox.warning(
                self, "只读来源", "该声明来自 import 或生成投影，不能直接编辑。"
            )
            return False
        edit = TextEdit.for_ref(
            self.document_session.source_revision,
            source_ref,
            declaration,
            intent="replace {}".format(source_ref.kind),
        )
        return self._commit_form_edits((edit,))

    def _delete_projected_declaration(self, data):
        source_ref = data.get("source_ref")
        if source_ref is None or not source_ref.editable:
            QtWidgets.QMessageBox.warning(
                self, "只读来源", "该声明来自 import 或生成投影，不能直接删除。"
            )
            return False
        edit = TextEdit.for_ref(
            self.document_session.source_revision,
            source_ref,
            source_ref.deletion_replacement,
            intent="delete {}".format(source_ref.kind),
        )
        return self._commit_form_edits((edit,))

    def _confirm_event_transaction(
        self, transaction, title, declaration_ref=None
    ):
        dialog = QtWidgets.QDialog(self)
        dialog.setObjectName("event_transaction_preview_dialog")
        dialog.setWindowTitle("{}预览".format(title))
        dialog.resize(900, 560)
        layout = QtWidgets.QVBoxLayout(dialog)

        if declaration_ref is not None:
            location = "声明位置：{}:{}  {}".format(
                declaration_ref.span.start_line,
                declaration_ref.span.start_column,
                self.task_center.redactor.redact_text(
                    declaration_ref.source_uri
                ),
            )
        else:
            location = "声明位置：将在当前状态中新增"
        location_label = QtWidgets.QLabel(location, dialog)
        location_label.setObjectName("event_transaction_location")
        location_label.setTextInteractionFlags(Qt.TextSelectableByKeyboard | Qt.TextSelectableByMouse)
        layout.addWidget(location_label)

        affected = QtWidgets.QLabel(
            "本次事务包含 {} 项源码修改；确认后将作为一个命令提交，可整体撤销。".format(
                len(transaction.forward_edits)
            ),
            dialog,
        )
        affected.setObjectName("event_transaction_summary")
        layout.addWidget(affected)

        panes = QtWidgets.QSplitter(Qt.Horizontal, dialog)
        for heading, text, object_name in (
            ("修改前", transaction.before_text, "event_transaction_before"),
            ("修改后", transaction.after_text, "event_transaction_after"),
        ):
            page = QtWidgets.QWidget(panes)
            page_layout = QtWidgets.QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.addWidget(QtWidgets.QLabel(heading, page))
            editor = QtWidgets.QPlainTextEdit(page)
            editor.setObjectName(object_name)
            editor.setReadOnly(True)
            editor.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
            editor.setPlainText(text)
            page_layout.addWidget(editor)
            panes.addWidget(page)
        layout.addWidget(panes, 1)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=dialog,
        )
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("确认提交")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        return dialog.exec_() == QtWidgets.QDialog.Accepted

    def _commit_form_edits(
        self, edits, preview_title=None, declaration_ref=None
    ):
        try:
            transaction = self.document_service.preview_edits(
                self.document_session, edits
            )
            if preview_title is not None and not self._confirm_event_transaction(
                transaction, preview_title, declaration_ref
            ):
                return False
            updated = self.command_stack.execute(
                self.document_session, transaction
            )
        except DocumentValidationError as error:
            detail = "\n".join(
                str(item) for item in error.candidate.current_diagnostics
            )
            QtWidgets.QMessageBox.warning(
                self,
                "编辑未应用",
                "候选源码未通过完整校验：\n{}".format(detail),
            )
            return False
        except Exception as error:
            QtWidgets.QMessageBox.warning(self, "编辑未应用", str(error))
            return False
        self.task_runner.supersede(
            "model-check", self.document_session.session_id
        )
        self._set_active_document_session(updated)
        return True

    def _undo_document(self):
        if self.document_session is None:
            return False
        if (
            self.source_editor.hasFocus()
            and self.source_editor.document().isUndoAvailable()
        ):
            self.source_editor.undo()
            return True
        try:
            self._variable_edit_timer.stop()
            restored = self.command_stack.undo(self.document_session)
        except CommandStateError as error:
            QtWidgets.QMessageBox.warning(self, "无法撤销", str(error))
            return False
        self.task_runner.invalidate(
            "document-validate", self.document_session.session_id
        )
        self.task_runner.supersede(
            "model-check", self.document_session.session_id
        )
        self._set_active_document_session(restored)
        return True

    def _redo_document(self):
        if self.document_session is None:
            return False
        if (
            self.source_editor.hasFocus()
            and self.source_editor.document().isRedoAvailable()
        ):
            self.source_editor.redo()
            return True
        try:
            self._variable_edit_timer.stop()
            restored = self.command_stack.redo(self.document_session)
        except CommandStateError as error:
            QtWidgets.QMessageBox.warning(self, "无法重做", str(error))
            return False
        self.task_runner.invalidate(
            "document-validate", self.document_session.session_id
        )
        self.task_runner.supersede(
            "model-check", self.document_session.session_id
        )
        self._set_active_document_session(restored)
        return True

    def _submit_product_task(self, kind, action, work, summary, finished_slot):
        session = self.document_session
        if session is None:
            return None
        snapshot = self._require_current_snapshot_for_action(summary)
        if snapshot is None:
            return None
        def stamp_state():
            current = self.document_session
            current_snapshot = (
                current.current_valid_snapshot if current is not None else None
            )
            valid = bool(
                current is not None
                and current.session_id == session.session_id
                and current.source_revision == session.source_revision
                and current_snapshot is not None
                and current_snapshot.dependency_fingerprint
                == snapshot.dependency_fingerprint
            )
            detail = (
                "expected session={}/revision={}/dependency={}, "
                "current session={}/revision={}/dependency={}".format(
                    session.session_id,
                    session.source_revision,
                    snapshot.dependency_fingerprint,
                    getattr(current, "session_id", None),
                    getattr(current, "source_revision", None),
                    getattr(current_snapshot, "dependency_fingerprint", None),
                )
            )
            return valid, detail

        def guarded_work(token):
            guarded = _StampedTaskToken(
                token,
                stamp_state,
            )
            return work(guarded)

        handle = self.task_runner.submit(
            kind,
            session.source_revision,
            guarded_work,
            session_id=session.session_id,
            channel=kind,
            dependency_fingerprint=snapshot.dependency_fingerprint,
        )
        now = time.time()
        self.task_center.add(
            TaskRecord(
                task_id=handle.stamp.task_id,
                kind=kind,
                session_id=session.session_id,
                source_revision=session.source_revision,
                dependency_fingerprints=dict(snapshot.dependency_manifest),
                created_at=now,
                started_at=now,
                status=HistoryTaskStatus.RUNNING,
                summary=summary,
                messages=(),
                artifacts=(),
                retry_descriptor=None,
                exception_chain=(),
                boundary=TaskBoundary.EXPLICIT,
            )
        )
        self._task_handles[handle.stamp.task_id] = handle
        self._workspace_task_actions[handle.stamp.task_id] = action
        handle.finished.connect(finished_slot)
        self._refresh_task_result_dock(show=True)
        return handle

    def _refresh_graph(self):
        session = self.document_session
        if session is None or session.current_valid_snapshot is None:
            return None
        snapshot = session.current_valid_snapshot

        def work(token):
            with tempfile.TemporaryDirectory(prefix="fcstm-graph-preview-") as td:
                target = Path(td) / "graph.png"
                self.export_service.export(
                    "png",
                    str(target),
                    session.source_text,
                    snapshot.model,
                    overwrite=True,
                    cancel_token=token,
                )
                token.raise_if_cancelled()
                return target.read_bytes()

        self.graph_panel.set_busy(True, "正在渲染状态图")
        return self._submit_product_task(
            "graph-render",
            {"mode": "preview", "revision": session.source_revision},
            work,
            "正在渲染状态图",
            self._finish_graph_task,
        )

    def _export_graph_kind(self, kind):
        suffix = "puml" if kind == "plantuml" else kind
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "导出状态图",
            "statechart." + suffix,
            "所有文件 (*)",
        )
        if not path:
            return None
        if not path.lower().endswith("." + suffix):
            path += "." + suffix
        session = self.document_session
        if session is None or session.current_valid_snapshot is None:
            return None
        snapshot = session.current_valid_snapshot

        def work(token):
            return self.export_service.export(
                kind,
                path,
                session.source_text,
                snapshot.model,
                overwrite=False,
                cancel_token=token,
            )

        self.graph_panel.set_busy(True, "正在导出状态图")
        return self._submit_product_task(
            "graph-render",
            {"mode": "export", "kind": kind, "path": path},
            work,
            "正在导出状态图",
            self._finish_graph_task,
        )

    @QtCore.pyqtSlot(object)
    def _finish_graph_task(self, result):
        action = self._workspace_task_actions.pop(result.stamp.task_id, {})
        status = self._history_status_for_result(result)
        artifacts = ()
        if result.status is TaskStatus.SUCCESS and action.get("mode") == "preview":
            self.graph_panel.present_png(result.value, action["revision"])
            summary = "状态图已刷新"
        elif result.status is TaskStatus.SUCCESS:
            self.graph_panel.set_busy(False, "导出完成")
            artifacts = (
                TaskArtifact(label="状态图", path=result.value.path),
            )
            summary = "状态图导出完成"
        elif result.status is TaskStatus.CANCELLED:
            self.graph_panel.set_busy(False, "cancelled，未发布截断产物")
            summary = "状态图任务已取消"
        elif result.status is TaskStatus.STALE:
            self.graph_panel.show_error("结果已过期，请刷新当前 revision")
            summary = "状态图结果已过期"
        else:
            self.graph_panel.show_error(result.error)
            summary = "状态图任务失败"
        self._complete_workspace_history(
            result, status, summary, artifacts=artifacts
        )
        self.graph_task_finished.emit(result)

    def _start_generation(self, request, dialog):
        session = self.document_session
        if session is None or session.current_valid_snapshot is None:
            dialog.show_error("当前 revision 无有效快照")
            return None
        snapshot = session.current_valid_snapshot

        def work(token):
            return self.generation_service.generate(
                snapshot.model,
                request["output_dir"],
                template_name=request.get("template_name"),
                custom_template_dir=request.get("custom_template_dir"),
                overwrite=request.get("overwrite", False),
                cancel_token=token,
            )

        dialog.set_busy(True, "正在生成代码")
        return self._submit_product_task(
            "code-generation",
            {"dialog": dialog, "request": dict(request)},
            work,
            "正在生成代码",
            self._finish_generation_task,
        )

    @QtCore.pyqtSlot(object)
    def _finish_generation_task(self, result):
        action = self._workspace_task_actions.pop(result.stamp.task_id, {})
        dialog = action.get("dialog")
        status = self._history_status_for_result(result)
        artifacts = ()
        if result.status is TaskStatus.SUCCESS:
            if dialog is not None:
                dialog.present_result(result.value)
            artifacts = (
                TaskArtifact(
                    label="生成代码目录",
                    path=result.value.output_dir,
                    kind="directory",
                    metadata={"files": len(result.value.files)},
                ),
            )
            summary = "代码生成完成：{} 个文件".format(len(result.value.files))
        elif result.status is TaskStatus.CANCELLED:
            if dialog is not None:
                dialog.show_cancelled()
            summary = "代码生成已取消，既有输出未修改"
        elif result.status is TaskStatus.STALE:
            if dialog is not None:
                dialog.show_error("结果已过期，请基于当前 revision 重试")
            summary = "代码生成结果已过期"
        else:
            if dialog is not None:
                dialog.show_error(result.error)
            summary = "代码生成失败"
        self._complete_workspace_history(
            result, status, summary, artifacts=artifacts
        )
        self.generation_finished.emit(result)

    def _start_unified_export(self, request, dialog):
        session = self.document_session
        if session is None or session.current_valid_snapshot is None:
            dialog.show_error("当前 revision 无有效快照")
            return None
        snapshot = session.current_valid_snapshot
        dynamic_json = self.dynamic_validation_panel.report_json()
        state_manager = self.state_manager

        def work(token):
            return self.export_service.export(
                request["kind"],
                request["path"],
                session.source_text,
                snapshot.model,
                state_manager=state_manager,
                inspect_report=snapshot.inspect_report,
                dynamic_report_json=dynamic_json,
                overwrite=request.get("overwrite", False),
                cancel_token=token,
            )

        dialog.set_busy(True, "正在导出")
        return self._submit_product_task(
            "unified-export",
            {"dialog": dialog, "request": dict(request)},
            work,
            "正在统一导出",
            self._finish_unified_export_task,
        )

    @QtCore.pyqtSlot(object)
    def _finish_unified_export_task(self, result):
        action = self._workspace_task_actions.pop(result.stamp.task_id, {})
        dialog = action.get("dialog")
        status = self._history_status_for_result(result)
        artifacts = ()
        if result.status is TaskStatus.SUCCESS:
            if dialog is not None:
                dialog.present_result(result.value)
            artifacts = (
                TaskArtifact(label="统一导出产物", path=result.value.path),
            )
            summary = "统一导出完成"
        elif result.status is TaskStatus.CANCELLED:
            if dialog is not None:
                dialog.show_cancelled()
            summary = "统一导出已取消，既有文件未修改"
        elif result.status is TaskStatus.STALE:
            if dialog is not None:
                dialog.show_error("结果已过期，请基于当前 revision 重试")
            summary = "统一导出结果已过期"
        else:
            if dialog is not None:
                dialog.show_error(result.error)
            summary = "统一导出失败"
        self._complete_workspace_history(
            result, status, summary, artifacts=artifacts
        )
        self.unified_export_finished.emit(result)

    def _submit_workspace_task(self, kind, action, work, running_summary):
        session = self.document_session
        if session is None:
            return None
        snapshot = self._require_current_snapshot_for_action(running_summary)
        if snapshot is None:
            return None
        handle = self.task_runner.submit(
            kind,
            session.source_revision,
            work,
            session_id=session.session_id,
            channel=kind,
            dependency_fingerprint=snapshot.dependency_fingerprint,
        )
        now = time.time()
        self.task_center.add(
            TaskRecord(
                task_id=handle.stamp.task_id,
                kind=kind,
                session_id=session.session_id,
                source_revision=session.source_revision,
                dependency_fingerprints=dict(snapshot.dependency_manifest),
                created_at=now,
                started_at=now,
                status=HistoryTaskStatus.RUNNING,
                summary=running_summary,
                messages=(),
                artifacts=(),
                retry_descriptor=None,
                exception_chain=(),
                boundary=TaskBoundary.EXPLICIT,
            )
        )
        self._task_handles[handle.stamp.task_id] = handle
        self._workspace_task_actions[handle.stamp.task_id] = action
        if kind == "ordinary-simulation":
            handle.finished.connect(self._finish_simulation_task)
            self.simulation_panel.set_busy(True, running_summary)
        else:
            handle.finished.connect(self._finish_dynamic_validation_task)
            self.dynamic_validation_panel.set_busy(True, running_summary)
        self._refresh_task_result_dock(show=True)
        return handle

    def _initialize_simulation(self, options):
        session = self.document_session
        if session is None or session.current_valid_snapshot is None:
            return None
        snapshot = session.current_valid_snapshot
        state = options.get("state")
        initial_state = tuple(item for item in state.split(".") if item) if state else None
        source_uri = Path(canonical_path(session.path)).as_uri()

        def work(token):
            token.raise_if_cancelled()
            simulation = self.simulation_service.start(
                session.source_text,
                source_uri=source_uri,
                source_revision=session.source_revision,
                dependency_fingerprint=snapshot.dependency_fingerprint,
                initial_state=initial_state,
                initial_vars=options.get("variables"),
                source_path=session.path,
                model=snapshot.model,
            )
            token.raise_if_cancelled()
            initial_cycle = None
            if initial_state is None:
                initial_cycle = self.simulation_service.cycle(simulation)
            return {"session": simulation, "initial_cycle": initial_cycle}

        return self._submit_workspace_task(
            "ordinary-simulation", "initialize", work, "正在初始化普通仿真"
        )

    def _cycle_simulation(self, events):
        simulation = self._simulation_session
        if simulation is None:
            return None

        def work(token):
            token.raise_if_cancelled()
            return self.simulation_service.cycle(simulation, events=events)

        return self._submit_workspace_task(
            "ordinary-simulation", "cycle", work, "正在执行一个 simulation cycle"
        )

    def _run_simulation(self, options):
        simulation = self._simulation_session
        if simulation is None:
            return None
        max_cycles = int(options["max_cycles"])
        events = tuple(options.get("events", ()))

        def work(token):
            return self.simulation_service.run(
                simulation,
                max_cycles=max_cycles,
                events_per_cycle=tuple(events for _ in range(max_cycles)),
                cancel_token=token,
            )

        return self._submit_workspace_task(
            "ordinary-simulation", "run", work, "正在连续运行普通仿真"
        )

    def _reset_simulation(self):
        simulation = self._simulation_session
        if simulation is None:
            return None

        def work(token):
            token.raise_if_cancelled()
            snapshot = self.simulation_service.reset(simulation)
            initial_cycle = None
            if simulation.initial_state is None:
                initial_cycle = self.simulation_service.cycle(simulation)
                snapshot = initial_cycle.snapshot
            return {"snapshot": snapshot, "initial_cycle": initial_cycle}

        return self._submit_workspace_task(
            "ordinary-simulation", "reset", work, "正在重置普通仿真"
        )

    @QtCore.pyqtSlot(object)
    def _finish_simulation_task(self, result):
        action = self._workspace_task_actions.pop(result.stamp.task_id, None)
        history_status = self._history_status_for_result(result)
        messages = ()
        if result.status is TaskStatus.SUCCESS:
            if action == "initialize":
                self._simulation_session = result.value["session"]
                self.simulation_panel.set_initialized(
                    self._simulation_session.snapshot()
                )
                initial_cycle = result.value["initial_cycle"]
                if initial_cycle is not None:
                    self.simulation_panel.append_cycles((initial_cycle,))
                    if initial_cycle.error is not None:
                        history_status = HistoryTaskStatus.FAILED
                        messages = (
                            self._simulation_error_message(initial_cycle.error),
                        )
            elif action == "cycle":
                self.simulation_panel.append_cycles((result.value,))
                if result.value.error is not None:
                    history_status = HistoryTaskStatus.FAILED
                    messages = (self._simulation_error_message(result.value.error),)
            elif action == "run":
                self.simulation_panel.append_cycles(result.value.cycles)
                if result.value.cancelled:
                    history_status = HistoryTaskStatus.CANCELLED
                    self.simulation_panel.show_cancelled()
                elif result.value.cycles and result.value.cycles[-1].error is not None:
                    history_status = HistoryTaskStatus.FAILED
                    messages = (
                        self._simulation_error_message(result.value.cycles[-1].error),
                    )
            elif action == "reset":
                self.simulation_panel.set_initialized(result.value["snapshot"])
                initial_cycle = result.value["initial_cycle"]
                if initial_cycle is not None:
                    self.simulation_panel.append_cycles((initial_cycle,))
                    if initial_cycle.error is not None:
                        history_status = HistoryTaskStatus.FAILED
                        messages = (
                            self._simulation_error_message(initial_cycle.error),
                        )
        elif result.status is TaskStatus.CANCELLED:
            if action == "run" and result.value is not None:
                self.simulation_panel.append_cycles(result.value.cycles)
            self.simulation_panel.show_cancelled()
        elif result.status is TaskStatus.STALE:
            self._simulation_session = None
            self.simulation_panel.invalidate()
        else:
            self.simulation_panel.show_error(result.error)
        summary = {
            HistoryTaskStatus.SUCCESS: "普通仿真操作完成",
            HistoryTaskStatus.CANCELLED: "普通仿真已在 cycle 边界取消",
            HistoryTaskStatus.STALE: "普通仿真结果已过期",
        }.get(history_status, "普通仿真失败")
        self._complete_workspace_history(
            result, history_status, summary, messages=messages
        )
        self.simulation_task_finished.emit(result)

    @staticmethod
    def _simulation_error_message(error):
        return {
            "severity": "error",
            "message": "{}: {}".format(error.type, error.message),
            "cause_type": error.cause_type,
            "cause_message": error.cause_message,
        }

    def _run_dynamic_validation(self, request):
        mode = request.get("mode")
        if mode == "user":
            path = request.get("path")

            def work(token):
                return (None, self.dynamic_validation_service.run_scenario(path, cancel_token=token))

            action = {"mode": "user", "path": path}
            summary = "正在运行用户动态验证场景"
        elif mode == "case":
            case_id = request.get("case_id")

            def work(token):
                provenance = self.dynamic_validation_service.verify_packaged_provenance()
                if provenance.status != "passed":
                    raise ValueError("内置动态验证资源 provenance 校验失败")
                return (
                    provenance,
                    self.dynamic_validation_service.run_packaged_case(
                        case_id, cancel_token=token
                    ),
                )

            action = {"mode": "case", "case_id": case_id}
            summary = "正在运行内置动态验证用例"
        elif mode == "suite":

            def work(token):
                provenance = self.dynamic_validation_service.verify_packaged_provenance()
                if provenance.status != "passed":
                    raise ValueError("内置动态验证资源 provenance 校验失败")
                return (
                    provenance,
                    self.dynamic_validation_service.run_packaged_cases(
                        cancel_token=token
                    ),
                )

            action = {"mode": "suite"}
            summary = "正在运行全部动态验证验收用例"
        else:
            self.dynamic_validation_panel.show_error("未知动态验证模式")
            return None
        return self._submit_workspace_task(
            "dynamic-validation", action, work, summary
        )

    @QtCore.pyqtSlot(object)
    def _finish_dynamic_validation_task(self, result):
        action = self._workspace_task_actions.pop(result.stamp.task_id, None)
        history_status = self._history_status_for_result(result)
        messages = ()
        artifacts = ()
        if result.status is TaskStatus.SUCCESS and action == "export":
            path = result.value
            artifacts = (TaskArtifact(label="动态验证报告", path=path),)
            self.dynamic_validation_panel.set_busy(False, "report-ready")
        elif result.status is TaskStatus.SUCCESS:
            provenance, report = result.value
            self.dynamic_validation_panel.present_report(report, provenance=provenance)
            if report.status == "cancelled":
                history_status = HistoryTaskStatus.CANCELLED
                self.dynamic_validation_panel.show_cancelled()
            elif report.status in ("failed", "mismatch"):
                history_status = HistoryTaskStatus.FAILED
            messages = self._dynamic_report_messages(report)
        elif result.status is TaskStatus.CANCELLED:
            if result.value is not None and action != "export":
                provenance, report = result.value
                self.dynamic_validation_panel.present_report(
                    report, provenance=provenance
                )
                messages = self._dynamic_report_messages(report)
            self.dynamic_validation_panel.show_cancelled()
        elif result.status is TaskStatus.STALE:
            self.dynamic_validation_panel.show_error("结果已过期，请基于当前 revision 重试")
        else:
            self.dynamic_validation_panel.show_error(result.error)
        summary = {
            HistoryTaskStatus.SUCCESS: "动态验证完成",
            HistoryTaskStatus.CANCELLED: "动态验证已在 step 边界取消",
            HistoryTaskStatus.STALE: "动态验证结果已过期",
        }.get(history_status, "动态验证未通过")
        self._complete_workspace_history(
            result,
            history_status,
            summary,
            messages=messages,
            artifacts=artifacts,
        )
        self.dynamic_validation_finished.emit(result)

    @staticmethod
    def _dynamic_report_messages(report):
        messages = []
        cases = report.cases if hasattr(report, "cases") else (report,)
        for case in cases:
            if case.failure is not None:
                messages.append(
                    {
                        "severity": "error",
                        "case_id": case.case_id,
                        "message": case.failure.get("message", "case failed"),
                    }
                )
            for step in case.steps:
                if step.status not in ("passed", "expected_exception_passed"):
                    messages.append(
                        {
                            "severity": "error",
                            "case_id": case.case_id,
                            "step": step.index,
                            "message": json.dumps(
                                step.diffs, ensure_ascii=False, sort_keys=True
                            ),
                        }
                    )
        return tuple(messages)

    def _export_dynamic_validation_report(self):
        content = self.dynamic_validation_panel.report_json()
        if content is None:
            return None
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "导出动态验证报告",
            "dynamic-validation-report.json",
            "JSON 报告 (*.json)",
        )
        if not path:
            return None
        if not path.lower().endswith(".json"):
            path += ".json"

        def work(token):
            token.raise_if_cancelled()
            target = Path(path)
            temporary = target.with_name(target.name + ".tmp")
            try:
                temporary.write_text(content, encoding="utf-8")
                token.raise_if_cancelled()
                os.replace(str(temporary), str(target))
            finally:
                try:
                    temporary.unlink()
                except OSError:
                    pass
            return str(target)

        return self._submit_workspace_task(
            "dynamic-validation", "export", work, "正在导出动态验证报告"
        )

    def _cancel_workspace_kind(self, kind):
        record = next(
            (
                item
                for item in reversed(self.task_center.records)
                if item.kind == kind
                and item.status
                in {
                    HistoryTaskStatus.QUEUED,
                    HistoryTaskStatus.RUNNING,
                    HistoryTaskStatus.CANCEL_REQUESTED,
                }
            ),
            None,
        )
        return bool(record and self._cancel_task_record(record.task_id))

    @staticmethod
    def _history_status_for_result(result):
        return {
            TaskStatus.SUCCESS: HistoryTaskStatus.SUCCESS,
            TaskStatus.FAILED: HistoryTaskStatus.FAILED,
            TaskStatus.CANCELLED: HistoryTaskStatus.CANCELLED,
            TaskStatus.STALE: HistoryTaskStatus.STALE,
        }.get(result.status, HistoryTaskStatus.FAILED)

    def _complete_workspace_history(
        self, result, status, summary, messages=(), artifacts=()
    ):
        completion = {
            "summary": summary,
            "messages": messages,
            "artifacts": artifacts,
        }
        if result.error is not None:
            completion["exception"] = result.error
        try:
            self.task_center.complete_persistent(
                result.stamp.task_id, status, **completion
            )
        except OSError as error:
            self.statusbar.showMessage(
                "任务历史写入失败，内存结果仍可查看：{}".format(error), 15000
            )
        finally:
            self._task_handles.pop(result.stamp.task_id, None)
            self._refresh_task_result_dock(show=True)

    def _refresh_task_result_dock(self, show=False):
        self.task_result_dock.refresh()
        if show and self.isVisible():
            self.task_result_dock.show()

    def _complete_load_task(self, outcome, file_path):
        status = {
            TaskStatus.SUCCESS: HistoryTaskStatus.SUCCESS,
            TaskStatus.FAILED: HistoryTaskStatus.FAILED,
            TaskStatus.CANCELLED: HistoryTaskStatus.CANCELLED,
            TaskStatus.STALE: HistoryTaskStatus.STALE,
        }.get(outcome.status, HistoryTaskStatus.FAILED)
        summary = {
            HistoryTaskStatus.SUCCESS: "已加载 {}".format(file_path),
            HistoryTaskStatus.CANCELLED: "已取消加载 {}".format(file_path),
            HistoryTaskStatus.STALE: "加载结果已过期 {}".format(file_path),
        }.get(status, "加载失败 {}: {}".format(file_path, outcome.error))
        completion = {}
        session = outcome.value if status is HistoryTaskStatus.SUCCESS else None
        if session is not None:
            completion.update(
                session_id=session.session_id,
                source_revision=session.source_revision,
            )
            snapshot = session.current_valid_snapshot
            if snapshot is not None:
                completion["dependency_fingerprints"] = dict(
                    snapshot.dependency_manifest
                )
            if session.current_diagnostics:
                completion["messages"] = tuple(
                    {
                        "severity": getattr(item, "severity", "info"),
                        "message": str(item),
                    }
                    for item in session.current_diagnostics
                )
        if outcome.error is not None:
            completion["exception"] = outcome.error
        try:
            self.task_center.complete_persistent(
                outcome.operation_id,
                status,
                summary=summary,
                **completion
            )
        except (KeyError, StopIteration):
            pass
        except OSError as error:
            self.statusbar.showMessage(
                "任务历史写入失败，原历史保持不变：{}".format(error),
                15000,
            )
        finally:
            self._logical_load_operations.pop(outcome.operation_id, None)
            self._refresh_task_result_dock(show=True)

    def _cancel_task_record(self, task_id):
        operation = self._logical_load_operations.get(task_id)
        handle = self._task_handles.get(task_id)
        if operation is None and handle is None:
            return False
        record = next(
            (item for item in self.task_center.records if item.task_id == task_id),
            None,
        )
        kind = record.kind if record is not None else (
            "document-load" if operation is not None else "model-check"
        )
        summary = {
            "document-load": "正在取消加载",
            "model-check": "正在取消模型检查",
            "ordinary-simulation": "正在 cycle 边界取消普通仿真",
            "dynamic-validation": "正在 step 边界取消动态验证",
            "graph-render": "正在取消状态图任务",
            "code-generation": "正在取消代码生成",
            "unified-export": "正在取消统一导出",
        }.get(kind, "正在取消任务")
        try:
            self.task_center.transition(
                task_id,
                HistoryTaskStatus.CANCEL_REQUESTED,
                summary=summary,
            )
        except ValueError:
            return False
        if operation is not None:
            operation.cancel()
        else:
            handle.cancel()
        self._refresh_task_result_dock(show=True)
        return True

    def _retry_task_record(self, record):
        descriptor = record.retry_descriptor or {}
        if descriptor.get("kind") == "model-check":
            return self._validate_statechart()
        if descriptor.get("kind") != "document-load":
            return None
        path = descriptor.get("path")
        if not path or any(
            marker in str(path)
            for marker in ("<WORKSPACE>", "<HOME>", "<TEMP>")
        ):
            return None
        if not self._confirm_document_replacement():
            return None
        hints = tuple(tuple(item) for item in descriptor.get("encoding_hints", ()))
        return self._start_document_load(
            path,
            encoding=descriptor.get("encoding"),
            encoding_hints=hints,
        )
