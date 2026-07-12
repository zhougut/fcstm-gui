"""Expected/actual dynamic validation workbench view."""

from __future__ import unicode_literals

import json

from PyQt5 import QtCore, QtWidgets


class DynamicValidationWorkspace(QtWidgets.QWidget):
    run_requested = QtCore.pyqtSignal(object)
    cancel_requested = QtCore.pyqtSignal()
    export_requested = QtCore.pyqtSignal()

    def __init__(self, case_ids, parent=None):
        super().__init__(parent)
        self.setObjectName("dynamic_validation_panel")
        self._document_available = False
        self._busy = False
        self._report = None
        self._build_ui(case_ids)
        self._connect_signals()
        self._update_actions()

    def _build_ui(self, case_ids):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        source_row = QtWidgets.QHBoxLayout()
        self.scenario_edit = QtWidgets.QLineEdit(self)
        self.scenario_edit.setObjectName("dynamic_scenario_edit")
        self.scenario_edit.setReadOnly(True)
        self.scenario_edit.setPlaceholderText("选择用户 JSON 场景，或运行内置验收用例")
        self.browse_button = self._button("选择场景", "dynamic_browse_button")
        source_row.addWidget(self.scenario_edit, 1)
        source_row.addWidget(self.browse_button)
        layout.addLayout(source_row)

        controls = QtWidgets.QHBoxLayout()
        self.case_combo = QtWidgets.QComboBox(self)
        self.case_combo.setObjectName("dynamic_case_combo")
        self.case_combo.addItems(list(case_ids))
        self.run_user_button = self._button("运行用户场景", "dynamic_run_user_button")
        self.run_case_button = self._button("运行内置用例", "dynamic_run_case_button")
        self.run_suite_button = self._button("运行全部验收", "dynamic_run_suite_button")
        self.cancel_button = self._button("停止", "dynamic_cancel_button")
        self.export_button = self._button("导出报告", "dynamic_export_button")
        controls.addWidget(self.case_combo, 1)
        for button in (
            self.run_user_button,
            self.run_case_button,
            self.run_suite_button,
            self.cancel_button,
            self.export_button,
        ):
            controls.addWidget(button)
        layout.addLayout(controls)

        self.status_label = QtWidgets.QLabel("draft", self)
        self.status_label.setObjectName("dynamic_status_label")
        self.status_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByKeyboard)
        layout.addWidget(self.status_label)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical, self)
        self.result_table = QtWidgets.QTableWidget(0, 7, splitter)
        self.result_table.setObjectName("dynamic_result_table")
        self.result_table.setHorizontalHeaderLabels(
            ["用例", "step", "状态", "输入", "expected", "actual", "diff"]
        )
        self.result_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.result_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeToContents
        )
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.details_edit = QtWidgets.QPlainTextEdit(splitter)
        self.details_edit.setObjectName("dynamic_report_details")
        self.details_edit.setReadOnly(True)
        self.details_edit.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        splitter.addWidget(self.result_table)
        splitter.addWidget(self.details_edit)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

    def _button(self, text, name):
        button = QtWidgets.QPushButton(text, self)
        button.setObjectName(name)
        button.setAccessibleName(text)
        button.setToolTip(text)
        return button

    def _connect_signals(self):
        self.browse_button.clicked.connect(self._browse)
        self.run_user_button.clicked.connect(
            lambda: self.run_requested.emit(
                {"mode": "user", "path": self.scenario_edit.text()}
            )
        )
        self.run_case_button.clicked.connect(
            lambda: self.run_requested.emit(
                {"mode": "case", "case_id": self.case_combo.currentText()}
            )
        )
        self.run_suite_button.clicked.connect(
            lambda: self.run_requested.emit({"mode": "suite"})
        )
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.export_button.clicked.connect(self.export_requested)
        self.result_table.itemSelectionChanged.connect(self._show_selected_step)

    def _browse(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择动态验证场景", "", "JSON 场景 (*.json);;所有文件 (*)"
        )
        if path:
            self.scenario_edit.setText(path)
            self.scenario_edit.setToolTip(path)
            self._update_actions()

    @property
    def report(self):
        return self._report

    def set_document_available(self, available):
        self._document_available = bool(available)
        if not available:
            self.status_label.setText("当前 revision 无有效快照")
        elif self._report is None:
            self.status_label.setText("draft")
        self._update_actions()

    def set_busy(self, busy, status=None):
        self._busy = bool(busy)
        if status:
            self.status_label.setText(status)
        self._update_actions()

    def present_report(self, report, provenance=None):
        self._busy = False
        self._report = report
        payload = report.to_json_dict()
        if provenance is not None:
            payload = {
                "schema": "fcstm-gui.dynamic-validation-result-bundle",
                "version": 1,
                "provenance": provenance.to_json_dict(),
                "report": payload,
            }
        self._report_payload = payload
        self.details_edit.setPlainText(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
        )
        self.status_label.setText(report.status)
        self.result_table.setRowCount(0)
        cases = report.cases if hasattr(report, "cases") else (report,)
        for case in cases:
            if not case.steps:
                self._append_row(case.case_id, "-", case.status, (), {}, {}, [])
            for step in case.steps:
                self._append_row(
                    case.case_id,
                    step.index,
                    step.status,
                    step.input_events,
                    step.expected,
                    step.actual,
                    step.diffs,
                )
        self._update_actions()

    def _append_row(self, case_id, index, status, events, expected, actual, diffs):
        row = self.result_table.rowCount()
        self.result_table.insertRow(row)
        values = (
            case_id,
            index,
            status,
            ", ".join(events),
            json.dumps(expected, ensure_ascii=False, sort_keys=True),
            json.dumps(actual, ensure_ascii=False, sort_keys=True),
            json.dumps(diffs, ensure_ascii=False, sort_keys=True),
        )
        for column, value in enumerate(values):
            item = QtWidgets.QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            item.setData(QtCore.Qt.UserRole, {"expected": expected, "actual": actual, "diffs": diffs})
            self.result_table.setItem(row, column, item)

    def _show_selected_step(self):
        items = self.result_table.selectedItems()
        if not items:
            return
        payload = items[0].data(QtCore.Qt.UserRole)
        self.details_edit.setPlainText(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
        )

    def report_json(self):
        if self._report is None:
            return None
        return json.dumps(
            self._report_payload, ensure_ascii=False, sort_keys=True, indent=2
        ) + "\n"

    def show_cancelled(self):
        self._busy = False
        self.status_label.setText("cancelled，已保留完成的 step")
        self._update_actions()

    def show_error(self, message):
        self._busy = False
        self.status_label.setText("failed: " + str(message))
        self.status_label.setToolTip(str(message))
        self._update_actions()

    def _update_actions(self):
        ready = self._document_available and not self._busy
        self.browse_button.setEnabled(not self._busy)
        self.case_combo.setEnabled(ready)
        self.run_user_button.setEnabled(ready and bool(self.scenario_edit.text()))
        self.run_case_button.setEnabled(ready and self.case_combo.count() > 0)
        self.run_suite_button.setEnabled(ready)
        self.cancel_button.setEnabled(self._busy)
        self.export_button.setEnabled(not self._busy and self._report is not None)
