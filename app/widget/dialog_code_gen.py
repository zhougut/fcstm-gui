"""Five-template code generation dialog."""

from __future__ import unicode_literals

from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets


class DialogCodeGen(QtWidgets.QDialog):
    generate_requested = QtCore.pyqtSignal(object)
    cancel_requested = QtCore.pyqtSignal()

    LANGUAGE_LABELS = (("全部", ""), ("Python", "python"), ("C", "c"), ("C++", "cpp"))

    def __init__(self, parent, templates, state_manager=None, model=None):
        super().__init__(parent)
        self.templates = tuple(templates)
        self.state_manager = state_manager
        self.model = model
        self._busy = False
        self._build_ui()
        self._connect_signals()
        self._filter_templates()

    def _build_ui(self):
        self.setObjectName("code_generation_dialog")
        self.setWindowTitle("代码生成")
        self.resize(760, 560)
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.language_combo = QtWidgets.QComboBox(self)
        self.language_combo.setObjectName("generation_language_combo")
        for label, value in self.LANGUAGE_LABELS:
            self.language_combo.addItem(label, value)
        self.template_combo = QtWidgets.QComboBox(self)
        self.template_combo.setObjectName("generation_template_combo")
        self.template_mode_combo = QtWidgets.QComboBox(self)
        self.template_mode_combo.setObjectName("generation_template_mode_combo")
        self.template_mode_combo.addItems(["内置模板", "自定义模板"])
        self.custom_template_edit = QtWidgets.QLineEdit(self)
        self.custom_template_edit.setObjectName("generation_custom_template_edit")
        self.custom_template_button = self._button("选择", "generation_custom_template_button")
        custom_row = QtWidgets.QHBoxLayout()
        custom_row.addWidget(self.custom_template_edit, 1)
        custom_row.addWidget(self.custom_template_button)
        self.output_edit = QtWidgets.QLineEdit(self)
        self.output_edit.setObjectName("generation_output_edit")
        self.output_button = self._button("选择", "generation_output_button")
        output_row = QtWidgets.QHBoxLayout()
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(self.output_button)
        self.overwrite_check = QtWidgets.QCheckBox("替换已有输出目录", self)
        self.overwrite_check.setObjectName("generation_overwrite_check")
        form.addRow("目标语言", self.language_combo)
        form.addRow("模板来源", self.template_mode_combo)
        form.addRow("内置模板", self.template_combo)
        form.addRow("自定义模板目录", custom_row)
        form.addRow("输出目录", output_row)
        form.addRow("覆盖策略", self.overwrite_check)
        layout.addLayout(form)
        self.description_edit = QtWidgets.QPlainTextEdit(self)
        self.description_edit.setObjectName("generation_template_description")
        self.description_edit.setReadOnly(True)
        self.description_edit.setMaximumHeight(90)
        layout.addWidget(self.description_edit)
        self.status_label = QtWidgets.QLabel("ready", self)
        self.status_label.setObjectName("generation_status_label")
        layout.addWidget(self.status_label)
        self.progress_bar = QtWidgets.QProgressBar(self)
        self.progress_bar.setObjectName("generation_progress_bar")
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)
        self.result_table = QtWidgets.QTableWidget(0, 3, self)
        self.result_table.setObjectName("generation_result_table")
        self.result_table.setHorizontalHeaderLabels(["文件", "大小", "SHA-256"])
        self.result_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.result_table, 1)
        buttons = QtWidgets.QHBoxLayout()
        self.open_directory_button = self._button("打开目录", "generation_open_directory_button")
        self.generate_button = self._button("开始生成", "generation_start_button")
        self.cancel_button = self._button("停止", "generation_cancel_button")
        self.close_button = self._button("关闭", "generation_close_button")
        buttons.addWidget(self.open_directory_button)
        buttons.addStretch(1)
        buttons.addWidget(self.generate_button)
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
        self.language_combo.currentIndexChanged.connect(self._filter_templates)
        self.template_combo.currentIndexChanged.connect(self._show_template_info)
        self.template_mode_combo.currentIndexChanged.connect(self._update_actions)
        self.custom_template_button.clicked.connect(self._choose_custom_template)
        self.output_button.clicked.connect(self._choose_output)
        self.generate_button.clicked.connect(self._request_generation)
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.close_button.clicked.connect(self.reject)
        self.open_directory_button.clicked.connect(self._open_output_directory)

    def _filter_templates(self):
        language = self.language_combo.currentData() or ""
        current = self.template_combo.currentData()
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        for item in self.templates:
            if not language or item.language == language:
                self.template_combo.addItem("{} ({})".format(item.title, item.name), item.name)
        index = self.template_combo.findData(current)
        if index >= 0:
            self.template_combo.setCurrentIndex(index)
        self.template_combo.blockSignals(False)
        self._show_template_info()

    def _show_template_info(self):
        name = self.template_combo.currentData()
        descriptor = next((item for item in self.templates if item.name == name), None)
        self.description_edit.setPlainText(
            "" if descriptor is None else "{}\n{}".format(descriptor.title, descriptor.description)
        )

    def _choose_custom_template(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "选择自定义模板目录")
        if path:
            self.custom_template_edit.setText(path)

    def _choose_output(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "选择输出目录")
        if path:
            self.output_edit.setText(path)

    def _request_generation(self):
        custom = self.template_mode_combo.currentIndex() == 1
        request = {
            "template_name": None if custom else self.template_combo.currentData(),
            "custom_template_dir": self.custom_template_edit.text().strip() if custom else None,
            "output_dir": self.output_edit.text().strip(),
            "overwrite": self.overwrite_check.isChecked(),
        }
        if not request["output_dir"]:
            self.show_error("请选择输出目录")
            return
        if custom and not request["custom_template_dir"]:
            self.show_error("请选择自定义模板目录")
            return
        if request["overwrite"] and Path(request["output_dir"]).exists():
            reply = QtWidgets.QMessageBox.question(
                self,
                "确认替换",
                "将原子替换已有输出目录，继续吗？",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if reply != QtWidgets.QMessageBox.Yes:
                return
        self.generate_requested.emit(request)

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
        self.status_label.setText("生成完成：{} 个文件".format(len(result.files)))
        self.output_edit.setText(result.output_dir)
        self.result_table.setRowCount(0)
        for item in result.files:
            row = self.result_table.rowCount()
            self.result_table.insertRow(row)
            for column, value in enumerate((item.relative_path, item.size, item.sha256)):
                cell = QtWidgets.QTableWidgetItem(str(value))
                cell.setToolTip(str(value))
                self.result_table.setItem(row, column, cell)
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
        self.status_label.setText("cancelled，既有输出未修改")
        self._update_actions()

    def _open_output_directory(self):
        path = self.output_edit.text().strip()
        if path:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))

    def _update_actions(self):
        custom = self.template_mode_combo.currentIndex() == 1
        ready = not self._busy
        self.language_combo.setEnabled(ready and not custom)
        self.template_combo.setEnabled(ready and not custom)
        self.custom_template_edit.setEnabled(ready and custom)
        self.custom_template_button.setEnabled(ready and custom)
        self.output_edit.setEnabled(ready)
        self.output_button.setEnabled(ready)
        self.overwrite_check.setEnabled(ready)
        self.generate_button.setEnabled(ready)
        self.cancel_button.setEnabled(self._busy)
        self.close_button.setEnabled(not self._busy)
        self.open_directory_button.setEnabled(ready and bool(self.output_edit.text()))

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
