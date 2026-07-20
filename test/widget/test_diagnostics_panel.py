from PyQt5 import QtCore
from pyfcstm.utils.validate import ModelDiagnostic, ModelValidationError, Span

from app.application.diagnostics import (
    DiagnosticItem,
    DiagnosticReport,
    DiagnosticSourceKind,
    DiagnosticSpan,
    DiagnosticService,
    SuggestedFix,
)
from app.widget.diagnostics_panel import DiagnosticsPanel


SOURCE_URI = "file:///tmp/model.fcstm"


def _item(
    source_kind,
    message,
    severity=None,
    code=None,
    span=None,
    refs=None,
    revision=3,
    deps="deps-3",
    suggested_fix=None,
):
    return DiagnosticItem(
        source_kind=source_kind,
        source_uri=SOURCE_URI,
        code=code,
        severity=severity,
        message=message,
        span=span,
        refs=refs,
        suggested_fix=suggested_fix,
        source_revision=revision,
        dependency_fingerprint=deps,
        provenance="test.native",
    )


def _report(*items, revision=3, deps="deps-3"):
    return DiagnosticReport(revision, deps, tuple(items))


def test_diagnostics_panel_renders_missing_fields_as_empty_without_fabrication(qtbot):
    panel = DiagnosticsPanel()
    qtbot.addWidget(panel)
    syntax = _item(DiagnosticSourceKind.SYNTAX, "bad token")

    panel.set_report(_report(syntax), source_revision=3, dependency_fingerprint="deps-3")

    assert panel.table.rowCount() == 1
    assert panel.table.item(0, panel.COLUMN_SEVERITY).text() == ""
    assert panel.table.item(0, panel.COLUMN_SOURCE).text() == "syntax"
    assert panel.table.item(0, panel.COLUMN_CODE).text() == ""
    assert panel.table.item(0, panel.COLUMN_MESSAGE).text() == "bad token"
    assert panel.table.item(0, panel.COLUMN_LOCATION).text() == ""
    detail = panel.detail.toPlainText()
    assert "bad token" in detail
    assert "code:" not in detail
    assert "severity:" not in detail


def test_diagnostics_panel_filters_by_severity_source_and_search(qtbot):
    panel = DiagnosticsPanel()
    qtbot.addWidget(panel)
    model = _item(
        DiagnosticSourceKind.MODEL,
        "Unknown variable",
        severity="error",
        code="E_UNDEFINED_VAR",
        refs={"var_name": "CounterValue"},
    )
    inspect = _item(
        DiagnosticSourceKind.INSPECT,
        "dead guard",
        severity="warning",
        code="W_DEAD_GUARD",
    )
    panel.set_report(
        _report(model, inspect), source_revision=3, dependency_fingerprint="deps-3"
    )

    assert panel.table.rowCount() == 2
    panel.severity_filter.setCurrentText("error")
    assert panel.table.rowCount() == 1
    assert panel.table.item(0, panel.COLUMN_CODE).text() == "E_UNDEFINED_VAR"

    panel.source_filter.setCurrentText("model")
    panel.search_edit.setText("countervalue")
    assert panel.table.rowCount() == 1
    assert panel.selected_item is model

    panel.search_edit.setText("dead")
    assert panel.table.rowCount() == 0
    assert panel.empty_label.text() == "当前筛选条件下没有诊断"


def test_diagnostics_panel_empty_state_and_action_column_fit_compact_width(qtbot):
    panel = DiagnosticsPanel()
    qtbot.addWidget(panel)
    panel.resize(724, 560)
    panel.show()
    panel.clear("当前版本未发现问题")

    assert panel.empty_label.isVisibleTo(panel)
    assert panel.empty_label.text() == "当前版本未发现问题"

    item = _item(
        DiagnosticSourceKind.MODEL,
        "A long diagnostic message that should use the stretch column",
        severity="error",
        code="E_A_VERY_LONG_DIAGNOSTIC_CODE",
        span=DiagnosticSpan(8, 2),
    )
    panel.set_report(_report(item), source_revision=3, dependency_fingerprint="deps-3")
    qtbot.wait(10)

    action = panel.table.cellWidget(0, panel.COLUMN_ACTION)
    assert action.isVisibleTo(panel)
    assert panel.table.visualRect(panel.table.model().index(0, panel.COLUMN_ACTION)).right() <= (
        panel.table.viewport().width()
    )


def test_diagnostics_panel_emits_locate_signal_from_button_and_double_click(qtbot):
    panel = DiagnosticsPanel()
    qtbot.addWidget(panel)
    locatable = _item(
        DiagnosticSourceKind.MODEL,
        "missing target",
        severity="error",
        span=DiagnosticSpan(8, 2),
    )
    unlocated = _item(DiagnosticSourceKind.MODEL, "plain model error")
    panel.set_report(
        _report(locatable, unlocated),
        source_revision=3,
        dependency_fingerprint="deps-3",
    )

    button = panel.table.cellWidget(0, panel.COLUMN_ACTION)
    assert button.isEnabled()
    with qtbot.waitSignal(panel.locate_requested, timeout=1000) as emitted:
        qtbot.mouseClick(button, QtCore.Qt.LeftButton)
    assert emitted.args == [locatable]

    assert not panel.table.cellWidget(1, panel.COLUMN_ACTION).isEnabled()
    with qtbot.waitSignal(panel.locate_requested, timeout=1000) as emitted:
        panel.table.cellDoubleClicked.emit(0, panel.COLUMN_MESSAGE)
    assert emitted.args == [locatable]


def test_diagnostics_panel_rejects_stale_stamp_and_can_clear(qtbot):
    panel = DiagnosticsPanel()
    qtbot.addWidget(panel)
    current = _report(
        _item(
            DiagnosticSourceKind.MODEL,
            "current",
            severity="error",
            revision=5,
            deps="deps-5",
        ),
        revision=5,
        deps="deps-5",
    )

    panel.set_report(current, source_revision=6, dependency_fingerprint="deps-5")

    assert panel.table.rowCount() == 0
    assert panel.detail.toPlainText() == ""

    panel.set_report(current, source_revision=5, dependency_fingerprint="deps-5")
    assert panel.table.rowCount() == 1

    panel.set_report(None, source_revision=5, dependency_fingerprint="deps-5")
    assert panel.table.rowCount() == 0
    assert panel.detail.toPlainText() == ""


def test_diagnostics_panel_serializes_read_only_nested_refs_from_service(qtbot):
    panel = DiagnosticsPanel()
    qtbot.addWidget(panel)
    report = DiagnosticService().from_model_error(
        ModelValidationError(
            diagnostics=[
                ModelDiagnostic(
                    code="E_UNDEFINED_VAR",
                    severity="error",
                    message="missing",
                    refs={
                        "context": {"name": "lost"},
                        "transition_span": Span(4, 2, 4, 8),
                    },
                )
            ]
        ),
        SOURCE_URI,
        3,
        "deps-3",
    )

    panel.set_report(report, 3, "deps-3")

    assert '"name": "lost"' in panel.detail.toPlainText()
    assert '"line": 4' in panel.detail.toPlainText()


def test_diagnostics_panel_redacts_paths_only_in_display(qtbot):
    panel = DiagnosticsPanel(
        redactor=lambda value: value.replace("/tmp/work", "<WORKSPACE>")
    )
    qtbot.addWidget(panel)
    item = _item(
        DiagnosticSourceKind.MODEL,
        "failed at /tmp/work/model.fcstm",
        severity="error",
        refs={"path": "/tmp/work/model.fcstm"},
    )
    report = DiagnosticReport(3, "deps-3", (item,))

    panel.set_report(report, 3, "deps-3")

    assert "/tmp/work" not in panel.detail.toPlainText()
    assert "/tmp/work" not in panel.table.item(0, panel.COLUMN_MESSAGE).text()
    assert item.message == "failed at /tmp/work/model.fcstm"

    panel.set_redactor(None)
    assert "/tmp/work" in panel.detail.toPlainText()


def test_suggested_fix_button_exists_only_for_real_fix_and_emits_item(qtbot):
    panel = DiagnosticsPanel()
    qtbot.addWidget(panel)
    plain = _item(DiagnosticSourceKind.INSPECT, "plain")
    fix = SuggestedFix(
        kind="insert",
        target="deadlock_leaf_exit_transition",
        anchor_ref="refs.parent_path",
        text_template="A -> [*];\n",
        rationale="Add an exit transition.",
    )
    actionable = _item(
        DiagnosticSourceKind.INSPECT,
        "deadlock",
        severity="warning",
        refs={
            "suggested_fix": {
                "kind": "insert",
                "target": "deadlock_leaf_exit_transition",
                "anchor": {"ref": "refs.parent_path"},
                "text": "A -> [*];\n",
                "rationale": "Add an exit transition.",
            }
        },
        suggested_fix=fix,
    )
    panel.set_report(_report(plain, actionable), 3, "deps-3")

    assert panel.suggested_fix_button.isHidden()
    panel.table.selectRow(1)
    assert not panel.suggested_fix_button.isHidden()
    with qtbot.waitSignal(panel.suggested_fix_requested, timeout=1000) as emitted:
        qtbot.mouseClick(panel.suggested_fix_button, QtCore.Qt.LeftButton)
    assert emitted.args == [actionable]


def test_incomplete_suggested_fix_payload_does_not_expose_action(qtbot):
    panel = DiagnosticsPanel()
    qtbot.addWidget(panel)
    item = _item(
        DiagnosticSourceKind.INSPECT,
        "incomplete",
        refs={"suggested_fix": {"text": "template only"}},
        suggested_fix=SuggestedFix(
            "insert", "target", "refs.path", "template only", "reason"
        ),
    )

    panel.set_report(_report(item), 3, "deps-3")

    assert panel.suggested_fix_button.isHidden()
