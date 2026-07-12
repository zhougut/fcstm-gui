"""Ordinary simulation workbench view."""

from __future__ import unicode_literals

import json

from PyQt5 import QtCore, QtWidgets


class SimulationWorkspace(QtWidgets.QWidget):
    initialize_requested = QtCore.pyqtSignal(object)
    cycle_requested = QtCore.pyqtSignal(object)
    run_requested = QtCore.pyqtSignal(object)
    pause_requested = QtCore.pyqtSignal()
    reset_requested = QtCore.pyqtSignal()
    cancel_requested = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ordinary_simulation_panel")
        self._ready = False
        self._busy = False
        self._pausable = False
        self._paused = False
        self._build_ui()
        self._connect_signals()
        self.set_document_available(False)

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        status_row = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("未初始化", self)
        self.status_label.setObjectName("simulation_status_label")
        self.stamp_label = QtWidgets.QLabel("无有效文档", self)
        self.stamp_label.setObjectName("simulation_stamp_label")
        self.stamp_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByKeyboard)
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        status_row.addWidget(self.stamp_label)
        layout.addLayout(status_row)

        form = QtWidgets.QGridLayout()
        self.initial_state_edit = QtWidgets.QLineEdit(self)
        self.initial_state_edit.setObjectName("simulation_initial_state_edit")
        self.initial_state_edit.setPlaceholderText("留空使用模型初始状态，例如 Root.A")
        self.initial_variables_edit = QtWidgets.QLineEdit(self)
        self.initial_variables_edit.setObjectName("simulation_initial_variables_edit")
        self.initial_variables_edit.setText("{}")
        self.initial_variables_edit.setPlaceholderText('{"count": 0}')
        self.event_edit = QtWidgets.QLineEdit(self)
        self.event_edit.setObjectName("simulation_event_edit")
        self.event_edit.setPlaceholderText("同一 cycle 的事件用逗号分隔")
        self.cycle_count = QtWidgets.QSpinBox(self)
        self.cycle_count.setObjectName("simulation_cycle_count")
        self.cycle_count.setRange(1, 10000)
        self.cycle_count.setValue(10)
        form.addWidget(QtWidgets.QLabel("初始状态", self), 0, 0)
        form.addWidget(self.initial_state_edit, 0, 1)
        form.addWidget(QtWidgets.QLabel("初始变量 JSON", self), 0, 2)
        form.addWidget(self.initial_variables_edit, 0, 3)
        form.addWidget(QtWidgets.QLabel("输入事件", self), 1, 0)
        form.addWidget(self.event_edit, 1, 1)
        form.addWidget(QtWidgets.QLabel("连续 cycle 上限", self), 1, 2)
        form.addWidget(self.cycle_count, 1, 3)
        form.setColumnStretch(1, 3)
        form.setColumnStretch(3, 2)
        layout.addLayout(form)

        controls = QtWidgets.QHBoxLayout()
        controls.setSpacing(0)
        self.initialize_button = self._button("初始化", "simulation_initialize_button")
        self.cycle_button = self._button("单步", "simulation_cycle_button")
        self.run_button = self._button("连续运行", "simulation_run_button")
        self.pause_button = self._button("暂停", "simulation_pause_button")
        self.reset_button = self._button("重置", "simulation_reset_button")
        self.cancel_button = self._button("停止", "simulation_cancel_button")
        buttons = (
            self.initialize_button,
            self.cycle_button,
            self.run_button,
            self.pause_button,
            self.reset_button,
            self.cancel_button,
        )
        for index, button in enumerate(buttons):
            controls.addWidget(button)
            if index + 1 < len(buttons):
                controls.addSpacing(8)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.snapshot_label = QtWidgets.QLabel("状态: - | cycle: 0 | ended: false", self)
        self.snapshot_label.setObjectName("simulation_snapshot_label")
        self.snapshot_label.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse | QtCore.Qt.TextSelectableByKeyboard
        )
        layout.addWidget(self.snapshot_label)

        self.transcript_table = QtWidgets.QTableWidget(0, 7, self)
        self.transcript_table.setObjectName("simulation_transcript_table")
        self.transcript_table.setHorizontalHeaderLabels(
            ["cycle", "状态", "输入事件", "已消费", "未消费", "变量", "结果"]
        )
        self.transcript_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.transcript_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.transcript_table.setAlternatingRowColors(True)
        self.transcript_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeToContents
        )
        self.transcript_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.transcript_table, 1)

    def _button(self, text, name):
        button = QtWidgets.QPushButton(text, self)
        button.setObjectName(name)
        button.setAccessibleName(text)
        button.setToolTip(text)
        button.setMinimumWidth(88)
        return button

    def _connect_signals(self):
        self.initialize_button.clicked.connect(self._request_initialize)
        self.cycle_button.clicked.connect(
            lambda: self.cycle_requested.emit(self.event_values())
        )
        self.run_button.clicked.connect(
            lambda: self.run_requested.emit(
                {"max_cycles": self.cycle_count.value(), "events": self.event_values()}
            )
        )
        self.pause_button.clicked.connect(self.pause_requested)
        self.reset_button.clicked.connect(self.reset_requested)
        self.cancel_button.clicked.connect(self.cancel_requested)

    def _request_initialize(self):
        try:
            variables = json.loads(self.initial_variables_edit.text() or "{}")
            if not isinstance(variables, dict):
                raise ValueError("初始变量必须是 JSON object")
        except (TypeError, ValueError) as error:
            self.show_error(str(error))
            return
        state = self.initial_state_edit.text().strip() or None
        self.initialize_requested.emit({"state": state, "variables": variables})

    def event_values(self):
        return tuple(
            item.strip() for item in self.event_edit.text().split(",") if item.strip()
        )

    def set_document_available(self, available, revision=None, fingerprint=None):
        self._document_available = bool(available)
        if available:
            short_fingerprint = (fingerprint or "")[:12] or "-"
            self.stamp_label.setText(
                "版本 {} | 依赖 {}".format(revision, short_fingerprint)
            )
        else:
            self.stamp_label.setText("当前版本无有效快照")
            self._ready = False
        self._update_actions()

    def set_busy(self, busy, status=None, pausable=False):
        self._busy = bool(busy)
        self._pausable = bool(busy and pausable)
        if busy:
            self._paused = False
        if status:
            self.status_label.setText(status)
        self._update_actions()

    def set_initialized(self, snapshot):
        self._ready = True
        self._busy = False
        self._pausable = False
        self._paused = False
        self.status_label.setText("就绪")
        self.transcript_table.setRowCount(0)
        self.present_snapshot(snapshot)
        self._update_actions()

    def present_snapshot(self, snapshot):
        state = ".".join(snapshot.state_path) if snapshot.state_path else "<ended>"
        self.snapshot_label.setText(
            "状态: {} | cycle: {} | ended: {} | 变量: {}".format(
                state,
                snapshot.cycle,
                str(bool(snapshot.ended)).lower(),
                json.dumps(snapshot.vars, ensure_ascii=False, sort_keys=True),
            )
        )

    def append_cycles(self, cycles):
        for cycle in cycles:
            row = self.transcript_table.rowCount()
            self.transcript_table.insertRow(row)
            state = ".".join(cycle.snapshot.state_path) or "<ended>"
            error = cycle.error
            result = "成功" if error is None else "{}: {}".format(error.type, error.message)
            values = (
                cycle.snapshot.cycle,
                state,
                ", ".join(cycle.input_events),
                ", ".join(cycle.consumed_events),
                ", ".join(cycle.unconsumed_events),
                json.dumps(cycle.snapshot.vars, ensure_ascii=False, sort_keys=True),
                result,
            )
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.transcript_table.setItem(row, column, item)
            self.present_snapshot(cycle.snapshot)
        self._busy = False
        self._pausable = False
        self._paused = False
        if cycles:
            last = cycles[-1]
            if last.error is not None:
                self.status_label.setText("失败")
            elif last.snapshot.ended:
                self.status_label.setText("已结束")
            else:
                self.status_label.setText("就绪")
        self._update_actions()

    def show_pause_requested(self):
        self._pausable = False
        self.status_label.setText("正在暂停")
        self._update_actions()

    def show_paused(self):
        self._busy = False
        self._pausable = False
        self._paused = True
        self.status_label.setText("已暂停")
        self._update_actions()

    def show_cancelled(self):
        self._busy = False
        self._pausable = False
        self._paused = False
        self.status_label.setText("已取消，已保留完成的周期")
        self._update_actions()

    def show_error(self, message):
        self._busy = False
        self._pausable = False
        self._paused = False
        self.status_label.setText("失败：" + str(message))
        self.status_label.setToolTip(str(message))
        self._update_actions()

    def invalidate(self):
        self._ready = False
        self._busy = False
        self._pausable = False
        self._paused = False
        self.status_label.setText("已失效，需要重新初始化")
        self._update_actions()

    def _update_actions(self):
        self.initialize_button.setEnabled(self._document_available and not self._busy)
        self.cycle_button.setEnabled(self._ready and not self._busy)
        self.run_button.setEnabled(self._ready and not self._busy)
        self.run_button.setText("继续运行" if self._paused else "连续运行")
        self.pause_button.setEnabled(self._busy and self._pausable)
        self.reset_button.setEnabled(self._ready and not self._busy)
        self.cancel_button.setEnabled(self._busy)
