from PyQt5 import QtCore, QtGui, QtWidgets

from ..model import State, StateManager


ROOT_STATE_LABEL = "（根状态）"


def populate_state_combo(
    combo: QtWidgets.QComboBox,
    state_manager: StateManager,
    selected_state: State = None,
    include_root_choice: bool = False,
    placeholder: str = "",
    special_options=(),
):
    """Populate a state selector with stable object-backed choices."""
    previous = combo.blockSignals(True)
    try:
        combo.clear()
        combo.setEditable(False)
        combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLength)
        combo.setMinimumContentsLength(18)
        combo.setMaxVisibleItems(14)

        if placeholder:
            combo.addItem(placeholder, None)
            item = combo.model().item(0)
            if isinstance(item, QtGui.QStandardItem):
                item.setEnabled(False)

        if include_root_choice:
            combo.addItem(ROOT_STATE_LABEL, None)

        for label, value in special_options:
            combo.addItem(label, value)

        selected_index = -1
        for state in state_manager.get_all_states():
            path = state.get_full_path()
            combo.addItem(path, state)
            index = combo.count() - 1
            combo.setItemData(index, path, QtCore.Qt.ToolTipRole)
            if state is selected_state:
                selected_index = index

        if selected_index >= 0:
            combo.setCurrentIndex(selected_index)
        elif combo.count():
            combo.setCurrentIndex(0)
    finally:
        combo.blockSignals(previous)


def selected_state(combo: QtWidgets.QComboBox):
    value = combo.currentData()
    return value if isinstance(value, State) else None


def select_transition_token(combo: QtWidgets.QComboBox, token: str):
    normalized = (token or "").strip()
    for index in range(combo.count()):
        value = combo.itemData(index)
        if isinstance(value, State) and value.name == normalized:
            combo.setCurrentIndex(index)
            return True
        if isinstance(value, str) and value == normalized:
            combo.setCurrentIndex(index)
            return True
    return False


def transition_token(combo: QtWidgets.QComboBox) -> str:
    value = combo.currentData()
    if isinstance(value, State):
        return value.name
    return value.strip() if isinstance(value, str) else ""
