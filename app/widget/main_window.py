from dataclasses import dataclass
from typing import Optional, Dict, List
import os
import uuid

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
    DocumentDependencyStaleError,
    DocumentService,
    DocumentValidationError,
    InvalidDocumentSaveError,
    TextEdit,
)
from app.application.task_runner import TaskResult, TaskRunner, TaskStatus
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
from .dialog_show_graph import DialogShowGraph
from app.utils.ui_to_dsl import state_manager_to_dsl
from .dialog_show_error import DialogShowError
from .dialog_code_gen import DialogCodeGen
from .dialog_add_lifecycle import DialogAddLifecycle
from .dialog_add_transition import DialogAddTransition
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


class AppMainWindow(QMainWindow, UIMainWindow):
    document_load_finished = QtCore.pyqtSignal(object)
    document_validation_finished = QtCore.pyqtSignal(object)
    state_manager: Optional[StateManager]

    def __init__(self, settings=None):
        QMainWindow.__init__(self)
        self.setupUi(self)
        self.at_page_initial = True
        #self.fcstm_state_chart = None
        self.code_file_path = "./"
        self.state_machine_file_path = "./"
        self.document_service = DocumentService()
        self.document_session = None
        self.settings = settings if settings is not None else QtCore.QSettings(
            "zhougut", "fcstm-gui"
        )
        self.task_runner = TaskRunner(parent=self)
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
        '''
        self._init_button_save_state()
        '''

    def _init_window_style(self):
        self.stackedWidget_state_machine.setCurrentIndex(0)
        self._init_tree_style()
        self._init_button_style()
        self._init_text_edit_style()
        self._init_table_style()

    def _init_menu_bar(self):
        """初始化菜单栏"""
        # 文件菜单
        self.menu_file.addAction(self.action_import_state_machine)
        self.action_save_state_machine = QtWidgets.QAction("保存", self)
        self.action_save_state_machine.setShortcut(QtGui.QKeySequence.Save)
        self.menu_file.addAction(self.action_save_state_machine)
        self.menu_file.addAction(self.action_export_state_machine)
        
        # 工具菜单
        self.menu_tool.addAction(self.action_validate_state_machine)
        self.menu_tool.addAction(self.action_graph_gen)
        self.menu_tool.addAction(self.action_code_gen)
        
        # 连接菜单项信号
        self.action_import_state_machine.triggered.connect(self._import_statechart)
        self.action_save_state_machine.triggered.connect(self._save_current_document)
        self.action_export_state_machine.triggered.connect(self._export_statechart)
        self.action_validate_state_machine.triggered.connect(self._validate_statechart)
        self.action_graph_gen.triggered.connect(self._graph_gen)

        self.action_code_gen.triggered.connect(self._code_gen)

    def _init_source_editor(self):
        self.setWindowTitle("fcstm[*]")
        self.source_dock = QtWidgets.QDockWidget("源码", self)
        self.source_dock.setObjectName("source_dock")
        self.source_editor = QtWidgets.QPlainTextEdit(self.source_dock)
        self.source_editor.setObjectName("source_editor")
        self.source_editor.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.source_dock.setWidget(self.source_editor)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.source_dock)
        self.source_dock.hide()
        self.source_editor.textChanged.connect(self._on_source_text_changed)
        self.action_save_state_machine.setEnabled(False)

    def _init_import_state_chart(self):
        self._init_button_initial_import_state_machine()

    def _init_button_initial_import_state_machine(self):
        self.button_initial_import_state_machine.clicked.connect(lambda: self._import_statechart())

    def _init_button_initial_new_state_machine(self):
        self.button_initial_new_state_machine.clicked.connect(lambda: self._new_state_machine())

    def _new_state_machine(self):
        self.state_manager = StateManager()
        if self.at_page_initial:
            self.stackedWidget_state_machine.setCurrentIndex(1)
            self.at_page_initial = False

    def _init_tree_style(self):
        self.tree_all_state.header().hide()
        self.tree_all_state.setTextElideMode(Qt.ElideNone)
        self.tree_all_state.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        #self.tree_all_state.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.tree_all_state.header().setMinimumSectionSize(800)
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
        operation = operation or DocumentLoadOperation(parent=self)

        def load_document(token):
            token.raise_if_cancelled()
            session = service.load(
                file_path,
                encoding=encoding,
                encoding_hints=encoding_hints,
            )
            token.raise_if_cancelled()
            return session

        handle = self.task_runner.submit(
            "document-load",
            0,
            load_document,
            channel="document-load",
        )
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
        previous_dock_visible = self.source_dock.isVisible()
        previous_page = self.stackedWidget_state_machine.currentIndex()
        previous_at_initial = self.at_page_initial
        try:
            self._setting_source_text = True
            try:
                self.source_editor.setPlainText(session.source_text)
            finally:
                self._setting_source_text = False
            self.source_dock.show()
            self._setting_projection = True
            try:
                if manager is None:
                    self._clear_model_projection()
                else:
                    update_ui_from_state_manager(self, manager)
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
                self.source_dock.setVisible(previous_dock_visible)
                self._update_document_actions()
            raise

        self.document_session = session
        self.state_manager = manager
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
        self.state_manager = None
        self.tree_all_state.clear()
        self.edit_var_def.clear()
        self.table_transition.setRowCount(0)
        self.table_lifecycle.setRowCount(0)

    def _update_document_actions(self):
        session = self.document_session
        current_valid = (
            session is not None and session.current_valid_snapshot is not None
        )
        self.action_save_state_machine.setEnabled(session is not None)
        self.action_graph_gen.setEnabled(current_valid)
        self.action_code_gen.setEnabled(current_valid)
        self.edit_var_def.setReadOnly(session is not None and not current_valid)
        self.button_add_state.setEnabled(session is None or current_valid)
        self.button_lifecycle.setEnabled(session is None or current_valid)
        self.button_transition.setEnabled(session is None or current_valid)
        self.setWindowModified(bool(session and session.dirty))
        if session is not None:
            self.setWindowFilePath(session.path)

    def _on_source_text_changed(self):
        if self._setting_source_text or self.document_session is None:
            return
        source_text = self.source_editor.toPlainText()
        pending = self.document_service.prepare_source_text(
            self.document_session, source_text
        )
        if pending is self.document_session:
            return
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
        handle.finished.connect(self._finish_document_validation)

    @QtCore.pyqtSlot(object)
    def _finish_document_validation(self, result):
        try:
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
                warning_count = sum(
                    1
                    for item in self.document_session.current_diagnostics
                    if str(getattr(item, "severity", "")).lower() == "warning"
                )
                message = "状态机检查通过！"
                if warning_count:
                    message += "\n{} 条警告。".format(warning_count)
                QtWidgets.QMessageBox.information(self, "检查结果", message)
                return snapshot.inspect_report
            # 获取当前的DSL代码
            dsl_content = state_manager_to_dsl(self.state_manager)
            
            # 解析DSL
            ast_node = parse_with_grammar_entry(dsl_content, entry_name='state_machine_dsl')
            state_machine = parse_dsl_node_to_state_machine(ast_node)
            
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

    def _graph_gen(self):
        try:
            if self.state_manager is None:
                QtWidgets.QMessageBox.warning(
                    self,
                    "警告",
                    "请先创建或导入状态机！",
                    QtWidgets.QMessageBox.Ok
                )
                return
            model = None
            if self.document_session is not None:
                snapshot = self._require_current_snapshot_for_action("状态图")
                if snapshot is None:
                    return
                model = snapshot.model
            dialog_show_graph = DialogShowGraph(
                self, self.state_manager, model=model
            )
            dialog_show_graph.exec_()

        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"生成状态图时发生错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

    def _code_gen(self):
        """代码生成功能"""
        try:
            if self.state_manager is None:
                QtWidgets.QMessageBox.warning(
                    self,
                    "警告",
                    "请先创建或导入状态机！",
                    QtWidgets.QMessageBox.Ok
                )
                return
            
            # 显示代码生成对话框
            model = None
            if self.document_session is not None:
                snapshot = self._require_current_snapshot_for_action("代码生成")
                if snapshot is None:
                    return
                model = snapshot.model
            dialog = DialogCodeGen(self, self.state_manager, model=model)
            dialog.exec_()
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"代码生成时发生错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

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

    def _on_tree_item_selection_changed(self):
        """
        当树形控件中的选择发生变化时，更新转移信息和生命周期信息表格
        """
        try:
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
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "错误",
                f"更新状态信息时发生错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )

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

    def _commit_form_edits(self, edits):
        try:
            updated = self.document_service.apply_edits(
                self.document_session, edits
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
        self._set_active_document_session(updated)
        return True
