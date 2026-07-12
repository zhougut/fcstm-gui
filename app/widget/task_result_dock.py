import json
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets

from app.application.tasks import TaskStatus


_STATUS_LABELS = {
    TaskStatus.QUEUED: "排队中",
    TaskStatus.RUNNING: "运行中",
    TaskStatus.SUCCESS: "成功",
    TaskStatus.FAILED: "失败",
    TaskStatus.STALE: "已失效",
    TaskStatus.CANCEL_REQUESTED: "正在取消",
    TaskStatus.CANCELLED: "已取消",
}


class TaskResultDock(QtWidgets.QDockWidget):
    retry_requested = QtCore.pyqtSignal(object)
    cancel_requested = QtCore.pyqtSignal(str)

    def __init__(self, task_center, parent=None, settings=None):
        super().__init__("任务结果", parent)
        self.setObjectName("task_result_dock")
        self._task_center = task_center
        self._settings = (
            settings if settings is not None else getattr(parent, "settings", None)
        )
        self._show_full_paths = self._read_show_full_paths_setting()
        self._visible_records = ()
        self._build_ui()
        self._update_path_mode_labels()
        self.refresh()

    def _read_show_full_paths_setting(self):
        if self._settings is None:
            return False
        return self._settings.value(
            "task_center/show_full_paths", False, type=bool
        )

    def _build_ui(self):
        container = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)

        filters = QtWidgets.QHBoxLayout()
        self.status_filter = QtWidgets.QComboBox(container)
        self.status_filter.setObjectName("task_status_filter")
        self.status_filter.setAccessibleName("任务状态筛选")
        self.status_filter.setToolTip("按任务状态筛选结果")
        self.status_filter.addItem("全部状态", None)
        for status in TaskStatus:
            self.status_filter.addItem(_STATUS_LABELS[status], status.value)
        self.search_edit = QtWidgets.QLineEdit(container)
        self.search_edit.setObjectName("task_search_edit")
        self.search_edit.setAccessibleName("任务结果搜索")
        self.search_edit.setPlaceholderText("筛选任务结果")
        self.search_edit.setToolTip("搜索脱敏后的任务结果")
        self.path_display_button = QtWidgets.QToolButton(container)
        self.path_display_button.setObjectName("task_path_display_button")
        self.path_display_button.setText("路径显示")
        self.path_display_button.setAccessibleName("任务路径显示设置")
        self.path_display_button.setToolTip("设置任务结果中的路径显示方式")
        self.path_display_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        path_menu = QtWidgets.QMenu(self.path_display_button)
        self.show_full_paths_action = path_menu.addAction("显示完整路径")
        self.show_full_paths_action.setObjectName("action_task_show_full_paths")
        self.show_full_paths_action.setCheckable(True)
        self.show_full_paths_action.setChecked(self._show_full_paths)
        self.show_full_paths_action.setToolTip(
            "显式显示、复制和导出内存中可用的完整路径"
        )
        self.path_display_button.setMenu(path_menu)
        filters.addWidget(self.status_filter)
        filters.addWidget(self.search_edit, 1)
        filters.addWidget(self.path_display_button)
        layout.addLayout(filters)

        self.table = QtWidgets.QTableWidget(container)
        self.table.setObjectName("task_result_table")
        self.table.setAccessibleName("任务结果列表")
        self.table.setToolTip("任务结果列表")
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ("状态", "任务", "revision", "摘要", "时间", "操作")
        )
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            3, QtWidgets.QHeaderView.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            5, QtWidgets.QHeaderView.ResizeToContents
        )
        self.detail = QtWidgets.QPlainTextEdit(container)
        self.detail.setObjectName("task_result_detail")
        self.detail.setAccessibleName("任务详情")
        self.detail.setToolTip("所选任务的脱敏详情")
        self.detail.setReadOnly(True)
        self.detail.setMaximumBlockCount(2000)
        self.artifact_list = QtWidgets.QListWidget(container)
        self.artifact_list.setObjectName("task_artifact_list")
        self.artifact_list.setAccessibleName("任务产物")
        self.artifact_list.setToolTip("当前任务生成的产物")
        self.artifact_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self.result_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal, container)
        self.result_splitter.setObjectName("task_result_splitter")
        self.result_splitter.addWidget(self.table)
        self.result_views = QtWidgets.QTabWidget(self.result_splitter)
        self.result_views.setObjectName("task_result_views")
        detail_page = QtWidgets.QWidget(self.result_views)
        detail_layout = QtWidgets.QVBoxLayout(detail_page)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.addWidget(self.detail)
        artifact_page = QtWidgets.QWidget(self.result_views)
        artifact_layout = QtWidgets.QVBoxLayout(artifact_page)
        artifact_layout.setContentsMargins(0, 0, 0, 0)
        artifact_layout.addWidget(self.artifact_list)
        self.result_views.addTab(detail_page, "详情")
        self.result_views.addTab(artifact_page, "产物")
        self.result_splitter.addWidget(self.result_views)
        self.result_splitter.setStretchFactor(0, 3)
        self.result_splitter.setStretchFactor(1, 2)
        layout.addWidget(self.result_splitter, 1)

        commands = QtWidgets.QHBoxLayout()
        self.copy_button = QtWidgets.QPushButton("复制", container)
        self.export_button = QtWidgets.QPushButton("导出日志", container)
        self.retry_button = QtWidgets.QPushButton("重试", container)
        self.cancel_button = QtWidgets.QPushButton("取消", container)
        self.open_artifact_button = QtWidgets.QPushButton("打开文件", container)
        self.open_artifact_directory_button = QtWidgets.QPushButton(
            "打开目录", container
        )
        self.clear_filtered_button = QtWidgets.QPushButton(
            "清空筛选结果", container
        )
        self.clear_all_button = QtWidgets.QPushButton("清空全部历史", container)
        buttons = (
            (self.copy_button, "task_copy_button", "复制脱敏后的任务详情"),
            (
                self.export_button,
                "task_export_button",
                "导出脱敏后的任务日志",
            ),
            (self.retry_button, "task_retry_button", "重试所选任务"),
            (self.cancel_button, "task_cancel_button", "取消所选任务"),
            (
                self.open_artifact_button,
                "task_open_artifact_button",
                "使用系统默认程序打开所选产物文件",
            ),
            (
                self.open_artifact_directory_button,
                "task_open_artifact_directory_button",
                "在文件管理器中打开所选产物所在目录",
            ),
            (
                self.clear_filtered_button,
                "task_clear_filtered_button",
                "删除当前筛选出的持久任务记录",
            ),
            (
                self.clear_all_button,
                "task_clear_all_button",
                "删除全部持久任务历史",
            ),
        )
        for button, object_name, tooltip in buttons:
            button.setObjectName(object_name)
            button.setToolTip(tooltip)
            button.setAccessibleName(button.text())
            commands.addWidget(button)
        commands.addStretch(1)
        layout.addLayout(commands)

        self.setWidget(container)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        self.search_edit.textChanged.connect(self.refresh)
        self.show_full_paths_action.toggled.connect(self._set_show_full_paths)
        self.table.itemSelectionChanged.connect(self._update_detail)
        self.artifact_list.itemSelectionChanged.connect(
            self._update_artifact_actions
        )
        self.copy_button.clicked.connect(self.copy_selected)
        self.export_button.clicked.connect(self.export_selected)
        self.retry_button.clicked.connect(self.retry_selected)
        self.cancel_button.clicked.connect(self.cancel_selected)
        self.open_artifact_button.clicked.connect(self.open_selected_artifact)
        self.open_artifact_directory_button.clicked.connect(
            self.open_selected_artifact_directory
        )
        self.clear_filtered_button.clicked.connect(self.clear_filtered)
        self.clear_all_button.clicked.connect(self.clear_all)

    def sizeHint(self):
        return QtCore.QSize(900, 220)

    @property
    def selected_record(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._visible_records):
            return None
        return self._visible_records[row]

    def _record_matches(self, record):
        status_value = self.status_filter.currentData()
        if status_value is not None and record.status.value != status_value:
            return False
        query = self.search_edit.text().strip().casefold()
        if not query:
            return True
        haystack = self._detail_payload(record).casefold()
        return query in haystack

    def _display_text(self, value):
        text = str(value)
        if self._show_full_paths:
            return text
        return self._task_center.redactor.redact_text(text)

    def _set_show_full_paths(self, enabled):
        self._show_full_paths = bool(enabled)
        if self._settings is not None:
            self._settings.setValue(
                "task_center/show_full_paths", self._show_full_paths
            )
        self._update_path_mode_labels()
        self.refresh()

    def _update_path_mode_labels(self):
        qualifier = "包含完整路径" if self._show_full_paths else "脱敏后的"
        self.copy_button.setToolTip("复制{}任务详情".format(qualifier))
        self.export_button.setToolTip("导出{}任务日志".format(qualifier))
        self.search_edit.setToolTip("搜索{}任务结果".format(qualifier))

    @staticmethod
    def _format_local_time(timestamp):
        try:
            milliseconds = int(float(timestamp) * 1000)
        except (TypeError, ValueError, OverflowError):
            return "-"
        value = QtCore.QDateTime.fromMSecsSinceEpoch(milliseconds)
        if not value.isValid():
            return "-"
        return value.toLocalTime().toString("yyyy-MM-dd HH:mm:ss")

    def refresh(self):
        selected_id = getattr(self.selected_record, "task_id", None)
        self._visible_records = tuple(
            record
            for record in self._task_center.records
            if self._record_matches(record)
        )
        self.table.setRowCount(len(self._visible_records))
        selected_row = -1
        for row, record in enumerate(self._visible_records):
            values = (
                _STATUS_LABELS[record.status],
                self._display_text(record.kind),
                "r{}".format(record.source_revision),
                self._display_text(record.summary),
                self._format_local_time(record.created_at),
            )
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row, column, item)
            self.table.setCellWidget(row, 5, self._create_row_action(record))
            if record.task_id == selected_id:
                selected_row = row
        if selected_row >= 0:
            self.table.setCurrentCell(selected_row, 0)
            self.table.selectRow(selected_row)
        elif self._visible_records:
            self.table.setCurrentCell(0, 0)
            self.table.selectRow(0)
        else:
            self.detail.clear()
        self._update_detail()

    def _create_row_action(self, record):
        button = QtWidgets.QPushButton(self.table)
        button.setObjectName("task_row_action_button")
        button.setProperty("task_id", record.task_id)
        button.setMinimumWidth(76)
        button.setFixedHeight(24)
        display_id = self._display_text(record.task_id)
        if self._can_cancel(record):
            button.setText("取消")
            button.setAccessibleName("取消任务 {}".format(display_id))
            button.setToolTip("取消任务 {}".format(display_id))
            button.clicked.connect(
                lambda checked=False, task_id=record.task_id: (
                    self.cancel_requested.emit(task_id)
                )
            )
            return button
        if self._can_retry(record):
            button.setText("重试")
            button.setAccessibleName("重试任务 {}".format(display_id))
            button.setToolTip("使用原任务参数重试任务 {}".format(display_id))
            button.clicked.connect(
                lambda checked=False, selected=record: (
                    self.retry_requested.emit(selected)
                )
            )
            return button
        if (
            record.status
            in {
                TaskStatus.SUCCESS,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
                TaskStatus.STALE,
            }
            and record.retry_descriptor
            and self._contains_redacted_path(record.retry_descriptor)
        ):
            button.setText("重试")
            button.setAccessibleName("任务 {} 重试不可用".format(display_id))
            button.setToolTip("重试需要完整路径；当前记录仅保留脱敏路径")
        else:
            button.setText("无操作")
            button.setAccessibleName("任务 {} 当前无可用操作".format(display_id))
            button.setToolTip("当前任务状态没有可用操作")
        button.setEnabled(False)
        return button

    def _detail_payload(self, record):
        if record is None:
            return ""
        return self._task_center.copy_payload(
            record, include_raw_paths=self._show_full_paths
        )

    def _update_detail(self):
        record = self.selected_record
        self.detail.setPlainText(self._detail_payload(record))
        self._populate_artifacts(record)
        self.copy_button.setEnabled(record is not None)
        self.export_button.setEnabled(record is not None)
        self.retry_button.setEnabled(self._can_retry(record))
        self.cancel_button.setEnabled(self._can_cancel(record))

    def _can_retry(self, record):
        return bool(
            record is not None
            and record.status
            in {
                TaskStatus.SUCCESS,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
                TaskStatus.STALE,
            }
            and record.retry_descriptor
            and not self._contains_redacted_path(record.retry_descriptor)
        )

    @staticmethod
    def _can_cancel(record):
        return record is not None and record.status in {
            TaskStatus.QUEUED,
            TaskStatus.RUNNING,
        }

    @staticmethod
    def _contains_redacted_path(value):
        if isinstance(value, str):
            return any(
                marker in value for marker in ("<WORKSPACE>", "<HOME>", "<TEMP>")
            )
        if isinstance(value, dict):
            return any(
                TaskResultDock._contains_redacted_path(key)
                or TaskResultDock._contains_redacted_path(item)
                for key, item in value.items()
            )
        if isinstance(value, (list, tuple)):
            return any(TaskResultDock._contains_redacted_path(item) for item in value)
        return False

    def _populate_artifacts(self, record):
        self.artifact_list.clear()
        if record is None:
            self._update_artifact_actions()
            return
        for index, artifact in enumerate(record.artifacts):
            label = self._display_text(artifact.label)
            path = self._display_text(artifact.path)
            item = QtWidgets.QListWidgetItem("{} | {}".format(label, path))
            item.setData(QtCore.Qt.UserRole, index)
            item.setToolTip(path)
            self.artifact_list.addItem(item)
        if self.artifact_list.count():
            self.artifact_list.setCurrentRow(0)
        self._update_artifact_actions()

    @property
    def selected_artifact(self):
        record = self.selected_record
        item = self.artifact_list.currentItem()
        if record is None or item is None:
            return None
        index = item.data(QtCore.Qt.UserRole)
        if not isinstance(index, int) or not 0 <= index < len(record.artifacts):
            return None
        return record.artifacts[index]

    def _artifact_targets(self):
        artifact = self.selected_artifact
        if artifact is None or not artifact.raw_path_available:
            return None, None
        path = Path(artifact.path)
        if not path.exists():
            return None, None
        file_target = path if path.is_file() else None
        directory_target = path if path.is_dir() else path.parent
        return file_target, directory_target

    def _update_artifact_actions(self):
        file_target, directory_target = self._artifact_targets()
        self.open_artifact_button.setEnabled(file_target is not None)
        self.open_artifact_directory_button.setEnabled(directory_target is not None)

    def open_selected_artifact(self):
        file_target, _ = self._artifact_targets()
        if file_target is None:
            return False
        return QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(file_target))
        )

    def open_selected_artifact_directory(self):
        _, directory_target = self._artifact_targets()
        if directory_target is None:
            return False
        return QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(directory_target))
        )

    def copy_selected(self):
        payload = self._detail_payload(self.selected_record)
        if payload:
            QtWidgets.QApplication.clipboard().setText(payload)

    def export_selected(self):
        record = self.selected_record
        if record is None:
            return False
        safe_task_id = "".join(
            character if character.isalnum() or character in "._-" else "_"
            for character in self._display_text(record.task_id)
        ).strip("._")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "导出任务日志",
            "task-{}.json".format(safe_task_id or "result"),
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return False
        payload = json.loads(self._detail_payload(record))
        with open(path, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2, sort_keys=True)
            file.write("\n")
        return True

    def retry_selected(self):
        record = self.selected_record
        if self._can_retry(record):
            self.retry_requested.emit(record)

    def cancel_selected(self):
        record = self.selected_record
        if self._can_cancel(record):
            self.cancel_requested.emit(record.task_id)

    def _matches_visible_filter(self, record):
        return record in self._visible_records

    def clear_filtered(self):
        if not self._visible_records:
            return 0
        reply = QtWidgets.QMessageBox.question(
            self,
            "清空筛选结果",
            "删除当前筛选中的持久任务记录？此操作不可撤销。",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return 0
        removed = self._task_center.clear_filtered(self._matches_visible_filter)
        self.refresh()
        return removed

    def clear_all(self):
        reply = QtWidgets.QMessageBox.question(
            self,
            "清空全部历史",
            "删除全部持久任务历史？正在运行的任务不受影响，"
            "此操作不可撤销。",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return 0
        removed = self._task_center.clear_all_persistent()
        self.refresh()
        return removed


__all__ = ["TaskResultDock"]
