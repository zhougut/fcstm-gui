import json
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from enum import Enum

from PyQt5 import QtCore, QtWidgets

from app.application.diagnostics import DiagnosticQuery, DiagnosticSourceKind


class DiagnosticsPanel(QtWidgets.QWidget):
    locate_requested = QtCore.pyqtSignal(object)
    suggested_fix_requested = QtCore.pyqtSignal(object)
    check_requested = QtCore.pyqtSignal()

    COLUMN_SEVERITY = 0
    COLUMN_SOURCE = 1
    COLUMN_CODE = 2
    COLUMN_MESSAGE = 3
    COLUMN_LOCATION = 4
    COLUMN_ACTION = 5

    def __init__(self, parent=None, redactor=None):
        super().__init__(parent)
        self._report = None
        self._items = ()
        self._redactor = redactor or (lambda value: value)

        self.setObjectName("diagnostics_panel")
        self.setAccessibleName("诊断面板")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        filter_row = QtWidgets.QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(filter_row)

        self.severity_filter = QtWidgets.QComboBox(self)
        self.severity_filter.setObjectName("diagnostics_severity_filter")
        self.severity_filter.setAccessibleName("诊断等级筛选")
        self.severity_filter.setToolTip("按诊断等级筛选")
        self.severity_filter.addItem("全部等级", "")
        for severity in ("error", "warning", "info"):
            self.severity_filter.addItem(severity, severity)
        filter_row.addWidget(self.severity_filter)

        self.source_filter = QtWidgets.QComboBox(self)
        self.source_filter.setObjectName("diagnostics_source_filter")
        self.source_filter.setAccessibleName("诊断来源筛选")
        self.source_filter.setToolTip("按诊断来源筛选")
        self.source_filter.addItem("全部来源", "")
        for source_kind in DiagnosticSourceKind:
            self.source_filter.addItem(source_kind.value, source_kind.value)
        filter_row.addWidget(self.source_filter)

        self.search_edit = QtWidgets.QLineEdit(self)
        self.search_edit.setObjectName("diagnostics_search_edit")
        self.search_edit.setAccessibleName("搜索诊断")
        self.search_edit.setPlaceholderText("搜索消息、代码、来源、引用")
        self.search_edit.setToolTip("搜索诊断消息、代码、来源 URI 与引用字段")
        filter_row.addWidget(self.search_edit, 1)

        self.clear_search_button = QtWidgets.QPushButton("清空", self)
        self.clear_search_button.setObjectName("diagnostics_clear_search_button")
        self.clear_search_button.setAccessibleName("清空诊断搜索")
        self.clear_search_button.setToolTip("清空搜索条件")
        filter_row.addWidget(self.clear_search_button)

        self.check_button = QtWidgets.QPushButton("运行检查", self)
        self.check_button.setObjectName("diagnostics_check_button")
        self.check_button.setAccessibleName("运行模型检查")
        self.check_button.setToolTip("手动检查当前版本的状态机")
        self.check_button.setEnabled(False)
        filter_row.addWidget(self.check_button)

        self.table = QtWidgets.QTableWidget(self)
        self.table.setObjectName("diagnostics_table")
        self.table.setAccessibleName("诊断列表")
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ("等级", "来源", "代码", "消息", "位置", "操作")
        )
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(
            self.COLUMN_MESSAGE, QtWidgets.QHeaderView.Stretch
        )
        for column in (
            self.COLUMN_SEVERITY,
            self.COLUMN_SOURCE,
            self.COLUMN_CODE,
            self.COLUMN_LOCATION,
            self.COLUMN_ACTION,
        ):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QtWidgets.QHeaderView.ResizeToContents
            )
        layout.addWidget(self.table, 2)

        self.detail = QtWidgets.QPlainTextEdit(self)
        self.detail.setObjectName("diagnostics_detail")
        self.detail.setAccessibleName("诊断详情")
        self.detail.setToolTip("所选诊断的原始详情")
        self.detail.setReadOnly(True)
        layout.addWidget(self.detail, 1)

        self.suggested_fix_button = QtWidgets.QPushButton(
            "预览并应用建议修复", self
        )
        self.suggested_fix_button.setObjectName(
            "diagnostics_suggested_fix_button"
        )
        self.suggested_fix_button.setAccessibleName("预览并应用建议修复")
        self.suggested_fix_button.setToolTip(
            "预览上游诊断提供的修复，并在确认后重新校验文档"
        )
        self.suggested_fix_button.setVisible(False)
        self.suggested_fix_button.clicked.connect(
            self._request_suggested_fix
        )
        layout.addWidget(self.suggested_fix_button)

        self.severity_filter.currentIndexChanged.connect(self._refresh)
        self.source_filter.currentIndexChanged.connect(self._refresh)
        self.search_edit.textChanged.connect(self._refresh)
        self.clear_search_button.clicked.connect(self.search_edit.clear)
        self.check_button.clicked.connect(self.check_requested)
        self.table.itemSelectionChanged.connect(self._update_detail)
        self.table.cellDoubleClicked.connect(self._locate_row)

    def set_check_enabled(self, enabled):
        self.check_button.setEnabled(bool(enabled))

    @property
    def selected_item(self):
        row = self.table.currentRow()
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    def set_report(self, report, source_revision, dependency_fingerprint):
        if report is None:
            self._report = None
        elif report.matches(source_revision, dependency_fingerprint):
            self._report = report
        else:
            self._report = None
        self._refresh()

    def clear(self):
        self.set_report(None, 0, None)

    def set_redactor(self, redactor):
        self._redactor = redactor or (lambda value: value)
        self._refresh()

    def _query(self):
        severity = self.severity_filter.currentData()
        source = self.source_filter.currentData()
        source_kinds = ()
        if source:
            source_kinds = (DiagnosticSourceKind(source),)
        return DiagnosticQuery(
            severities=(str(severity),) if severity else (),
            source_kinds=source_kinds,
            search=self.search_edit.text(),
        )

    def _refresh(self):
        if self._report is None:
            self._items = ()
        else:
            self._items = self._report.select(self._query())
        self.table.setRowCount(len(self._items))
        for row, item in enumerate(self._items):
            values = (
                item.severity or "",
                item.source_kind.value,
                item.code or "",
                self._display(item.message),
                self._format_location(item),
            )
            for column, value in enumerate(values):
                cell = QtWidgets.QTableWidgetItem(value)
                cell.setToolTip(value)
                self.table.setItem(row, column, cell)
            self.table.setCellWidget(row, self.COLUMN_ACTION, self._action_button(item))
        if self._items:
            self.table.setCurrentCell(0, 0)
            self.table.selectRow(0)
        self._update_detail()

    def _action_button(self, item):
        button = QtWidgets.QPushButton("定位", self.table)
        button.setObjectName("diagnostics_locate_button")
        button.setAccessibleName("定位诊断")
        button.setToolTip("跳转到诊断位置")
        button.setEnabled(self._is_locatable(item))
        button.clicked.connect(lambda checked=False, selected=item: self._locate(selected))
        return button

    @staticmethod
    def _is_locatable(item):
        return item is not None and item.span is not None

    @staticmethod
    def _format_location(item):
        span = item.span
        if span is None:
            return ""
        value = "{}:{}".format(span.line, span.column + 1)
        if span.end_line is not None and span.end_column is not None:
            value += "-{}:{}".format(span.end_line, span.end_column + 1)
        return value

    def _update_detail(self):
        item = self.selected_item
        if item is None:
            self.detail.clear()
            self.suggested_fix_button.setVisible(False)
            return
        lines = [
            "source: {}".format(item.source_kind.value),
            "message: {}".format(self._display(item.message)),
            "source_uri: {}".format(self._display(item.source_uri)),
            "版本：{}".format(item.source_revision),
            "provenance: {}".format(item.provenance),
        ]
        if item.severity is not None:
            lines.insert(0, "severity: {}".format(item.severity))
        if item.code is not None:
            insert_at = 1 if item.severity is not None else 0
            lines.insert(insert_at, "code: {}".format(item.code))
        if item.span is not None:
            lines.append("location: {}".format(self._format_location(item)))
        if item.raw_message is not None:
            lines.append("raw_message: {}".format(self._display(item.raw_message)))
        if item.offending_symbol_text is not None:
            lines.append("offending_symbol_text: {}".format(item.offending_symbol_text))
        if item.refs is not None:
            lines.append(
                "refs: {}".format(
                    json.dumps(
                        _json_value(self._redact_value(item.refs)),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            )
        if item.suggested_fix is not None:
            lines.append("suggested_fix: {}".format(item.suggested_fix.kind))
        self.detail.setPlainText("\n".join(lines))
        has_materialized_fix = self._has_materialized_fix(item)
        self.suggested_fix_button.setVisible(has_materialized_fix)
        self.suggested_fix_button.setEnabled(has_materialized_fix)

    def _display(self, value):
        return self._redactor(str(value))

    def _redact_value(self, value):
        if isinstance(value, Mapping):
            return {
                self._display(key): self._redact_value(item)
                for key, item in value.items()
            }
        if isinstance(value, (tuple, list, set, frozenset)):
            return [self._redact_value(item) for item in value]
        if isinstance(value, str):
            return self._display(value)
        return value

    def _locate_row(self, row, column):
        if 0 <= row < len(self._items):
            self._locate(self._items[row])

    def _locate(self, item):
        if self._is_locatable(item):
            self.locate_requested.emit(item)

    def _request_suggested_fix(self):
        item = self.selected_item
        if self._has_materialized_fix(item):
            self.suggested_fix_requested.emit(item)

    @staticmethod
    def _has_materialized_fix(item):
        if item is None or item.suggested_fix is None or not isinstance(
            item.refs, Mapping
        ):
            return False
        payload = item.refs.get("suggested_fix")
        if not isinstance(payload, Mapping):
            return False
        anchor = payload.get("anchor")
        return (
            all(
                isinstance(payload.get(field), str)
                for field in ("kind", "target", "text", "rationale")
            )
            and isinstance(anchor, Mapping)
            and isinstance(anchor.get("ref"), str)
        )


__all__ = ["DiagnosticsPanel"]


def _json_value(value):
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_json_value(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
