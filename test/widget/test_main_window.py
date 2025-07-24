import pytest
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import QTimerEvent, Qt, QPoint
import os
from app.utils import create_formlayout_dialog
from app.widget import AppMainWindow, DialogEditState
from app.widget import main_window
from pyfcstm.model import NormalState, CompositeState, StateType, State

@pytest.mark.unittest
class TestMainWindow:
    @pytest.fixture
    def get_window(self, qtbot):
        window = AppMainWindow()
        qtbot.addWidget(window)
        return qtbot, window

    @pytest.fixture
    def new_state_chart(self,monkeypatch, get_window):
        qtbot, window = get_window

        def fake_dialog(*args, **kwargs):
            return True, ["TestFSM"]

        monkeypatch.setattr(main_window, "create_formlayout_dialog", fake_dialog)

        qtbot.mouseClick(window.button_initial_new_state_machine, QtCore.Qt.LeftButton)
        assert window.stackedWidget_state_machine.currentIndex() == 1

        return qtbot, window

    def find_top_level_menus(self):
        return [w for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, QtWidgets.QMenu)]

    def test_statechart_name(self, new_state_chart):
        qtbot, window = new_state_chart
        assert window.state_chart.name == "TestFSM"

    def test_state_option(self, new_state_chart):
        qtbot, window = new_state_chart
        #获取根状态节点
        root_item = window.tree_state_machine_all_state.topLevelItem(0)
        assert root_item is not None

        #模拟右键点击根状态节点
        #pos = window.tree_state_machine_all_state.visualItemRect(root_item).center()
        #print(pos)
        #qtbot.mouseClick(window.tree_state_machine_all_state.viewport(), Qt.RightButton, pos=pos)
        global_pos = window.tree_state_machine_all_state.viewport().mapToGlobal(
            window.tree_state_machine_all_state.visualItemRect(root_item).center()
        )
        local_pos = window.mapFromGlobal(global_pos)

        # 模拟右键点击
        qtbot.mouseClick(window, Qt.RightButton, pos=global_pos)
        #获取上下文菜单
        context_menu = None
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(widget, QtWidgets.QMenu):
                print(widget)
                context_menu = widget

        assert context_menu is not None
        assert isinstance(context_menu, QtWidgets.QMenu)
        #menus = self.find_top_level_menus()
        #assert len(menus) == 1
        #context_menu = menus[0]

        print("###")
        print(context_menu)
        print("###")
        #找到并点击"添加子状态"选项
        add_action = None
        for action in context_menu.actions():
            if action.text() == "添加子状态":
                add_action = action
                break
        assert add_action is not None
        add_action.trigger()

        # 5. 获取弹出的对话框
        dialog = window.findChild(DialogEditState)
        assert dialog is not None

        # 6. 填写对话框内容
        qtbot.keyClicks(dialog.edit_state_name, "test_add_state")
        qtbot.keyClicks(dialog.edit_state_description, "test state")
        dialog.combo_state_type.setCurrentText("normal")  # 设置为普通状态
        qtbot.keyClicks(dialog.edit_min_time, "1")
        qtbot.keyClicks(dialog.edit_max_time, "10")
        qtbot.keyClicks(dialog.edit_state_entry, "1")
        qtbot.keyClicks(dialog.edit_state_during, "2")
        qtbot.keyClicks(dialog.edit_state_exit, "3")

        # 7. 点击确定按钮
        ok_button = dialog.findChild(QtWidgets.QPushButton, "button_accept")
        assert ok_button is not None
        qtbot.mouseClick(ok_button, Qt.LeftButton)

        # 8. 验证子状态是否添加成功
        # 检查树中是否有新添加的子状态
        child_item = root_item.child(0)
        assert child_item is not None
        assert child_item.text(0) == "test_add_state"

        # 检查状态对象是否正确创建
        child_state = child_item.data(0, Qt.UserRole)
        assert child_state is not None
        assert isinstance(child_state, NormalState)
        assert child_state.name == "test_add_state"
        assert child_state.description == "test state"
        assert child_state.type == NormalState
        assert child_state.min_time_lock == 1
        assert child_state.max_time_lock == 10
        assert child_state.on_entry == "1"
        assert child_state.on_during == "2"
        assert child_state.on_exit == "3"

        # 检查父状态是否正确设置
        assert child_state in window.state_chart.root_state.states
        assert window.d_id_father_state[child_state.id] == window.state_chart.root_state

    def test_import_statechart(self, monkeypatch, get_window, tmp_path):
        qtbot, window = main_window
        json_file = "../ui/ui/export_data/test_json.json"
        json_file = "../../app/ui/ui/export_data/test_json.json"
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(json_file), "JSON Files (*.json)")
        )

        window._import_statechart()

        assert window.state_chart is not None
        assert window.state_chart.name == "1234"
        assert "".join(window.state_chart.preamble) == ""
        assert window.state_chart.root_state.name == "start2"

