from pyfcstm.dsl.error import SyntaxFailError
from pyfcstm.utils.validate import ModelDiagnostic
from PyQt5 import QtCore
from PyQt5 import QtWidgets

from app.model.session import DocumentSession, ValidationState
from app.widget import AppMainWindow


def _window(qtbot, tmp_path):
    settings = QtCore.QSettings(
        str(tmp_path / "settings.ini"), QtCore.QSettings.IniFormat
    )
    window = AppMainWindow(settings=settings)
    qtbot.addWidget(window)
    return window


def test_main_window_populates_diagnostics_tab_and_locates_source(
    qtbot, tmp_path
):
    window = _window(qtbot, tmp_path)
    source = tmp_path / "bad.fcstm"
    text = "state Root {\n bad"
    source.write_text(text, encoding="utf-8")
    session = DocumentSession.new(str(source), "utf-8", text).with_validation(
        ValidationState.INVALID_SYNTAX,
        (SyntaxFailError(2, 1, "bad", "unexpected token"),),
        None,
    )

    window._set_active_document_session(session)

    assert window.workspace_tabs.isTabEnabled(
        window.workspace_tabs.indexOf(window.diagnostics_workspace)
    )
    assert window.diagnostics_panel.table.rowCount() == 1
    assert window.diagnostics_panel.table.item(
        0, window.diagnostics_panel.COLUMN_SOURCE
    ).text() == "syntax"

    window.diagnostics_panel.table.cellDoubleClicked.emit(
        0, window.diagnostics_panel.COLUMN_MESSAGE
    )

    assert window.workspace_tabs.currentWidget() is window.source_workspace
    cursor = window.source_editor.textCursor()
    assert cursor.selectionStart() == text.index("bad")
    assert cursor.selectedText() == "bad"


def test_invalid_inspect_diagnostic_keeps_inspect_provenance(qtbot, tmp_path):
    window = _window(qtbot, tmp_path)
    source = tmp_path / "inspect.fcstm"
    text = "state Root;"
    source.write_text(text, encoding="utf-8")
    session = DocumentSession.new(str(source), "utf-8", text).with_validation(
        ValidationState.INVALID_MODEL,
        (
            ModelDiagnostic(
                code="E_INSPECT",
                severity="error",
                message="inspect failure",
            ),
        ),
        None,
        diagnostic_source_kind="inspect",
    )

    window._set_active_document_session(session)

    assert window.diagnostics_panel.table.item(
        0, window.diagnostics_panel.COLUMN_SOURCE
    ).text() == "inspect"


def test_diagnostic_location_rejects_changed_dependency(qtbot, tmp_path):
    window = _window(qtbot, tmp_path)
    child = tmp_path / "child.fcstm"
    child.write_text("state Child;", encoding="utf-8")
    source = tmp_path / "root.fcstm"
    source.write_text(
        'state Root { import "./child.fcstm" as Child; '
        "[*] -> Child; Child -> [*]; }",
        encoding="utf-8",
    )
    session = window.document_service.load(source)
    window._set_active_document_session(session)
    item = window.diagnostics_panel.selected_item
    assert item is not None and item.span is not None
    child.write_text('state Child named "changed";', encoding="utf-8")
    window.workspace_tabs.setCurrentWidget(window.diagnostics_workspace)

    assert not window._locate_diagnostic(item)
    assert window.workspace_tabs.currentWidget() is window.diagnostics_workspace


def test_materialized_suggested_fix_requires_confirmation_and_uses_source_edit_path(
    monkeypatch, qtbot, tmp_path
):
    window = _window(qtbot, tmp_path)
    source = tmp_path / "deadlock.fcstm"
    source.write_text(
        "state Root { state A; [*] -> A; }", encoding="utf-8"
    )
    window._set_active_document_session(window.document_service.load(source))
    row = next(
        row
        for row in range(window.diagnostics_panel.table.rowCount())
        if window.diagnostics_panel.table.item(
            row, window.diagnostics_panel.COLUMN_CODE
        ).text()
        == "W_DEADLOCK_LEAF"
    )
    window.diagnostics_panel.table.selectRow(row)
    applied = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
    )
    monkeypatch.setattr(
        window,
        "_insert_state_declaration",
        lambda state, kind, declaration: applied.append(
            (state.get_full_path(), kind, declaration)
        )
        or True,
    )

    assert not window.diagnostics_panel.suggested_fix_button.isHidden()
    qtbot.mouseClick(
        window.diagnostics_panel.suggested_fix_button,
        QtCore.Qt.LeftButton,
    )

    assert applied == [("Root", "transition", "A -> [*];")]


def test_materialized_suggested_fix_commits_and_revalidates_document(
    monkeypatch, qtbot, tmp_path
):
    window = _window(qtbot, tmp_path)
    source = tmp_path / "deadlock-commit.fcstm"
    source.write_text(
        "state Root { state A; [*] -> A; }", encoding="utf-8"
    )
    window._set_active_document_session(window.document_service.load(source))
    item = next(
        diagnostic
        for diagnostic in window.diagnostics_panel._items
        if diagnostic.code == "W_DEADLOCK_LEAF"
    )
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
    )
    monkeypatch.setattr(
        QtWidgets.QDialog,
        "exec_",
        lambda *args, **kwargs: QtWidgets.QDialog.Accepted,
    )

    assert window._apply_diagnostic_suggested_fix(item)

    assert "A -> [*];" in window.document_session.source_text
    assert window.document_session.source_revision == 1
    assert window.document_session.current_valid_snapshot is not None
    assert window.document_session.validated_revision == 1


def test_self_assign_fix_uses_its_transition_span_when_actions_are_identical(
    monkeypatch, qtbot, tmp_path
):
    window = _window(qtbot, tmp_path)
    source = tmp_path / "two-self-assigns.fcstm"
    source.write_text(
        "def int x = 0; state Root { state A; state B; [*] -> A; "
        "A -> B effect { x = x; } B -> A effect { x = x; } }",
        encoding="utf-8",
    )
    window._set_active_document_session(window.document_service.load(source))
    item = next(
        diagnostic
        for diagnostic in window.diagnostics_panel._items
        if diagnostic.code == "W_EFFECT_SELF_ASSIGN"
        and diagnostic.refs["state_path"] == "Root.B"
    )
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
    )
    monkeypatch.setattr(
        QtWidgets.QDialog,
        "exec_",
        lambda *args, **kwargs: QtWidgets.QDialog.Accepted,
    )

    assert window._apply_diagnostic_suggested_fix(item)

    updated = window.document_session.source_text
    assert updated.count("x = x;") == 1
    assert "A -> B effect { x = x; }" in updated
    assert window.document_session.current_valid_snapshot is not None
