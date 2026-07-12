"""Unified export dialog."""

from __future__ import unicode_literals

from pathlib import Path

from PyQt5 import QtCore, QtWidgets


class DialogExport(QtWidgets.QDialog):
    export_requested = QtCore.pyqtSignal(object)
    cancel_requested = QtCore.pyqtSignal()

    KIND_LABELS = (
        ("FCSTM 源码", "fcstm", "fcstm"),
        ("Word 文档", "docx", "docx"),
        ("Excel 工作簿", "xlsx", "xlsx"),
        ("PlantUML 源码", "plantuml", "puml"),
        ("PNG 状态图", "png", "png"),
        ("SVG 状态图", "svg", "svg"),
        ("PDF 状态图", "pdf", "pdf"),
        ("Inspect JSON", "inspect-json", "json"),
        ("动态验证 JSON", "dynamic-json", "json"),
    )
    KIND_SUFFIXES = {kind: suffix for _label, kind, suffix in KIND_LABELS}

    def __init__(self, parent=None, dynamic_available=False):
        super().__init__(parent)
        self._busy = False
        self.dynamic_available = bool(dynamic_available)
        self._build_ui()
        self._connect_signals()
        self._update_actions()

    def _build_ui(self):
        self.setObjectName("unified_export_dialog")
        self.setWindowTitle("统一导出")
        self.resize(680, 250)
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.kind_combo = QtWidgets.QComboBox(self)
        self.kind_combo.setObjectName("export_kind_combo")
        for label, kind, suffix in self.KIND_LABELS:
            self.kind_combo.addItem(label, kind)
        dynamic_index = self.kind_combo.findData("dynamic-json")
        if dynamic_index >= 0 and not self.dynamic_available:
            self.kind_combo.model().item(dynamic_index).setEnabled(False)
        self.path_edit = QtWidgets.QLineEdit(self)
        self.path_edit.setObjectName("export_path_edit")
        self.path_button = self._button("选择", "export_path_button")
        path_row = QtWidgets.QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(self.path_button)
        self.overwrite_check = QtWidgets.QCheckBox("替换已有文件", self)
        self.overwrite_check.setObjectName("export_overwrite_check")
        form.addRow("导出类型", self.kind_combo)
        form.addRow("目标文件", path_row)
        form.addRow("覆盖策略", self.overwrite_check)
        layout.addLayout(form)
        self.status_label = QtWidgets.QLabel("ready", self)
        self.status_label.setObjectName("export_status_label")
        layout.addWidget(self.status_label)
        self.progress_bar = QtWidgets.QProgressBar(self)
        self.progress_bar.setObjectName("export_progress_bar")
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        self.start_button = self._button("开始导出", "export_start_button")
        self.cancel_button = self._button("停止", "export_cancel_button")
        self.close_button = self._button("关闭", "export_close_button")
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

    def _button(self, text, name):
        button = QtWidgets.QPushButton(text, self)
        button.setObjectName(name)
        button.setAccessibleName(text)
        button.setToolTip(text)
        return button

    def _connect_signals(self):
        self.kind_combo.currentIndexChanged.connect(self._kind_changed)
        self.path_button.clicked.connect(self._choose_path)
        self.start_button.clicked.connect(self._request_export)
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.close_button.clicked.connect(self.reject)

    def _kind_changed(self):
        self.path_edit.clear()

    def _choose_path(self):
        kind = self.kind_combo.currentData()
        suffix = self.KIND_SUFFIXES[kind]
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "选择导出文件", "artifact." + suffix, "所有文件 (*)"
        )
        if path:
            self.path_edit.setText(path)

    def _request_export(self):
        path = self.path_edit.text().strip()
        if not path:
            self.show_error("请选择目标文件")
            return
        kind = self.kind_combo.currentData()
        suffix = self.KIND_SUFFIXES[kind]
        if not path.lower().endswith("." + suffix):
            path += "." + suffix
            self.path_edit.setText(path)
        if self.overwrite_check.isChecked() and Path(path).exists():
            reply = QtWidgets.QMessageBox.question(
                self,
                "确认替换",
                "将原子替换已有文件，继续吗？",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if reply != QtWidgets.QMessageBox.Yes:
                return
        self.export_requested.emit(
            {"kind": kind, "path": path, "overwrite": self.overwrite_check.isChecked()}
        )

    def set_busy(self, busy, status=None):
        self._busy = bool(busy)
        if status:
            self.status_label.setText(status)
        if self._busy:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
        self._update_actions()

    def present_result(self, result):
        self._busy = False
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.path_edit.setText(result.path)
        self.status_label.setText("导出完成：{} bytes".format(result.size))
        self._update_actions()

    def show_error(self, message):
        self._busy = False
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.status_label.setText("failed: " + str(message))
        self.status_label.setToolTip(str(message))
        self._update_actions()

    def show_cancelled(self):
        self._busy = False
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.status_label.setText("cancelled，既有文件未修改")
        self._update_actions()

    def _update_actions(self):
        ready = not self._busy
        self.kind_combo.setEnabled(ready)
        self.path_edit.setEnabled(ready)
        self.path_button.setEnabled(ready)
        self.overwrite_check.setEnabled(ready)
        self.start_button.setEnabled(ready)
        self.cancel_button.setEnabled(self._busy)
        self.close_button.setEnabled(ready)

    def reject(self):
        if self._busy:
            self.cancel_requested.emit()
            return
        super().reject()

    def closeEvent(self, event):
        if self._busy:
            self.cancel_requested.emit()
            event.ignore()
            return
        super().closeEvent(event)
