import threading

import pytest
from PyQt5 import QtCore, QtWidgets

from app.model import State, StateManager
from app.model.session import ValidationState
from app.widget import AppMainWindow
from app.widget import main_window


@pytest.mark.unittest
class TestMainWindow:
    @pytest.fixture
    def window(self, qtbot, tmp_path):
        settings = QtCore.QSettings(
            str(tmp_path / "settings.ini"), QtCore.QSettings.IniFormat
        )
        window = AppMainWindow(settings=settings)
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
        assert not window.edit_var_def.isReadOnly()
        assert window.button_add_state.isEnabled()
        assert window.button_transition.isEnabled()
        assert window.button_lifecycle.isEnabled()

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

    def test_ambiguous_root_encoding_prompts_and_retries(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / "encoded.fcstm"
        source_text = 'state Root named "全";'
        source.write_bytes(source_text.encode("gb18030"))
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(source), "fcstm Files (*.fcstm)"),
        )
        prompts = []
        monkeypatch.setattr(
            QtWidgets.QInputDialog,
            "getItem",
            lambda *args, **kwargs: (
                prompts.append(args) or "GB18030",
                True,
            ),
        )

        window._import_statechart()
        qtbot.waitUntil(
            lambda: window.document_session is not None,
            timeout=3000,
        )

        assert prompts
        assert window.document_session.encoding == "gb18030"
        assert window.document_session.source_text == source_text

    def test_wrong_root_encoding_can_be_reselected_before_final_signal(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / "encoded.fcstm"
        source_text = 'state Root named "全";'
        source.write_bytes(source_text.encode("gb18030"))
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(source), "fcstm Files (*.fcstm)"),
        )
        selections = iter((("Big5", True), ("GB18030", True)))
        monkeypatch.setattr(
            QtWidgets.QInputDialog,
            "getItem",
            lambda *args, **kwargs: next(selections),
        )
        completed = []
        window.document_load_finished.connect(completed.append)

        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            operation = window._import_statechart()

        assert len(completed) == 1
        assert completed[0].operation_id == operation.operation_id
        assert operation.result is completed[0]
        assert operation.result.status is main_window.TaskStatus.SUCCESS
        assert window.document_session.encoding == "gb18030"
        assert window.document_session.source_text == source_text

    def test_import_encoding_cancel_keeps_current_document(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        current_path = tmp_path / "current.fcstm"
        current_path.write_text("state Current;", encoding="utf-8")
        current = window.document_service.load(current_path)
        window._set_active_document_session(current)

        child = tmp_path / "child.fcstm"
        root = tmp_path / "root.fcstm"
        child.write_bytes('state Child named "状态";'.encode("gb18030"))
        root.write_text(
            'state Root { import "./child.fcstm" as Imported; '
            '[*] -> Imported; Imported -> [*]; }',
            encoding="utf-8",
        )
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(root), "fcstm Files (*.fcstm)"),
        )
        monkeypatch.setattr(
            QtWidgets.QInputDialog,
            "getItem",
            lambda *args, **kwargs: ("UTF-8", False),
        )

        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            operation = window._import_statechart()

        assert window.document_session is current
        assert window.document_session.source_text == "state Current;"
        assert operation.result.status is main_window.TaskStatus.CANCELLED

    def test_root_encoding_cancel_keeps_current_document_without_error_dialog(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        current_path = tmp_path / "current.fcstm"
        current_path.write_text("state Current;", encoding="utf-8")
        current = window.document_service.load(current_path)
        window._set_active_document_session(current)
        encoded = tmp_path / "encoded.fcstm"
        encoded.write_bytes('state Root named "全";'.encode("gb18030"))
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(encoded), "fcstm Files (*.fcstm)"),
        )
        monkeypatch.setattr(
            QtWidgets.QInputDialog,
            "getItem",
            lambda *args, **kwargs: ("UTF-8", False),
        )
        errors = []
        monkeypatch.setattr(
            QtWidgets.QMessageBox,
            "critical",
            lambda *args, **kwargs: errors.append(args),
        )

        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            operation = window._import_statechart()

        assert window.document_session is current
        assert not errors
        assert operation.result.status is main_window.TaskStatus.CANCELLED

    def test_import_encoding_retry_publishes_only_final_valid_session(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        child = tmp_path / "child.fcstm"
        root = tmp_path / "root.fcstm"
        child.write_bytes('state Child named "全";'.encode("gb18030"))
        root.write_text(
            'state Root { import "./child.fcstm" as Imported; '
            '[*] -> Imported; Imported -> [*]; }',
            encoding="utf-8",
        )
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(root), "fcstm Files (*.fcstm)"),
        )
        monkeypatch.setattr(
            QtWidgets.QInputDialog,
            "getItem",
            lambda *args, **kwargs: ("GB18030", True),
        )
        completed = []
        window.document_load_finished.connect(completed.append)

        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            window._import_statechart()

        assert len(completed) == 1
        assert window.document_session.current_valid_snapshot is not None
        assert window.document_session.encoding_hints == (
            (str(child.resolve()), "gb18030"),
        )

    def test_projection_failure_completes_logical_load_once(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / "valid.fcstm"
        source.write_text("state Root;", encoding="utf-8")
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(source), "fcstm Files (*.fcstm)"),
        )
        monkeypatch.setattr(
            main_window,
            "convert_state_machine_to_state_manager",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("projection failed")
            ),
        )
        monkeypatch.setattr(
            QtWidgets.QMessageBox, "critical", lambda *args, **kwargs: None
        )
        completed = []
        window.document_load_finished.connect(completed.append)

        operation = window._import_statechart()
        qtbot.waitUntil(lambda: operation.result is not None, timeout=3000)

        assert len(completed) == 1
        assert operation.result is completed[0]
        assert operation.result.status is main_window.TaskStatus.FAILED
        assert isinstance(operation.result.ui_error, RuntimeError)
        assert window.document_session is None

    def test_ui_install_failure_restores_previous_document_and_recent_files(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        current_path = tmp_path / "current.fcstm"
        next_path = tmp_path / "next.fcstm"
        current_path.write_text("state Current;", encoding="utf-8")
        next_path.write_text("state Next;", encoding="utf-8")
        current = window.document_service.load(current_path)
        window._set_active_document_session(current)
        previous_recent = window.settings.value("recent_files", [], type=list)
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(next_path), "fcstm Files (*.fcstm)"),
        )
        real_update = main_window.update_ui_from_state_manager
        calls = []

        def fail_once(target, manager):
            calls.append(manager.root_state.name)
            if len(calls) == 1:
                raise RuntimeError("ui install failed")
            return real_update(target, manager)

        monkeypatch.setattr(main_window, "update_ui_from_state_manager", fail_once)
        monkeypatch.setattr(
            QtWidgets.QMessageBox, "critical", lambda *args, **kwargs: None
        )

        operation = window._import_statechart()
        qtbot.waitUntil(lambda: operation.result is not None, timeout=3000)

        assert operation.result.status is main_window.TaskStatus.FAILED
        assert window.document_session is current
        assert window.state_manager.root_state.name == "Current"
        assert window.source_editor.toPlainText() == "state Current;"
        assert window.settings.value("recent_files", [], type=list) == previous_recent

    def test_superseded_loads_keep_distinct_operation_results(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        first_path = tmp_path / "first.fcstm"
        second_path = tmp_path / "second.fcstm"
        first_path.write_text("state First;", encoding="utf-8")
        second_path.write_text("state Second;", encoding="utf-8")
        selected_paths = iter((str(first_path), str(second_path)))
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (
                next(selected_paths),
                "fcstm Files (*.fcstm)",
            ),
        )
        real_load = window.document_service.load
        first_started = threading.Event()
        release_first = threading.Event()

        def controlled_load(path, **kwargs):
            if str(path) == str(first_path):
                first_started.set()
                release_first.wait(3)
            return real_load(path, **kwargs)

        monkeypatch.setattr(window.document_service, "load", controlled_load)

        first = window._import_statechart()
        qtbot.waitUntil(first_started.is_set, timeout=3000)
        second = window._import_statechart()
        release_first.set()
        qtbot.waitUntil(
            lambda: first.result is not None and second.result is not None,
            timeout=3000,
        )

        assert first.operation_id != second.operation_id
        assert first.result.operation_id == first.operation_id
        assert first.result.status is main_window.TaskStatus.CANCELLED
        assert second.result.operation_id == second.operation_id
        assert second.result.status is main_window.TaskStatus.SUCCESS
        assert window.document_session.path == str(second_path.resolve())

    def test_recent_files_are_isolated_deduplicated_and_bounded(
        self, window, tmp_path
    ):
        paths = [tmp_path / "{}.fcstm".format(index) for index in range(12)]
        for path in paths:
            window._record_recent_file(str(path))
        window._record_recent_file(str(paths[5]))

        recent = window.settings.value("recent_files", [], type=list)
        assert len(recent) == 10
        assert recent[0] == str(paths[5].resolve())
        assert recent.count(str(paths[5].resolve())) == 1

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

    @pytest.mark.parametrize(
        "reply,expected_text,accepted",
        [
            (QtWidgets.QMessageBox.Save, "state Changed;", True),
            (QtWidgets.QMessageBox.Discard, "state Original;", True),
            (QtWidgets.QMessageBox.Cancel, "state Original;", False),
        ],
    )
    def test_visible_dirty_close_save_discard_cancel(
        self,
        monkeypatch,
        qtbot,
        window,
        tmp_path,
        reply,
        expected_text,
        accepted,
    ):
        source = tmp_path / "dirty.fcstm"
        source.write_text("state Original;", encoding="utf-8")
        session = window.document_service.load(source)
        dirty = window.document_service.replace_source_text(
            session, "state Changed;"
        )
        window._set_active_document_session(dirty)
        window.show()
        QtWidgets.QApplication.processEvents()
        assert window.isVisible()
        monkeypatch.setattr(
            QtWidgets.QMessageBox,
            "question",
            lambda *args, **kwargs: reply,
        )
        closed = window.close()
        QtWidgets.QApplication.processEvents()

        assert closed is accepted
        assert window.isVisible() is (not accepted)
        assert source.read_text(encoding="utf-8") == expected_text
        if not accepted:
            assert window.document_session is dirty
            window.hide()

    def test_invalid_source_save_rejection_blocks_real_window_close(
        self, monkeypatch, window, tmp_path
    ):
        source = tmp_path / "invalid.fcstm"
        source.write_text("state Original;", encoding="utf-8")
        session = window.document_service.load(source)
        invalid = window.document_service.replace_source_text(
            session, "state Broken {"
        )
        window._set_active_document_session(invalid)
        window.show()
        QtWidgets.QApplication.processEvents()

        def answer(parent, title, *args, **kwargs):
            if title == "未保存的修改":
                return QtWidgets.QMessageBox.Save
            if title == "保存无效源码":
                return QtWidgets.QMessageBox.No
            raise AssertionError("unexpected question: {}".format(title))

        monkeypatch.setattr(QtWidgets.QMessageBox, "question", answer)

        assert not window.close()
        QtWidgets.QApplication.processEvents()
        assert window.isVisible()
        assert source.read_text(encoding="utf-8") == "state Original;"
        assert window.document_session is invalid
        window.hide()

    def test_missing_import_preserves_previous_document(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        current_path = tmp_path / "current.fcstm"
        broken_path = tmp_path / "broken.fcstm"
        current_path.write_text("state Current;", encoding="utf-8")
        broken_path.write_text(
            'state Broken { import "./missing.fcstm" as Missing; }',
            encoding="utf-8",
        )
        current = window.document_service.load(current_path)
        window._set_active_document_session(current)
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (
                str(broken_path),
                "fcstm Files (*.fcstm)",
            ),
        )
        errors = []
        monkeypatch.setattr(
            QtWidgets.QMessageBox,
            "critical",
            lambda *args, **kwargs: errors.append(args),
        )

        operation = window._import_statechart()
        qtbot.waitUntil(lambda: operation.result is not None, timeout=3000)

        assert operation.result.status is main_window.TaskStatus.FAILED
        assert window.document_session is current
        assert window.state_manager.root_state.name == "Current"
        assert window.source_editor.toPlainText() == "state Current;"
        assert errors and errors[0][1] == "依赖加载失败"
        assert isinstance(
            operation.result.error,
            main_window.DocumentDependencyLoadError,
        )
        assert operation.result.error.path == str(
            (tmp_path / "missing.fcstm").resolve()
        )
        assert operation.result.error.operation == "read"

    def test_loaded_document_validation_and_dsl_export_use_source_authority(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / "authority.fcstm"
        original = "// exact\nstate Root { state A; [*] -> A; A -> [*]; }\n"
        source.write_text(original, encoding="utf-8")
        original_bytes = source.read_bytes()
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
        assert exported.read_bytes() == original_bytes

    def test_loaded_form_insertions_commit_local_text_edits(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / "forms.fcstm"
        source.write_text(
            "def int x = 0;\nstate Root { state A; [*] -> A; A -> [*]; }",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(source), "fcstm Files (*.fcstm)"),
        )
        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            window._import_statechart()

        class StateDialog:
            def __init__(self, *args, **kwargs):
                pass

            def exec_(self):
                return QtWidgets.QDialog.Accepted

            def get_state_name(self):
                return "B"

        monkeypatch.setattr(main_window, "DialogEditState", StateDialog)
        root_item = window.tree_all_state.topLevelItem(0)
        window.tree_all_state.setCurrentItem(root_item)
        window._add_state(window.state_manager.root_state, False)
        assert "state B;" in window.document_session.source_text
        assert window.document_session.source_revision == 1

        class TransitionDialog:
            def __init__(self, *args, **kwargs):
                assert kwargs["mutate_model"] is False

            def exec_(self):
                return QtWidgets.QDialog.Accepted

            def get_transition_data(self):
                return {
                    "source": "A",
                    "target": "B",
                    "event": "",
                    "condition": "",
                    "action": "",
                }

        monkeypatch.setattr(main_window, "DialogAddTransition", TransitionDialog)
        root_item = window.tree_all_state.topLevelItem(0)
        window.tree_all_state.setCurrentItem(root_item)
        window._on_button_transition_clicked()
        assert "A -> B;" in window.document_session.source_text
        assert window.document_session.source_revision == 2
        state_b = window.state_manager.get_state_by_path("Root.B")
        assert window._rename_projected_state(state_b, "C")
        assert "state C;" in window.document_session.source_text
        assert "A -> C;" in window.document_session.source_text
        assert window.document_session.source_revision == 3

        class LifecycleDialog:
            def __init__(self, *args, **kwargs):
                assert kwargs["mutate_model"] is False

            def exec_(self):
                return QtWidgets.QDialog.Accepted

            def get_lifecycle_data(self):
                return {
                    "type": "enter",
                    "name": "",
                    "action": "",
                    "is_abstract": False,
                    "comment": "",
                }

        monkeypatch.setattr(main_window, "DialogAddLifecycle", LifecycleDialog)
        root_item = window.tree_all_state.topLevelItem(0)
        window.tree_all_state.setCurrentItem(root_item)
        window._on_button_lifecycle_clicked()
        assert "enter {}" in window.document_session.source_text
        assert window.document_session.source_revision == 4
        assert window.document_session.current_valid_snapshot is not None
        window.edit_var_def.setPlainText("def int x = 1;")
        assert window._commit_variable_editor()
        assert window.document_session.source_revision == 5
        assert "def int x = 1;" in window.document_session.source_text
        state_c = window.state_manager.get_state_by_path("Root.C")
        assert window._delete_projected_state(state_c)
        assert "state C;" not in window.document_session.source_text
        assert "A -> C;" not in window.document_session.source_text
        assert window.document_session.source_revision == 6

    def test_loaded_projection_modify_delete_and_import_read_only(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        child = tmp_path / "child.fcstm"
        source = tmp_path / "modify.fcstm"
        child.write_text(
            "state Child { state C; [*] -> C; C -> [*]; }",
            encoding="utf-8",
        )
        source.write_text(
            'state Root { import "./child.fcstm" as Imported; '
            "enter {} state A; state B; [*] -> A; A -> B; "
            "B -> Imported; Imported -> [*]; }",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(source), "fcstm Files (*.fcstm)"),
        )
        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            window._import_statechart()
        warnings = []
        monkeypatch.setattr(
            QtWidgets.QMessageBox,
            "warning",
            lambda *args, **kwargs: warnings.append(args),
        )

        root = window.state_manager.root_state
        transition = next(
            item
            for item in root.transitions
            if item["source"] == "A" and item["target"] == "B"
        )
        assert window._replace_projected_declaration(
            transition, "A -> [*];"
        )
        assert "A -> [*];" in window.document_session.source_text

        root = window.state_manager.root_state
        lifecycle = root.lifecycle[0]
        assert window._replace_projected_declaration(lifecycle, "exit {}"), warnings
        root = window.state_manager.root_state
        assert window._delete_projected_declaration(root.lifecycle[0])
        assert "exit {}" not in window.document_session.source_text

        imported = window.state_manager.get_state_by_path("Root.Imported")
        imported_transition = imported.transitions[0]
        before = window.document_session
        assert not window._replace_projected_declaration(
            imported_transition, "[*] -> C;"
        )
        assert window.document_session is before
        assert warnings

    def test_invalid_form_candidate_leaves_session_and_projection_unchanged(
        self, monkeypatch, window, tmp_path
    ):
        source = tmp_path / "form.fcstm"
        source.write_text(
            "state Root { state A; [*] -> A; A -> [*]; }",
            encoding="utf-8",
        )
        session = window.document_service.load(source)
        window._set_active_document_session(session)
        before_session = window.document_session
        before_manager = window.state_manager
        state_a = before_manager.get_state_by_path("Root.A")
        warnings = []
        monkeypatch.setattr(
            QtWidgets.QMessageBox,
            "warning",
            lambda *args, **kwargs: warnings.append(args),
        )

        changed = window._replace_projected_declaration(
            {"source_ref": state_a.source_ref}, "state ;"
        )

        assert not changed
        assert window.document_session is before_session
        assert window.state_manager is before_manager
        assert window.source_editor.toPlainText() == before_session.source_text
        assert warnings and warnings[0][1] == "编辑未应用"

    def test_composite_state_rename_is_source_editor_only_and_non_mutating(
        self, monkeypatch, window, tmp_path
    ):
        source = tmp_path / "composite.fcstm"
        source.write_text(
            "state Root { state Group { state A; [*] -> A; A -> [*]; } "
            "[*] -> Group; Group -> [*]; }",
            encoding="utf-8",
        )
        session = window.document_service.load(source)
        window._set_active_document_session(session)
        group = window.state_manager.get_state_by_path("Root.Group")
        warnings = []
        monkeypatch.setattr(
            QtWidgets.QMessageBox,
            "warning",
            lambda *args, **kwargs: warnings.append(args),
        )

        changed = window._rename_projected_state(group, "Renamed")

        assert not changed
        assert window.document_session is session
        assert "state Group" in window.document_session.source_text
        assert "Renamed" not in window.document_session.source_text
        assert warnings and warnings[0][1] == "暂不支持"

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
