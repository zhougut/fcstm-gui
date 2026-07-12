from PyQt5 import QtWidgets

from app.application.formulas import FormulaKind, FormulaValidationService
from app.widget.dialog_numeric_formula import DialogNumericFormula


def test_numeric_formula_dialog_validates_initial_value_and_exposes_accessible_controls(qtbot):
    dialog = DialogNumericFormula(
        initial_text="x * 2 + 1",
        title="编辑数值公式",
        revision_provider=lambda: 7,
        debounce_ms=20,
    )
    qtbot.addWidget(dialog)
    dialog.show()

    qtbot.waitUntil(lambda: dialog.formula_editor.last_result is not None, timeout=1000)

    assert dialog.objectName() == "numeric_formula_dialog"
    assert dialog.input_field.objectName() == "numeric_formula_input"
    assert dialog.formula_editor.kind is FormulaKind.NUMERIC
    assert isinstance(dialog.formula_editor._service, FormulaValidationService)
    assert dialog.formula_text() == "x * 2 + 1"
    assert dialog.formula_editor.last_result.source_revision == 7
    assert dialog.button_box.button(QtWidgets.QDialogButtonBox.Ok).isEnabled()
    assert dialog.button_box.button(QtWidgets.QDialogButtonBox.Ok).text() == "确定"
    assert (
        dialog.button_box.button(QtWidgets.QDialogButtonBox.Cancel).text()
        == "取消"
    )
    assert dialog.input_field.accessibleName()
    assert dialog.formula_editor.status_label.accessibleName()


def test_numeric_formula_dialog_debounces_invalid_feedback_and_blocks_accept(qtbot):
    dialog = DialogNumericFormula(initial_text="1", debounce_ms=20)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog.formula_editor.last_result is not None, timeout=1000)

    dialog.input_field.setText("x > 0")
    qtbot.waitUntil(
        lambda: dialog.formula_editor.last_result is not None
        and not dialog.formula_editor.is_valid,
        timeout=1000,
    )

    assert "无效" in dialog.formula_editor.status_label.text()
    assert not dialog.button_box.button(QtWidgets.QDialogButtonBox.Ok).isEnabled()

    dialog._on_accept()

    assert dialog.result() == 0


def test_numeric_formula_dialog_accepts_valid_value_and_rejects_without_mutation(qtbot):
    accepted = DialogNumericFormula(initial_text="3", debounce_ms=20)
    qtbot.addWidget(accepted)
    accepted.show()
    accepted.input_field.setText("42")
    qtbot.waitUntil(lambda: accepted.formula_editor.is_valid, timeout=1000)

    accepted._on_accept()

    assert accepted.result() == QtWidgets.QDialog.Accepted
    assert accepted.formula_text() == "42"

    rejected = DialogNumericFormula(initial_text="5", debounce_ms=20)
    qtbot.addWidget(rejected)
    rejected.reject()

    assert rejected.result() == QtWidgets.QDialog.Rejected
    assert rejected.formula_text() == "5"
