from PyQt5 import QtWidgets
from types import SimpleNamespace

from app.widget.dialog_add_lifecycle import DialogAddLifecycle
from app.widget.dialog_add_transition import DialogAddTransition


class _State:
    transitions = []
    lifecycle = []

    @staticmethod
    def get_full_path():
        return "Root"


class _Manager:
    @staticmethod
    def get_state_by_path(path):
        return object()


def test_transition_dialog_blocks_invalid_guard_and_accepts_real_formulas(
    monkeypatch, qtbot
):
    warnings = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args[2]),
    )
    dialog = DialogAddTransition(
        None, _Manager(), _State(), mutate_model=False
    )
    qtbot.addWidget(dialog)
    dialog.edit_source_state.setText("A")
    dialog.edit_target_state.setText("B")
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
    dialog = DialogAddLifecycle(
        None, _Manager(), _State(), mutate_model=False
    )
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
    dialog = DialogAddTransition(
        parent, _Manager(), _State(), mutate_model=False
    )
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
    dialog = DialogAddTransition(
        parent, _Manager(), _State(), mutate_model=False
    )
    dialog.edit_op.setPlainText("x = x + 1;")

    assert not dialog.effect_formula_editor.validate_now()
