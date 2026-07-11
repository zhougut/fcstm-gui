import pytest
from PyQt5 import QtWidgets
from PyQt5.Qt import Qt
from PyQt5.QtTest import QSignalSpy

from app.model import State, StateManager
from app.widget import DialogEditState


@pytest.fixture
def warning_messages(monkeypatch):
    messages = []

    def fake_warning(parent, title, text, buttons=QtWidgets.QMessageBox.Ok):
        messages.append((title, text))
        return QtWidgets.QMessageBox.Ok

    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", fake_warning)
    return messages


@pytest.mark.unittest
class TestDialogEditState:
    def test_empty_name_is_rejected(self, qtbot, warning_messages):
        dialog = DialogEditState(None, StateManager(), is_edit=False)
        qtbot.addWidget(dialog)
        accepted = QSignalSpy(dialog.accepted)

        dialog.edit_state_name.setText("   ")
        qtbot.mouseClick(dialog.button_accept, Qt.LeftButton)

        assert len(accepted) == 0
        assert warning_messages == [("错误", "状态名不能为空！")]

    def test_duplicate_name_is_rejected(self, qtbot, warning_messages):
        root = State("Root")
        root.add_child(State("Existing"))
        dialog = DialogEditState(
            None,
            StateManager(root),
            is_edit=False,
            parent_state=root,
        )
        qtbot.addWidget(dialog)
        accepted = QSignalSpy(dialog.accepted)

        qtbot.keyClicks(dialog.edit_state_name, "Existing")
        qtbot.mouseClick(dialog.button_accept, Qt.LeftButton)

        assert len(accepted) == 0
        assert warning_messages == [
            ("错误", "父状态 'Root' 下已存在名为 'Existing' 的子状态！")
        ]

    def test_valid_new_state_is_accepted(self, qtbot, warning_messages):
        root = State("Root")
        dialog = DialogEditState(
            None,
            StateManager(root),
            is_edit=False,
            parent_state=root,
        )
        qtbot.addWidget(dialog)
        accepted = QSignalSpy(dialog.accepted)

        qtbot.keyClicks(dialog.edit_state_name, "NewChild")
        qtbot.mouseClick(dialog.button_accept, Qt.LeftButton)

        assert len(accepted) == 1
        assert dialog.result() == QtWidgets.QDialog.Accepted
        assert dialog.get_state_name() == "NewChild"
        assert warning_messages == []

    def test_valid_edit_is_accepted(self, qtbot, warning_messages):
        root = State("Root")
        edited = State("Before")
        root.add_child(edited)
        dialog = DialogEditState(
            None,
            StateManager(root),
            is_edit=True,
            initial_data=edited,
        )
        qtbot.addWidget(dialog)
        accepted = QSignalSpy(dialog.accepted)

        dialog.edit_state_name.selectAll()
        qtbot.keyClicks(dialog.edit_state_name, "After")
        qtbot.mouseClick(dialog.button_accept, Qt.LeftButton)

        assert len(accepted) == 1
        assert dialog.result() == QtWidgets.QDialog.Accepted
        assert dialog.get_state_name() == "After"
        assert warning_messages == []
