import pytest
from PyQt5.Qt import Qt
from PyQt5 import QtCore, QtGui, QtWidgets
from app.widget import DialogEditState
from pyfcstm.model import NormalState


@pytest.mark.unittest
class TestMainWindow:
    def test_state_name(self, qtbot, monkeypatch):
        edit_state = NormalState("name1")
        des = DialogEditState(None, True, edit_state)
        qtbot.addWidget(des)
        des.edit_state_name.setText('')

        called = {}

        def fake_warning(parent, title, text, buttons=QtWidgets.QMessageBox.Ok):
            called['shown'] = (title, text)
            return QtWidgets.QMessageBox.Ok

        monkeypatch.setattr(QtWidgets.QMessageBox, 'warning', fake_warning)

        # 点击按钮
        qtbot.mouseClick(des.button_accept, Qt.MouseButton.LeftButton)

        assert des.edit_state_name.text() == ''
        assert 'shown' in called
        assert called['shown'][1] == "状态名不能为空！"

    def test_correct_time(self, qtbot, monkeypatch):
        edit_state = NormalState("name1")
        des = DialogEditState(None, True, edit_state)
        qtbot.addWidget(des)
        des.edit_min_time.setText('')
        des.edit_max_time.setText('20')

        called = {}

        def fake_warning(parent, title, text, buttons=QtWidgets.QMessageBox.Ok):
            called['shown'] = (title, text)
            return QtWidgets.QMessageBox.Ok

        monkeypatch.setattr(QtWidgets.QMessageBox, 'warning', fake_warning)

        # 点击按钮
        qtbot.mouseClick(des.button_accept, Qt.MouseButton.LeftButton)

        assert des.edit_min_time.text() == ''
        assert des.edit_max_time.text() == '20'
        assert 'shown' not in called

    def test_not_correct_time(self, qtbot, monkeypatch):
        edit_state = NormalState("name1")
        des = DialogEditState(None, True, edit_state)
        qtbot.addWidget(des)
        des.edit_min_time.setText('abc')
        des.edit_max_time.setText('20')

        called = {}

        def fake_warning(parent, title, text, buttons=QtWidgets.QMessageBox.Ok):
            called['shown'] = (title, text)
            return QtWidgets.QMessageBox.Ok

        monkeypatch.setattr(QtWidgets.QMessageBox, 'warning', fake_warning)

        # 点击按钮
        qtbot.mouseClick(des.button_accept, Qt.MouseButton.LeftButton)

        assert des.edit_min_time.text() == 'abc'
        assert des.edit_max_time.text() == '20'
        assert 'shown' in called
        assert called['shown'][1] == '最小停留时间和最大停留时间应为整数！'