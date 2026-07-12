from PyQt5 import QtWidgets

from app.application.formulas import (
    FormulaKind,
    FormulaValidationRequest,
    FormulaValidationService,
)
from app.widget.formula_editor import FormulaEditor


def test_formula_editor_debounces_real_validation_and_shows_location(qtbot):
    field = QtWidgets.QLineEdit()
    editor = FormulaEditor(field, FormulaKind.LOGICAL, debounce_ms=20)
    qtbot.addWidget(editor)
    editor.show()

    field.setText("x +")
    qtbot.waitUntil(lambda: editor.last_result is not None, timeout=1000)

    assert not editor.is_valid
    assert "1:" in editor.status_label.text()
    assert editor.status_label.toolTip()


def test_formula_editor_drops_stale_token_and_revision_results(qtbot):
    revision = [3]
    field = QtWidgets.QLineEdit()
    editor = FormulaEditor(
        field,
        FormulaKind.NUMERIC,
        revision_provider=lambda: revision[0],
        debounce_ms=1000,
    )
    qtbot.addWidget(editor)
    field.setText("x + 1")
    request = editor.pending_request
    assert request is not None

    stale_token = FormulaValidationService().validate(
        FormulaValidationRequest(
            FormulaKind.NUMERIC,
            "x + 1",
            request.source_revision,
            "older-token",
        )
    )
    assert not editor.apply_result(stale_token)

    revision[0] = 4
    result = FormulaValidationService().validate(request)
    assert not editor.apply_result(result)
    assert editor.last_result is None


def test_formula_editor_allows_optional_empty_and_validates_on_submit(qtbot):
    field = QtWidgets.QPlainTextEdit()
    editor = FormulaEditor(field, FormulaKind.EFFECT, allow_empty=True)
    qtbot.addWidget(editor)

    assert editor.validate_now()
    assert editor.is_valid

    field.setPlainText("x = ;")
    assert not editor.validate_now()
    assert field.textCursor().position() == len("x = ")


def test_validate_now_refreshes_request_after_document_revision_changes(qtbot):
    revision = [1]
    field = QtWidgets.QLineEdit()
    editor = FormulaEditor(
        field,
        FormulaKind.NUMERIC,
        revision_provider=lambda: revision[0],
        debounce_ms=1000,
    )
    qtbot.addWidget(editor)
    field.setText("x + 1")
    revision[0] = 2

    assert editor.validate_now()
    assert editor.last_result.source_revision == 2
