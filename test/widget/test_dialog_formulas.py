from PyQt5 import QtWidgets
from types import SimpleNamespace

from app.widget.dialog_add_lifecycle import DialogAddLifecycle
from app.widget.dialog_add_transition import DialogAddTransition
from app.model import State, StateManager
from app.application.formulas import FormulaKind


def _model():
    root = State("Root")
    root.add_child(State("A"))
    root.add_child(State("B"))
    return StateManager(root), root


def test_transition_dialog_blocks_invalid_guard_and_accepts_real_formulas(
    monkeypatch, qtbot
):
    warnings = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args[2]),
    )
    manager, root = _model()
    dialog = DialogAddTransition(None, manager, root, mutate_model=False)
    qtbot.addWidget(dialog)
    dialog.edit_source_state.setCurrentText("Root.A")
    dialog.edit_target_state.setCurrentText("Root.B")
    dialog.edit_condition.setText("x +")
    dialog.edit_op.setPlainText("x = x + 1;")

    dialog._on_accept()

    assert dialog.result() == 0
    assert warnings == ["请修正条件公式后再提交。"]

    dialog.edit_condition.setText("x > 0")
    dialog._on_accept()
    assert dialog.result() == QtWidgets.QDialog.Accepted


def test_lifecycle_dialog_blocks_invalid_production_action(monkeypatch, qtbot):
    warnings = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args[2]),
    )
    manager, root = _model()
    dialog = DialogAddLifecycle(None, manager, root, mutate_model=False)
    qtbot.addWidget(dialog)
    dialog.edit_op.setPlainText("x = ;")

    dialog._on_accept()

    assert dialog.result() == 0
    assert warnings == ["请修正生命周期动作后再提交。"]

    dialog.edit_op.setPlainText("x = x + 1;")
    dialog._on_accept()
    assert dialog.result() == QtWidgets.QDialog.Accepted


def test_dialog_action_validation_uses_current_document_variable_definitions(qtbot):
    parent = QtWidgets.QWidget()
    parent.document_session = SimpleNamespace(
        source_revision=9,
        source_text=(
            "def int count = 0;\n"
            "state Root { state A; state B; [*] -> A; }"
        ),
    )
    qtbot.addWidget(parent)
    manager, root = _model()
    dialog = DialogAddTransition(parent, manager, root, mutate_model=False)
    dialog.edit_op.setPlainText("count = count + 1;")

    assert dialog.effect_formula_editor.validate_now()
    assert dialog.effect_formula_editor.last_result.source_revision == 9


def test_real_document_without_variables_does_not_invent_x(qtbot):
    parent = QtWidgets.QWidget()
    parent.document_session = SimpleNamespace(
        source_revision=10,
        source_text="state Root { state A; state B; [*] -> A; }",
    )
    qtbot.addWidget(parent)
    manager, root = _model()
    dialog = DialogAddTransition(parent, manager, root, mutate_model=False)
    dialog.edit_op.setPlainText("x = x + 1;")

    assert not dialog.effect_formula_editor.validate_now()


def test_transition_and_lifecycle_fields_offer_full_formula_editor(qtbot):
    manager, root = _model()
    transition = DialogAddTransition(None, manager, root, mutate_model=False)
    lifecycle = DialogAddLifecycle(None, manager, root, mutate_model=False)
    qtbot.addWidget(transition)
    qtbot.addWidget(lifecycle)
    transition.show()
    lifecycle.show()
    QtWidgets.QApplication.processEvents()

    assert transition.condition_formula_editor.edit_button.text() == "编辑公式…"
    assert transition.condition_formula_editor.kind is FormulaKind.LOGICAL
    assert transition.effect_formula_editor.edit_button.text() == "编辑动作…"
    assert transition.effect_formula_editor.kind is FormulaKind.EFFECT
    assert lifecycle.lifecycle_formula_editor.edit_button.text() == "编辑动作…"
    assert lifecycle.lifecycle_formula_editor.kind is FormulaKind.LIFECYCLE
    for button in (
        transition.condition_formula_editor.edit_button,
        transition.effect_formula_editor.edit_button,
        lifecycle.lifecycle_formula_editor.edit_button,
    ):
        assert button.accessibleName()
        assert "渲染预览" in button.toolTip()
    assert abs(
        transition.edit_condition.geometry().center().y()
        - transition.condition_formula_editor.edit_button.geometry().center().y()
    ) <= 4


def test_formula_button_returns_edited_text_to_transition_field(
    monkeypatch, qtbot
):
    class AcceptedEditor:
        def __init__(self, *args, **kwargs):
            assert kwargs["kind"] is FormulaKind.LOGICAL

        def exec_(self):
            return QtWidgets.QDialog.Accepted

        def formula_text(self):
            return "count >= 2 && enabled"

    monkeypatch.setattr(
        "app.widget.dialog_formula.DialogFormulaEditor", AcceptedEditor
    )
    manager, root = _model()
    dialog = DialogAddTransition(None, manager, root, mutate_model=False)
    qtbot.addWidget(dialog)

    assert dialog.condition_formula_editor.open_dialog()
    assert dialog.edit_condition.text() == "count >= 2 && enabled"


def test_abstract_lifecycle_disables_complete_action_editor(qtbot):
    manager, root = _model()
    dialog = DialogAddLifecycle(None, manager, root, mutate_model=False)
    qtbot.addWidget(dialog)

    dialog.combo_abstract.setCurrentText("是")

    assert not dialog.lifecycle_formula_editor.isEnabled()
    assert not dialog.lifecycle_formula_editor.edit_button.isEnabled()
