import pytest
from PyQt5 import QtWidgets

from app.model import State, StateManager
from app.widget.dialog_add_lifecycle import DialogAddLifecycle
from app.widget.dialog_add_transition import DialogAddTransition
from app.widget.dialog_edit_state import DialogEditState


def _hierarchy():
    root = State("Root")
    group = State("Group")
    ready = State("Ready")
    running = State("Running")
    root.add_child(group)
    group.add_child(ready)
    root.add_child(running)
    return StateManager(root), root, group, ready, running


@pytest.mark.unittest
def test_new_state_parent_is_selected_from_full_path_combo(qtbot):
    manager, root, group, _, _ = _hierarchy()
    dialog = DialogEditState(
        None, manager, is_edit=False, parent_state=group
    )
    qtbot.addWidget(dialog)

    assert isinstance(dialog.combo_parent_state, QtWidgets.QComboBox)
    assert dialog.combo_parent_state.currentText() == "Root.Group"
    assert dialog.get_parent_state() is group

    dialog.combo_parent_state.setCurrentText("Root")
    assert dialog.get_parent_state() is root


@pytest.mark.unittest
def test_lifecycle_owner_combo_can_choose_any_existing_state(qtbot):
    manager, root, _, ready, running = _hierarchy()
    dialog = DialogAddLifecycle(
        None, manager, root, mutate_model=False
    )
    qtbot.addWidget(dialog)

    assert dialog.combo_owner_state.currentText() == "Root"
    assert "Root.Group.Ready" in [
        dialog.combo_owner_state.itemText(index)
        for index in range(dialog.combo_owner_state.count())
    ]
    dialog.combo_owner_state.setCurrentText("Root.Running")
    assert dialog.get_owner_state() is running
    assert dialog.get_owner_state() is not ready


@pytest.mark.unittest
def test_transition_endpoints_are_constrained_state_combos(qtbot):
    manager, root, _, ready, running = _hierarchy()
    dialog = DialogAddTransition(
        None, manager, root, mutate_model=False
    )
    qtbot.addWidget(dialog)

    assert isinstance(dialog.edit_source_state, QtWidgets.QComboBox)
    assert isinstance(dialog.edit_target_state, QtWidgets.QComboBox)
    assert not dialog.edit_source_state.isEditable()
    assert not dialog.edit_target_state.isEditable()

    dialog.edit_source_state.setCurrentText("Root.Group.Ready")
    dialog.edit_target_state.setCurrentText("Root.Running")
    assert dialog.get_transition_data()["source"] == ready.name
    assert dialog.get_transition_data()["target"] == running.name

    dialog.check_force_transition.setChecked(True)
    assert dialog.get_transition_data()["source"] == "! Ready"
