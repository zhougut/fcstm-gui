import pytest
from PyQt5 import QtCore, QtWidgets

from app.model import State, StateManager
from app.model.session import ValidationState
from app.widget import AppMainWindow
from app.widget import main_window


@pytest.mark.unittest
class TestMainWindow:
    @pytest.fixture
    def window(self, qtbot):
        window = AppMainWindow()
        qtbot.addWidget(window)
        return window

    def test_new_button_opens_editor_with_empty_state_manager(self, qtbot, window):
        assert window.stackedWidget_state_machine.currentIndex() == 0
        assert not hasattr(window, "state_manager")

        qtbot.mouseClick(
            window.button_initial_new_state_machine,
            QtCore.Qt.LeftButton,
        )

        assert window.stackedWidget_state_machine.currentIndex() == 1
        assert window.at_page_initial is False
        assert isinstance(window.state_manager, StateManager)
        assert window.state_manager.get_root_state() is None

    def test_import_valid_fcstm_updates_model_and_editor(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / "traffic.fcstm"
        source.write_text(
            """
def int count = 0;
state TrafficLight {
    state Red;
    state Green;
    [*] -> Red;
    Red -> Green : if [count >= 1];
}
""".strip(),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(source), "fcstm Files (*.fcstm)"),
        )

        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            window._import_statechart()

        manager = window.state_manager
        assert manager.get_root_state().name == "TrafficLight"
        assert [child.name for child in manager.get_root_state().children] == [
            "Red",
            "Green",
        ]
        assert manager.variable_definitions == "def int count = 0;"
        assert window.edit_var_def.toPlainText() == manager.variable_definitions
        assert window.tree_all_state.topLevelItem(0).text(0) == "TrafficLight"
        assert window.tree_all_state.topLevelItem(0).childCount() == 2
        assert window.stackedWidget_state_machine.currentIndex() == 1
        assert window.at_page_initial is False
        assert window.state_machine_file_path == str(tmp_path)
        assert window.document_session.source_text == source.read_bytes().decode("utf-8")
        assert window.document_session.validated_revision == 0
        assert window.edit_var_def.isReadOnly()
        assert not window.button_add_state.isEnabled()
        assert not window.button_transition.isEnabled()
        assert not window.button_lifecycle.isEnabled()

    def test_invalid_import_becomes_editable_source_without_stale_model(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        original = StateManager(State("Existing"))
        original.variable_definitions = "def int value = 7;"
        window.state_manager = original

        invalid_source = tmp_path / "broken.fcstm"
        invalid_source.write_text("state Broken { state Child;", encoding="utf-8")
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (
                str(invalid_source),
                "fcstm Files (*.fcstm)",
            ),
        )
        messages = []
        monkeypatch.setattr(
            QtWidgets.QMessageBox,
            "critical",
            lambda parent, title, text, *args, **kwargs: messages.append(
                (title, text)
            ),
        )

        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            window._import_statechart()

        assert window.state_manager is None
        assert window.document_session.source_text == invalid_source.read_text(
            encoding="utf-8"
        )
        assert window.document_session.validation_state is ValidationState.INVALID_SYNTAX
        assert window.source_editor.toPlainText() == window.document_session.source_text
        assert window.document_session.last_valid_snapshot is None
        assert messages
        assert messages[0][0] == "导入失败"
        assert "解析fcstm文件时发生错误" in messages[0][1]

    def test_source_editor_change_validates_latest_revision_in_background(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / "editable.fcstm"
        source.write_text(
            "state Root { state A; [*] -> A; A -> [*]; }",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(source), "fcstm Files (*.fcstm)"),
        )
        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            window._import_statechart()

        with qtbot.waitSignal(window.document_validation_finished, timeout=3000):
            window.source_editor.setPlainText("state Broken {")

        assert window.document_session.source_revision == 1
        assert window.document_session.validation_state is ValidationState.INVALID_SYNTAX
        assert window.document_session.last_valid_snapshot.source_revision == 0
        assert window.state_manager is None
        assert not window.action_graph_gen.isEnabled()

        fixed = "state Fixed { state A; [*] -> A; A -> [*]; }"
        with qtbot.waitSignal(window.document_validation_finished, timeout=3000):
            window.source_editor.setPlainText(fixed)

        assert window.document_session.source_revision == 2
        assert window.document_session.validated_revision == 2
        assert window.state_manager.root_state.name == "Fixed"
        assert window.action_graph_gen.isEnabled()

    def test_save_writes_exact_source_text_and_clears_dirty(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / "save.fcstm"
        source.write_text(
            "// keep\nstate Root { state A; [*] -> A; A -> [*]; }\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(source), "fcstm Files (*.fcstm)"),
        )
        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            window._import_statechart()
        changed = "// keep exactly\nstate Root { state A; [*] -> A; A -> [*]; }\n"
        with qtbot.waitSignal(window.document_validation_finished, timeout=3000):
            window.source_editor.setPlainText(changed)

        assert window.document_session.dirty
        window._save_current_document()

        assert source.read_text(encoding="utf-8") == changed
        assert not window.document_session.dirty

    def test_dirty_document_cancel_keeps_current_session(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        first = tmp_path / "first.fcstm"
        second = tmp_path / "second.fcstm"
        first.write_text("state First;", encoding="utf-8")
        second.write_text("state Second;", encoding="utf-8")
        selected = [str(first), str(second)]
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (
                selected.pop(0),
                "fcstm Files (*.fcstm)",
            ),
        )
        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            window._import_statechart()
        with qtbot.waitSignal(window.document_validation_finished, timeout=3000):
            window.source_editor.setPlainText("state Changed;")
        current = window.document_session
        monkeypatch.setattr(
            QtWidgets.QMessageBox,
            "question",
            lambda *args, **kwargs: QtWidgets.QMessageBox.Cancel,
        )

        assert window._import_statechart() is None
        assert window.document_session is current
        assert window.document_session.path == str(first.resolve())

    def test_loaded_document_validation_and_dsl_export_use_source_authority(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / "authority.fcstm"
        original = "// exact\nstate Root { state A; [*] -> A; A -> [*]; }\n"
        source.write_text(original, encoding="utf-8")
        selected = [(str(source), "fcstm Files (*.fcstm)")]
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: selected.pop(0),
        )
        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            window._import_statechart()
        monkeypatch.setattr(
            main_window,
            "state_manager_to_dsl",
            lambda manager: (_ for _ in ()).throw(
                AssertionError("loaded document must not regenerate DSL")
            ),
        )
        messages = []
        monkeypatch.setattr(
            QtWidgets.QMessageBox,
            "information",
            lambda parent, title, text, *args: messages.append((title, text)),
        )

        report = window._validate_statechart()

        assert report["root_state_path"] == "Root"
        assert messages
        exported = tmp_path / "exported.fcstm"
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getSaveFileName",
            lambda *args, **kwargs: (
                str(exported),
                "fcstm Files (*.fcstm)",
            ),
        )
        window._export_statechart()
        assert exported.read_bytes().decode("utf-8") == original

    def test_add_button_creates_root_then_child_without_blocking_dialog(
        self, monkeypatch, qtbot, window
    ):
        class AcceptedStateDialog:
            names = iter(("Root", "Child"))

            def __init__(self, *args, **kwargs):
                self.name = next(self.names)

            def exec_(self):
                return QtWidgets.QDialog.Accepted

            def get_state_name(self):
                return self.name

        monkeypatch.setattr(main_window, "DialogEditState", AcceptedStateDialog)
        qtbot.mouseClick(
            window.button_initial_new_state_machine,
            QtCore.Qt.LeftButton,
        )

        qtbot.mouseClick(window.button_add_state, QtCore.Qt.LeftButton)
        root_item = window.tree_all_state.topLevelItem(0)
        assert root_item.text(0) == "Root"
        assert root_item.data(0, QtCore.Qt.UserRole) is window.state_manager.root_state

        window.tree_all_state.setCurrentItem(root_item)
        qtbot.mouseClick(window.button_add_state, QtCore.Qt.LeftButton)

        child_item = root_item.child(0)
        root_state = window.state_manager.root_state
        assert child_item.text(0) == "Child"
        assert [state.name for state in root_state.children] == ["Child"]
        assert root_state.children[0].parent is root_state
        assert window.state_manager.get_state_by_path("Root.Child") is root_state.children[0]

    def test_menu_actions_are_connected_to_window_commands(self, window):
        file_actions = window.menu_file.actions()
        tool_actions = window.menu_tool.actions()

        assert window.action_import_state_machine in file_actions
        assert window.action_export_state_machine in file_actions
        assert window.action_validate_state_machine in tool_actions
        assert window.action_graph_gen in tool_actions
        assert window.action_code_gen in tool_actions

        for action in (
            window.action_import_state_machine,
            window.action_export_state_machine,
            window.action_validate_state_machine,
            window.action_graph_gen,
            window.action_code_gen,
        ):
            assert action.receivers(action.triggered) >= 1
