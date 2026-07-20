import threading
from dataclasses import replace

import pytest
from PyQt5 import QtCore, QtGui, QtWidgets

from app.model import State, StateManager
from app.model.session import ValidationState
from app.source import SourceDocument
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

    def test_source_editor_uses_four_space_tab_width(self, window):
        metrics = QtGui.QFontMetricsF(window.source_editor.font())
        expected = metrics.horizontalAdvance(" ") * 4
        assert abs(window.source_editor.tabStopDistance() - expected) < 0.5

    def test_new_state_button_text_fits_compact_model_explorer(
        self, qtbot, window
    ):
        qtbot.mouseClick(
            window.button_initial_new_state_machine,
            QtCore.Qt.LeftButton,
        )
        window.resize(1280, 720)
        window.show()
        QtWidgets.QApplication.processEvents()

        text_width = window.button_add_state.fontMetrics().horizontalAdvance(
            window.button_add_state.text()
        )
        assert window.button_add_state.text() == "新建状态"
        assert window.button_add_state.width() >= text_width + 20
        button_rect = window.button_add_state.rect()
        visible_rect = window.button_add_state.visibleRegion().boundingRect()
        assert visible_rect.contains(button_rect)
        assert window.button_add_state.geometry().right() <= (
            window.widget_state_add_state.contentsRect().right()
        )

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
        window.workspace_tabs.setCurrentWidget(window.source_workspace)
        original_manager = window.state_manager
        critical_messages = []
        monkeypatch.setattr(
            QtWidgets.QMessageBox,
            "critical",
            lambda *args, **kwargs: critical_messages.append(args),
        )

        with qtbot.waitSignal(window.document_validation_finished, timeout=3000):
            window.source_editor.setPlainText("state Broken {")

        assert window.document_session.source_revision == 1
        assert window.document_session.validation_state is ValidationState.INVALID_SYNTAX
        assert window.document_session.last_valid_snapshot.source_revision == 0
        assert window.state_manager is original_manager
        assert window.state_manager.root_state.name == "Root"
        assert window.workspace_tabs.currentWidget() is window.source_workspace
        assert not window.action_graph_gen.isEnabled()

        fixed = "state Fixed { state A; [*] -> A; A -> [*]; }"
        with qtbot.waitSignal(window.document_validation_finished, timeout=3000):
            window.source_editor.setPlainText(fixed)

        assert window.document_session.source_revision == 2
        assert window.document_session.validated_revision == 2
        assert window.state_manager.root_state.name == "Fixed"
        assert window.workspace_tabs.currentWidget() is window.source_workspace
        assert window.action_graph_gen.isEnabled()
        assert not critical_messages

    def test_source_refresh_button_reports_invalid_source(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / "refresh.fcstm"
        source.write_text(
            "state Root { state A; [*] -> A; A -> [*]; }",
            encoding="utf-8",
        )
        window._set_active_document_session(window.document_service.load(source))
        window.workspace_tabs.setCurrentWidget(window.source_workspace)
        warnings = []
        monkeypatch.setattr(
            QtWidgets.QMessageBox,
            "warning",
            lambda *args, **kwargs: warnings.append(args),
        )

        with qtbot.waitSignal(window.document_validation_finished, timeout=3000):
            window.source_editor.setPlainText("state Broken {")
        with qtbot.waitSignal(window.document_validation_finished, timeout=3000):
            qtbot.mouseClick(
                window.source_refresh_button, QtCore.Qt.LeftButton
            )

        assert warnings
        assert warnings[-1][1] == "刷新失败"
        assert "未通过完整校验" in warnings[-1][2]
        assert window.state_manager.root_state.name == "Root"
        assert window.workspace_tabs.currentWidget() is window.source_workspace

    def test_variable_editor_commit_preserves_cursor_and_focus(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / "variables.fcstm"
        source.write_text(
            "def int a = 0;\nstate Root;",
            encoding="utf-8",
        )
        window._set_active_document_session(window.document_service.load(source))
        window.show()
        window.edit_var_def.setFocus()
        cursor = window.edit_var_def.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        cursor.insertText("\ndef int b = 1;")
        window.edit_var_def.setTextCursor(cursor)
        warnings = []
        monkeypatch.setattr(
            QtWidgets.QMessageBox,
            "warning",
            lambda *args, **kwargs: warnings.append(args),
        )

        qtbot.waitUntil(
            lambda: window.document_session.source_revision == 1,
            timeout=3000,
        )

        assert window.edit_var_def.textCursor().position() == len(
            window.edit_var_def.toPlainText()
        )
        assert window.edit_var_def.hasFocus()
        assert window.document_session.current_valid_snapshot is not None
        assert window.edit_var_def.toPlainText().endswith("def int b = 1;")
        assert not warnings
        window.hide()

    def test_initially_invalid_source_can_be_repaired_and_validated(
        self, qtbot, window, tmp_path
    ):
        source = tmp_path / "repair.fcstm"
        source.write_text("state Broken {", encoding="utf-8")
        invalid = window.document_service.load(source)
        assert invalid.last_valid_snapshot is None
        window._set_active_document_session(invalid)

        fixed = "state Fixed { state A; [*] -> A; A -> [*]; }"
        with qtbot.waitSignal(
            window.document_validation_finished, timeout=3000
        ) as blocker:
            window.source_editor.setPlainText(fixed)

        result = blocker.args[0]
        assert result.status is main_window.TaskStatus.SUCCESS
        assert window.document_session.source_text == fixed
        assert window.document_session.current_valid_snapshot is not None
        assert window.document_session.last_valid_snapshot.source_revision == 1
        assert window.document_session.validation_state is ValidationState.VALID
        assert window.state_manager.root_state.name == "Fixed"

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

        assert window.document_session.document_version == 1
        assert window.document_revision_label.text() == "版本 1"

        changed = "// same unsaved version\nstate Root { state A; [*] -> A; A -> [*]; }\n"
        with qtbot.waitSignal(window.document_validation_finished, timeout=3000):
            window.source_editor.setPlainText(changed)

        assert window.document_session.dirty
        assert window.document_session.source_revision == 2
        assert window.document_session.document_version == 1
        assert window.document_revision_label.text() == "版本 1"
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

        with qtbot.waitSignal(window.model_check_finished, timeout=3000) as blocker:
            handle = window._validate_statechart()
        result = blocker.args[0]

        assert handle.stamp.task_id == result.stamp.task_id
        assert result.value["root_state_path"] == "Root"
        assert messages == []
        record = next(
            item
            for item in window.task_center.records
            if item.task_id == handle.stamp.task_id
        )
        assert record.kind == "model-check"
        assert record.status is main_window.HistoryTaskStatus.SUCCESS
        assert record.session_id == window.document_session.session_id
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

    def test_form_edit_marks_running_model_check_stale(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / "stale-model-check.fcstm"
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

        original_require = window.document_service.require_current_valid_snapshot
        worker_started = threading.Event()
        release_worker = threading.Event()
        calls = []

        def controlled_require(session):
            calls.append((threading.current_thread().ident, session.source_revision))
            if threading.current_thread() is not threading.main_thread():
                worker_started.set()
                assert release_worker.wait(3)
            return original_require(session)

        monkeypatch.setattr(
            window.document_service,
            "require_current_valid_snapshot",
            controlled_require,
        )
        results = []
        window.model_check_finished.connect(results.append)
        handle = window._validate_statechart()
        qtbot.waitUntil(worker_started.is_set, timeout=3000)
        state = window.state_manager.get_state_by_path("Root.A")
        assert window._rename_projected_state(state, "Ready")
        assert window.document_session.source_revision == 1
        release_worker.set()
        qtbot.waitUntil(lambda: len(results) == 1, timeout=3000)

        assert results[0].status is main_window.TaskStatus.STALE
        assert handle.result.status is main_window.TaskStatus.STALE
        record = next(
            item
            for item in window.task_center.records
            if item.task_id == handle.stamp.task_id
        )
        assert record.status is main_window.HistoryTaskStatus.STALE
        assert record.source_revision == 0
        assert window.document_session.source_revision == 1

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

    def test_form_edit_undo_redo_restores_source_projection_and_unique_revisions(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / "undo.fcstm"
        original = "state Root { state A; [*] -> A; A -> [*]; }"
        source.write_text(original, encoding="utf-8")
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
        root = window.state_manager.root_state
        window._add_state(root, False)

        changed = window.document_session.source_text
        assert "state B;" in changed
        assert window.document_session.source_revision == 1
        assert window.command_stack.can_undo
        assert window.action_undo.isEnabled()
        window.tree_all_state.setFocus()

        assert window._undo_document()
        assert window.document_session.source_revision == 2
        assert window.document_session.source_text == original
        assert window.state_manager.get_state_by_path("Root.B") is None
        assert window.command_stack.can_redo
        assert window.action_redo.isEnabled()

        assert window._redo_document()
        assert window.document_session.source_revision == 3
        assert window.document_session.source_text == changed
        assert window.state_manager.get_state_by_path("Root.B") is not None
        assert window.document_session.dirty

    def test_direct_source_edit_and_new_load_clear_form_command_history(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        first = tmp_path / "first.fcstm"
        second = tmp_path / "second.fcstm"
        first.write_text(
            "state First { state A; [*] -> A; A -> [*]; }",
            encoding="utf-8",
        )
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
        state = window.state_manager.get_state_by_path("First.A")
        assert window._rename_projected_state(state, "Ready")
        assert window.command_stack.can_undo

        with qtbot.waitSignal(window.document_validation_finished, timeout=3000):
            window.source_editor.setPlainText(
                window.document_session.source_text.replace("Ready", "Running")
            )
        assert not window.command_stack.can_undo
        monkeypatch.setattr(
            QtWidgets.QMessageBox,
            "question",
            lambda *args, **kwargs: QtWidgets.QMessageBox.Discard,
        )

        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            window._import_statechart()
        assert window.document_session.path == str(second.resolve())
        assert not window.command_stack.can_undo
        assert not window.command_stack.can_redo

    def test_load_task_is_persistent_and_debounce_validation_is_transient(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / "tasks.fcstm"
        source.write_text("state Tasks;", encoding="utf-8")
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(source), "fcstm Files (*.fcstm)"),
        )
        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            operation = window._import_statechart()

        loads = [
            record
            for record in window.task_center.records
            if record.kind == "document-load"
        ]
        assert len(loads) == 1
        assert loads[0].task_id == operation.operation_id
        assert loads[0].status is main_window.HistoryTaskStatus.SUCCESS
        assert loads[0].session_id == window.document_session.session_id
        assert loads[0].source_revision == window.document_session.source_revision
        assert loads[0].dependency_fingerprints == dict(
            window.document_session.current_valid_snapshot.dependency_manifest
        )
        assert window.task_result_dock.table.rowCount() == 1

        with qtbot.waitSignal(window.document_validation_finished, timeout=3000):
            window.source_editor.setPlainText("state TasksChanged;")
        assert all(
            record.kind != "document-validate"
            for record in window.task_center.records
        )

    def test_superseded_debounce_validation_releases_transient_record(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / "supersede-validation.fcstm"
        source.write_text("state Initial;", encoding="utf-8")
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(source), "fcstm Files (*.fcstm)"),
        )
        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            window._import_statechart()
        original_validate = window.document_service.validate
        first_started = threading.Event()
        release_first = threading.Event()
        calls = []

        def controlled_validate(session):
            calls.append(session.source_text)
            if len(calls) == 1:
                first_started.set()
                assert release_first.wait(3)
            return original_validate(session)

        monkeypatch.setattr(
            window.document_service, "validate", controlled_validate
        )
        results = []
        window.document_validation_finished.connect(results.append)
        window.source_editor.setPlainText("state First;")
        qtbot.waitUntil(first_started.is_set, timeout=3000)
        window.source_editor.setPlainText("state Latest;")
        release_first.set()
        qtbot.waitUntil(lambda: len(results) == 2, timeout=3000)

        assert window.document_session.source_text == "state Latest;"
        assert window.document_session.current_valid_snapshot is not None
        assert all(
            record.kind != "document-validate"
            for record in window.task_center.records
        )

    def test_load_history_write_failure_is_nonblocking_and_cleans_operation(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / "history-write.fcstm"
        source.write_text("state HistoryWrite;", encoding="utf-8")
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(source), "fcstm Files (*.fcstm)"),
        )
        monkeypatch.setattr(
            window.task_center,
            "_write",
            lambda encoded: (_ for _ in ()).throw(OSError("disk full")),
        )
        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            operation = window._import_statechart()

        assert operation.result.status is main_window.TaskStatus.SUCCESS
        assert operation.operation_id not in window._logical_load_operations
        record = next(
            item
            for item in window.task_center.records
            if item.task_id == operation.operation_id
        )
        assert record.status is main_window.HistoryTaskStatus.SUCCESS
        assert "任务历史写入失败" in window.statusbar.currentMessage()

    def test_load_submit_failure_finishes_logical_operation_and_history(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / "submit-failure.fcstm"
        source.write_text("state SubmitFailure;", encoding="utf-8")
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(source), "fcstm Files (*.fcstm)"),
        )
        monkeypatch.setattr(
            window.task_runner,
            "submit",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("runner stopped")
            ),
        )
        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            operation = window._import_statechart()

        assert operation.result.status is main_window.TaskStatus.FAILED
        assert operation.operation_id not in window._logical_load_operations
        record = next(
            item
            for item in window.task_center.records
            if item.task_id == operation.operation_id
        )
        assert record.status is main_window.HistoryTaskStatus.FAILED
        assert "runner stopped" in "\n".join(record.exception_chain)

    def test_save_updates_command_baseline_before_direct_and_form_edits(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / "baseline.fcstm"
        source.write_text(
            "state Original { state A; [*] -> A; A -> [*]; }",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(source), "fcstm Files (*.fcstm)"),
        )
        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            window._import_statechart()
        state = window.state_manager.get_state_by_path("Original.A")
        assert window._rename_projected_state(state, "Saved")
        assert window._save_current_document()
        assert "state Saved;" in source.read_text(encoding="utf-8")

        with qtbot.waitSignal(window.document_validation_finished, timeout=3000):
            window.source_editor.setPlainText(
                window.document_session.source_text.replace("Saved", "Direct")
            )
        state = window.state_manager.get_state_by_path("Original.Direct")
        assert window._rename_projected_state(state, "A")

        assert window.document_session.dirty
        assert "state A;" in window.document_session.source_text
        assert "state Saved;" in source.read_text(encoding="utf-8")

    def test_retry_respects_dirty_replacement_gate_and_rejects_redacted_path(
        self, monkeypatch, window, tmp_path
    ):
        current_path = tmp_path / "current.fcstm"
        retry_path = tmp_path / "retry.fcstm"
        current_path.write_text("state Current;", encoding="utf-8")
        retry_path.write_text("state Retry;", encoding="utf-8")
        current = window.document_service.load(current_path)
        dirty = window.document_service.replace_source_text(
            current, "state Dirty;"
        )
        window._set_active_document_session(dirty)
        record = main_window.TaskRecord(
            task_id="retry",
            kind="document-load",
            session_id="",
            source_revision=0,
            dependency_fingerprints={},
            created_at=1.0,
            started_at=1.0,
            finished_at=2.0,
            status=main_window.HistoryTaskStatus.FAILED,
            summary="failed",
            messages=(),
            artifacts=(),
            retry_descriptor={
                "kind": "document-load",
                "path": str(retry_path),
                "encoding": None,
                "encoding_hints": [],
            },
            exception_chain=(),
            boundary=main_window.TaskBoundary.EXPLICIT,
        )
        prompts = []
        monkeypatch.setattr(
            QtWidgets.QMessageBox,
            "question",
            lambda *args, **kwargs: (
                prompts.append(args),
                QtWidgets.QMessageBox.Cancel,
            )[1],
        )

        assert window._retry_task_record(record) is None
        assert prompts
        assert window.document_session is dirty
        assert window._logical_load_operations == {}

        redacted = replace(
            record,
            retry_descriptor={
                "kind": "document-load",
                "path": "<WORKSPACE>/retry.fcstm",
            },
        )
        prompts.clear()
        assert window._retry_task_record(redacted) is None
        assert prompts == []

    def test_running_load_can_be_cancelled_without_replacing_session(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        current_path = tmp_path / "current.fcstm"
        incoming_path = tmp_path / "incoming.fcstm"
        current_path.write_text("state Current;", encoding="utf-8")
        incoming_path.write_text("state Incoming;", encoding="utf-8")
        current = window.document_service.load(current_path)
        window._set_active_document_session(current)
        original_load = window.document_service.load
        worker_started = threading.Event()
        release_worker = threading.Event()

        def controlled_load(path, *args, **kwargs):
            if str(path) == str(incoming_path):
                worker_started.set()
                assert release_worker.wait(3)
            return original_load(path, *args, **kwargs)

        monkeypatch.setattr(window.document_service, "load", controlled_load)
        operation = window._start_document_load(str(incoming_path))
        qtbot.waitUntil(worker_started.is_set, timeout=3000)

        window.task_result_dock.refresh()
        row = next(
            row
            for row, record in enumerate(window.task_result_dock._visible_records)
            if record.task_id == operation.operation_id
        )
        qtbot.mouseClick(
            window.task_result_dock.table.cellWidget(row, 5),
            QtCore.Qt.LeftButton,
        )
        cancelling = next(
            item
            for item in window.task_center.records
            if item.task_id == operation.operation_id
        )
        assert cancelling.status is main_window.HistoryTaskStatus.CANCEL_REQUESTED
        assert cancelling.summary == "正在取消加载"
        release_worker.set()
        qtbot.waitUntil(lambda: operation.result is not None, timeout=3000)

        assert operation.result.status is main_window.TaskStatus.CANCELLED
        assert window.document_session is current
        completed = next(
            item
            for item in window.task_center.records
            if item.task_id == operation.operation_id
        )
        assert completed.status is main_window.HistoryTaskStatus.CANCELLED

    def test_failed_load_retry_creates_new_successful_task(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        retry_path = tmp_path / "created-after-failure.fcstm"
        monkeypatch.setattr(
            QtWidgets.QMessageBox, "critical", lambda *args, **kwargs: None
        )
        failed_operation = window._start_document_load(str(retry_path))
        qtbot.waitUntil(lambda: failed_operation.result is not None, timeout=3000)
        failed_record = next(
            item
            for item in window.task_center.records
            if item.task_id == failed_operation.operation_id
        )
        assert failed_record.status is main_window.HistoryTaskStatus.FAILED

        retry_path.write_text("state Retried;", encoding="utf-8")
        window.task_result_dock.refresh()
        row = next(
            row
            for row, record in enumerate(window.task_result_dock._visible_records)
            if record.task_id == failed_record.task_id
        )
        with qtbot.waitSignal(window.document_load_finished, timeout=3000) as blocker:
            qtbot.mouseClick(
                window.task_result_dock.table.cellWidget(row, 5),
                QtCore.Qt.LeftButton,
            )
        retry_outcome = blocker.args[0]
        assert retry_outcome.operation_id != failed_operation.operation_id
        assert retry_outcome.status is main_window.TaskStatus.SUCCESS
        assert window.document_session.path == str(retry_path.resolve())
        assert window.state_manager.root_state.name == "Retried"
        retried_record = next(
            item
            for item in window.task_center.records
            if item.task_id == retry_outcome.operation_id
        )
        assert retried_record.status is main_window.HistoryTaskStatus.SUCCESS

    def test_running_model_check_can_be_cancelled_then_retried(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / "cancel-check.fcstm"
        source.write_text(
            "state Root { state A; [*] -> A; A -> [*]; }", encoding="utf-8"
        )
        session = window.document_service.load(source)
        window._set_active_document_session(session)
        original_require = window.document_service.require_current_valid_snapshot
        worker_started = threading.Event()
        release_worker = threading.Event()

        def controlled_require(candidate):
            if threading.current_thread() is not threading.main_thread():
                worker_started.set()
                assert release_worker.wait(3)
            return original_require(candidate)

        monkeypatch.setattr(
            window.document_service,
            "require_current_valid_snapshot",
            controlled_require,
        )
        handle = window._validate_statechart()
        qtbot.waitUntil(worker_started.is_set, timeout=3000)

        window.task_result_dock.refresh()
        row = next(
            row
            for row, record in enumerate(window.task_result_dock._visible_records)
            if record.task_id == handle.stamp.task_id
        )
        qtbot.mouseClick(
            window.task_result_dock.table.cellWidget(row, 5),
            QtCore.Qt.LeftButton,
        )
        cancelling = next(
            item
            for item in window.task_center.records
            if item.task_id == handle.stamp.task_id
        )
        assert cancelling.status is main_window.HistoryTaskStatus.CANCEL_REQUESTED
        assert cancelling.summary == "正在取消模型检查"
        release_worker.set()
        qtbot.waitUntil(lambda: handle.result is not None, timeout=3000)
        assert handle.result.status is main_window.TaskStatus.CANCELLED
        assert window.document_session is session

        cancelled_record = next(
            item
            for item in window.task_center.records
            if item.task_id == handle.stamp.task_id
        )
        assert cancelled_record.status is main_window.HistoryTaskStatus.CANCELLED
        monkeypatch.setattr(
            window.document_service,
            "require_current_valid_snapshot",
            original_require,
        )
        window.task_result_dock.refresh()
        row = next(
            row
            for row, record in enumerate(window.task_result_dock._visible_records)
            if record.task_id == cancelled_record.task_id
        )
        with qtbot.waitSignal(window.model_check_finished, timeout=3000) as blocker:
            qtbot.mouseClick(
                window.task_result_dock.table.cellWidget(row, 5),
                QtCore.Qt.LeftButton,
            )
        retried = blocker.args[0]
        assert retried.stamp.task_id != handle.stamp.task_id
        assert retried.status is main_window.TaskStatus.SUCCESS

    def test_event_edit_save_and_fresh_reload_are_consistent(
        self, monkeypatch, window, tmp_path
    ):
        source = tmp_path / "event-save.fcstm"
        source.write_text(
            'state Root { event Go named "Before"; state A; [*] -> A; }',
            encoding="utf-8",
        )
        window._set_active_document_session(window.document_service.load(source))
        window.tree_all_state.setCurrentItem(window.tree_all_state.topLevelItem(0))
        monkeypatch.setattr(window, "_prompt_event", lambda *args: ("Run", "After"))
        monkeypatch.setattr(
            window, "_confirm_event_transaction", lambda *args: True
        )

        assert window._edit_event()
        assert window._save_current_document()
        fresh = main_window.DocumentService().load(source)
        events = window.event_service.list_events(fresh, ("Root",))

        assert [(item.name, item.display_name) for item in events] == [
            ("Run", "After")
        ]
        assert fresh.source_text == window.document_session.source_text

    def test_corrupt_history_warning_is_visible_and_dock_has_view_action(
        self, qtbot, tmp_path
    ):
        data_dir = tmp_path / "task-data"
        data_dir.mkdir()
        (data_dir / "task-history.json").write_text(
            "{broken-json", encoding="utf-8"
        )
        center = main_window.TaskCenter(
            data_location_provider=lambda: str(data_dir),
            now_provider=lambda: 10.0,
        )
        settings = QtCore.QSettings(
            str(tmp_path / "history.ini"), QtCore.QSettings.IniFormat
        )
        history_window = main_window.AppMainWindow(
            settings=settings, task_center=center
        )
        qtbot.addWidget(history_window)

        warnings = [
            record
            for record in center.records
            if record.kind == "task-history"
        ]
        assert len(warnings) == 1
        assert warnings[0].status is main_window.HistoryTaskStatus.FAILED
        assert history_window.task_result_dock.table.rowCount() == 1
        assert history_window.action_toggle_task_results.shortcut().toString()
        history_window.show()
        history_window.action_toggle_task_results.trigger()
        assert history_window.task_result_dock.isVisible()

    def test_event_component_crud_and_action_undo_redo_use_exact_source_refs(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / "events.fcstm"
        source.write_text(
            'state Root { state A { event Go named "Go Event"; state X; '
            "[*] -> X; X -> X : Go; } state B; [*] -> A; }",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(source), "fcstm Files (*.fcstm)"),
        )
        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            window._import_statechart()
        selected_items = window.tree_all_state.findItems(
            "A", QtCore.Qt.MatchExactly | QtCore.Qt.MatchRecursive
        )
        assert len(selected_items) == 1
        window.tree_all_state.setCurrentItem(selected_items[0])
        assert window.event_table.rowCount() == 1
        assert window.event_table.item(0, 0).text() == "Root.A"
        assert window.event_table.item(0, 1).text() == "Go"
        assert window.event_table.item(0, 3).text() == "declaration"
        assert window.event_table.item(0, 6).text() == "可编辑"
        assert window.event_table.item(0, 0).data(QtCore.Qt.UserRole)
        assert window.event_reference_table.rowCount() == 1
        assert window._open_event_reference_source(
            window.event_reference_table.item(0, 0)
        )
        assert window.workspace_tabs.currentWidget() is window.source_workspace
        assert window.source_editor.textCursor().selectedText().startswith("X -> X")
        window.workspace_tabs.setCurrentWidget(window.model_workspace)

        def assert_selected(path, event_name):
            selected = window._get_pro_state()
            assert selected is window.state_manager.get_state_by_path(path)
            assert selected.get_full_path() == path
            assert window.property_path_label.text() == "状态：{}".format(path)
            assert window.event_table.rowCount() >= 1
            assert window.event_table.item(0, 1).text() == event_name

        answers = [("Run", "Run Event"), ("Stop", "Stop Event")]
        monkeypatch.setattr(
            window, "_prompt_event", lambda *args, **kwargs: answers.pop(0)
        )
        monkeypatch.setattr(
            window, "_confirm_event_transaction", lambda *args: True
        )
        qtbot.mouseClick(window.event_edit_button, QtCore.Qt.LeftButton)
        renamed = window.document_session.source_text
        assert 'event Run named "Run Event";' in renamed
        assert "X -> X : Run;" in renamed
        assert window.document_session.source_revision == 1
        assert_selected("Root.A", "Run")

        window.event_table.setFocus()
        window.action_undo.trigger()
        assert window.document_session.source_revision == 2
        assert 'event Go named "Go Event";' in window.document_session.source_text
        assert "X -> X : Go;" in window.document_session.source_text
        assert_selected("Root.A", "Go")
        window.action_redo.trigger()
        assert window.document_session.source_revision == 3
        assert window.document_session.source_text == renamed
        assert_selected("Root.A", "Run")

        qtbot.mouseClick(window.event_add_button, QtCore.Qt.LeftButton)
        assert window.document_session.source_revision == 4
        assert 'event Stop named "Stop Event";' in window.document_session.source_text
        assert window._get_pro_state().get_full_path() == "Root.A"
        stop_row = next(
            row
            for row in range(window.event_table.rowCount())
            if window.event_table.item(row, 1).text() == "Stop"
        )
        window.event_table.selectRow(stop_row)
        monkeypatch.setattr(
            QtWidgets.QMessageBox,
            "question",
            lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
        )
        qtbot.mouseClick(window.event_delete_button, QtCore.Qt.LeftButton)
        assert window.document_session.source_revision == 5
        assert "event Stop" not in window.document_session.source_text
        assert window.event_table.rowCount() == 1

    def test_imported_event_is_read_only_and_opens_physical_source_tab(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        child = tmp_path / "child.fcstm"
        child.write_text(
            'state Child { event Go named "Child Go"; state A; state B; '
            "[*] -> A; A -> B : Go; }",
            encoding="utf-8",
        )
        source = tmp_path / "root.fcstm"
        source.write_text(
            'state Root { import "./child.fcstm" as First; [*] -> First; }',
            encoding="utf-8",
        )
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(source), "fcstm Files (*.fcstm)"),
        )
        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            window._import_statechart()
        imported_items = window.tree_all_state.findItems(
            "First", QtCore.Qt.MatchExactly | QtCore.Qt.MatchRecursive
        )
        assert imported_items
        window.tree_all_state.setCurrentItem(imported_items[0])

        assert window.event_table.rowCount() == 1
        assert window.event_table.item(0, 0).text() == "Root.First"
        assert window.event_table.item(0, 6).text() == "只读"
        assert window.event_reference_table.rowCount() == 1
        assert not window.event_edit_button.isEnabled()
        assert not window.event_delete_button.isEnabled()
        assert window.event_open_source_button.isEnabled()
        qtbot.mouseClick(
            window.event_open_source_button, QtCore.Qt.LeftButton
        )
        editor = window.workspace_tabs.currentWidget().findChild(
            QtWidgets.QPlainTextEdit, "imported_source_editor"
        )
        assert editor is not None
        assert editor.isReadOnly()
        assert editor.textCursor().selectedText().startswith("event Go")
        assert (
            window.workspace_tabs.currentWidget().property("source_uri")
            == SourceDocument.from_file(child).uri
        )

    def test_read_only_event_edit_offers_open_source(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        child = tmp_path / "child.fcstm"
        child.write_text(
            "state Child { event Go; state A; [*] -> A; }", encoding="utf-8"
        )
        source = tmp_path / "root.fcstm"
        source.write_text(
            'state Root { import "./child.fcstm" as Imported; [*] -> Imported; }',
            encoding="utf-8",
        )
        session = window.document_service.load(source)
        window._set_active_document_session(session)
        imported = window.tree_all_state.findItems(
            "Imported", QtCore.Qt.MatchExactly | QtCore.Qt.MatchRecursive
        )[0]
        window.tree_all_state.setCurrentItem(imported)
        monkeypatch.setattr(
            QtWidgets.QMessageBox,
            "question",
            lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
        )

        assert window._edit_event()
        editor = window.workspace_tabs.currentWidget().findChild(
            QtWidgets.QPlainTextEdit, "imported_source_editor"
        )
        assert editor.textCursor().selectedText().startswith("event Go")
        assert window.workspace_tabs.currentWidget().property(
            "source_uri"
        ) == SourceDocument.from_file(child).uri

    def test_imported_event_source_is_keyboard_reachable(
        self, qtbot, window, tmp_path
    ):
        child = tmp_path / "keyboard-child.fcstm"
        child.write_text(
            "state Child { event Go; state A; [*] -> A; }", encoding="utf-8"
        )
        source = tmp_path / "keyboard-root.fcstm"
        source.write_text(
            'state Root { import "./keyboard-child.fcstm" as Imported; '
            "[*] -> Imported; }",
            encoding="utf-8",
        )
        window._set_active_document_session(window.document_service.load(source))
        item = window.tree_all_state.findItems(
            "Imported", QtCore.Qt.MatchExactly | QtCore.Qt.MatchRecursive
        )[0]
        window.tree_all_state.setCurrentItem(item)
        window.show()
        window.activateWindow()
        QtWidgets.QApplication.processEvents()
        window.workspace_tabs.setCurrentWidget(window.model_workspace)
        window.event_table.setFocus()
        QtWidgets.QApplication.processEvents()

        qtbot.keyClick(window.event_table, QtCore.Qt.Key_Return, QtCore.Qt.ControlModifier)

        editor = window.workspace_tabs.currentWidget().findChild(
            QtWidgets.QPlainTextEdit, "imported_source_editor"
        )
        assert editor is not None
        assert editor.hasFocus()
        assert editor.textCursor().selectedText().startswith("event Go")
        window.hide()

    def test_import_mapping_delete_conflict_offers_keyboard_open_source(
        self, monkeypatch, window, tmp_path
    ):
        child = tmp_path / "mapping-child.fcstm"
        child.write_text(
            "state Child { event Go; state A; [*] -> A; }", encoding="utf-8"
        )
        source = tmp_path / "mapping-root.fcstm"
        original = (
            'state Root { event Target; import "./mapping-child.fcstm" as Mod { '
            "event /Go -> Target; } [*] -> Mod; }"
        )
        source.write_text(original, encoding="utf-8")
        window._set_active_document_session(window.document_service.load(source))
        window.tree_all_state.setCurrentItem(window.tree_all_state.topLevelItem(0))
        prompts = []
        monkeypatch.setattr(
            QtWidgets.QMessageBox,
            "question",
            lambda *args, **kwargs: (
                prompts.append(args), QtWidgets.QMessageBox.Yes
            )[1],
        )

        assert not window._delete_event()
        assert "import 事件映射" in prompts[0][2]
        assert window.document_session.source_text == original
        assert window.workspace_tabs.currentWidget() is window.source_workspace
        assert window.source_editor.textCursor().selectedText() == "Target"
        assert window.event_reference_table.item(0, 0).text() == "import 映射"

    def test_event_transaction_preview_shows_before_after_and_location(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / "preview.fcstm"
        source.write_text(
            'state Root { event Go named "Before"; state A; [*] -> A; }',
            encoding="utf-8",
        )
        session = window.document_service.load(source)
        window._set_active_document_session(session)
        window.tree_all_state.setCurrentItem(window.tree_all_state.topLevelItem(0))
        monkeypatch.setattr(
            window, "_prompt_event", lambda *args: ("Run", "After")
        )
        observed = {}

        def inspect_preview(dialog):
            observed["location"] = dialog.findChild(
                QtWidgets.QLabel, "event_transaction_location"
            ).text()
            observed["summary"] = dialog.findChild(
                QtWidgets.QLabel, "event_transaction_summary"
            ).text()
            observed["before"] = dialog.findChild(
                QtWidgets.QPlainTextEdit, "event_transaction_before"
            ).toPlainText()
            observed["after"] = dialog.findChild(
                QtWidgets.QPlainTextEdit, "event_transaction_after"
            ).toPlainText()
            return QtWidgets.QDialog.Accepted

        monkeypatch.setattr(QtWidgets.QDialog, "exec_", inspect_preview)

        assert window._edit_event()
        assert "声明位置：1:" in observed["location"]
        assert "项源码修改" in observed["summary"]
        assert 'event Go named "Before";' in observed["before"]
        assert 'event Run named "After";' in observed["after"]
        assert 'event Run named "After";' in window.document_session.source_text

    def test_source_navigation_uses_qt_offsets_after_emoji_prefix(
        self, qtbot, window, tmp_path
    ):
        source = tmp_path / "emoji.fcstm"
        source.write_text(
            '// emoji 😀\nstate Root { event Go; state A; [*] -> A; }',
            encoding="utf-8",
        )
        session = window.document_service.load(source, encoding="utf-8")
        window._set_active_document_session(session)
        window.tree_all_state.setCurrentItem(window.tree_all_state.topLevelItem(0))

        assert window._open_event_source()
        assert window.source_editor.textCursor().selectedText().startswith("event Go")

    def test_referenced_event_delete_requires_explicit_transition_deletion(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / "delete-event.fcstm"
        source.write_text(
            "state Root { event Go; state A; state B; "
            "[*] -> A; A -> B : Go; }",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(source), "fcstm Files (*.fcstm)"),
        )
        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            window._import_statechart()
        window.tree_all_state.setCurrentItem(window.tree_all_state.topLevelItem(0))

        answers = iter((QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.Yes))
        monkeypatch.setattr(
            QtWidgets.QMessageBox,
            "question",
            lambda *args, **kwargs: next(answers),
        )
        monkeypatch.setattr(
            window, "_confirm_event_transaction", lambda *args: True
        )
        qtbot.mouseClick(window.event_delete_button, QtCore.Qt.LeftButton)
        assert "event Go;" in window.document_session.source_text
        assert "A -> B : Go;" in window.document_session.source_text

        qtbot.mouseClick(window.event_delete_button, QtCore.Qt.LeftButton)
        assert "event Go;" not in window.document_session.source_text
        assert "A -> B : Go;" not in window.document_session.source_text
        assert "[*] -> A;" in window.document_session.source_text

    def test_workbench_shell_uses_left_right_bottom_docks_and_central_tabs(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / "workbench.fcstm"
        source.write_text("state Workbench;", encoding="utf-8")
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(source), "fcstm Files (*.fcstm)"),
        )
        window.resize(1280, 720)
        window.show()
        QtWidgets.QApplication.processEvents()
        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            window._import_statechart()
        QtWidgets.QApplication.processEvents()

        assert (
            window.dockWidgetArea(window.model_explorer_dock)
            == QtCore.Qt.LeftDockWidgetArea
        )
        assert (
            window.dockWidgetArea(window.property_inspector_dock)
            == QtCore.Qt.RightDockWidgetArea
        )
        assert (
            window.dockWidgetArea(window.task_result_dock)
            == QtCore.Qt.BottomDockWidgetArea
        )
        assert window.model_explorer_dock.isVisible()
        assert window.property_inspector_dock.isVisible()
        assert window.workspace_tabs.width() >= 700
        assert window.model_explorer_dock.width() <= 240
        assert window.property_inspector_dock.width() <= 300
        assert window.tree_all_state.currentItem() is window.tree_all_state.topLevelItem(0)
        assert window.property_path_label.text() == "状态：Workbench"
        assert window.model_explorer_dock.isAncestorOf(window.tree_all_state)
        assert window.model_workspace.isAncestorOf(window.frame_state_machine_info)
        assert window.source_workspace.isAncestorOf(window.source_editor)
        assert window.model_scroll_area.isVisible()
        assert window.event_table.minimumHeight() >= 90
        assert window.event_reference_table.minimumHeight() >= 90
        assert window.event_group.layout().sizeConstraint() == (
            QtWidgets.QLayout.SetMinimumSize
        )
        assert window.event_table.height() >= 60
        assert window.event_reference_table.height() >= 60
        assert not window.task_result_dock.isVisible()
        window.action_toggle_task_results.trigger()
        QtWidgets.QApplication.processEvents()
        assert window.task_result_dock.isVisible()
        qtbot.waitUntil(
            lambda: window.task_result_dock.widget().height() <= 220,
            timeout=1000,
        )
        assert 150 <= window.task_result_dock.widget().height() <= 220
        # Native dock title bars differ by platform (macOS adds about 19 px).
        assert window.task_result_dock.height() <= 260
        assert [
            window.workspace_tabs.tabText(index)
            for index in range(6)
        ] == ["模型", "源码", "图形", "检查", "普通仿真", "动态验证"]
        assert window.task_result_dock.sizeHint().height() <= 220
        assert window.width() >= 1280 and window.height() >= 720

    def test_workbench_structure_is_owned_by_generated_ui(
        self, monkeypatch, qtbot, tmp_path
    ):
        monkeypatch.setattr(
            main_window.AppMainWindow, "_init_workbench_layout", lambda self: None
        )
        settings = QtCore.QSettings(
            str(tmp_path / "static-ui.ini"), QtCore.QSettings.IniFormat
        )
        static_window = main_window.AppMainWindow(settings=settings)
        qtbot.addWidget(static_window)

        assert static_window.workspace_tabs is static_window.workbench_tabs
        assert static_window.frame_all_state is static_window.model_explorer_panel
        assert static_window.model_workspace.isAncestorOf(
            static_window.frame_state_machine_info
        )
        assert static_window.source_workspace.isAncestorOf(
            static_window.source_editor
        )
        assert static_window.findChild(QtWidgets.QDockWidget, "source_dock") is None
        for object_name in (
            "document_status_strip",
            "workbench_tabs",
            "model_workspace",
            "model_scroll_area",
            "model_scroll_content",
            "source_workspace",
            "graph_workspace",
            "diagnostics_workspace",
            "simulation_workspace",
            "dynamic_validation_workspace",
            "source_editor",
            "model_explorer_dock",
            "model_explorer_panel",
            "property_inspector_dock",
            "property_inspector",
        ):
            assert len(static_window.findChildren(QtCore.QObject, object_name)) == 1

    def test_core_workbench_controls_have_accessible_names_and_tooltips(
        self, window
    ):
        for widget in (
            window.tree_all_state,
            window.edit_var_def,
            window.table_lifecycle,
            window.table_transition,
            window.button_initial_import_state_machine,
            window.button_initial_new_state_machine,
            window.button_fold_all_state,
            window.button_expand_all_state,
        ):
            assert widget.accessibleName()
            assert widget.toolTip()
        for table in (
            window.table_lifecycle,
            window.table_transition,
            window.event_table,
            window.event_reference_table,
            window.task_result_dock.table,
        ):
            assert all(
                table.horizontalHeaderItem(column).text()
                for column in range(table.columnCount())
            )

    def test_core_keyboard_actions_accessibility_and_tab_order(self, qtbot, window):
        for button in (
            window.button_add_state,
            window.button_lifecycle,
            window.button_transition,
            window.button_fold_all_state,
            window.button_expand_all_state,
        ):
            assert button.accessibleName()
            assert button.toolTip()
        for button in window.findChildren(QtWidgets.QAbstractButton):
            if not button.icon().isNull():
                assert button.accessibleName(), button.objectName()
                assert button.toolTip(), button.objectName()

        assert window.action_import_state_machine.shortcut() == QtGui.QKeySequence.Open
        assert window.action_find.shortcut() == QtGui.QKeySequence.Find
        assert window.action_validate_state_machine.shortcut().toString() == "F5"
        assert window.action_stop_task.shortcut().toString() == "Shift+F5"
        assert window.action_open_event_source.shortcut().toString() == "Ctrl+Return"
        assert window.button_add_state.nextInFocusChain() is window.button_fold_all_state
        assert window.button_fold_all_state.nextInFocusChain() is window.button_expand_all_state

        window.show()
        window.activateWindow()
        QtWidgets.QApplication.processEvents()
        window.action_find.trigger()
        QtWidgets.QApplication.processEvents()
        assert window.workspace_tabs.currentWidget() is window.source_workspace
        assert window.source_editor.hasFocus()
        window.hide()

    def test_long_document_name_is_elided_and_dirty_state_is_explicit(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        source = tmp_path / (("very-long-model-name-" * 8) + ".fcstm")
        source.write_text(
            "state Root { state A; [*] -> A; A -> [*]; }", encoding="utf-8"
        )
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(source), "fcstm Files (*.fcstm)"),
        )
        window.resize(1280, 720)
        window.show()
        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            window._import_statechart()
        QtWidgets.QApplication.processEvents()

        assert window.document_name_label.text() != source.name
        assert len(window.document_name_label.text()) < len(source.name)
        assert window.document_name_label.toolTip() != str(source)
        assert any(
            marker in window.document_name_label.toolTip()
            for marker in ("<TEMP>", "<HOME>")
        )
        window.task_result_dock.show_full_paths_action.setChecked(True)
        assert window.document_name_label.toolTip() == str(source)
        window.task_result_dock.show_full_paths_action.setChecked(False)
        assert window.document_name_label.toolTip() != str(source)
        assert window.document_dirty_label.text() == "已保存"
        state = window.state_manager.get_state_by_path("Root.A")
        assert window._rename_projected_state(state, "Ready")
        assert window.document_dirty_label.text() == "未保存"
        window.hide()

    def test_imported_source_workspace_is_reused_for_multiple_physical_files(
        self, monkeypatch, qtbot, window, tmp_path
    ):
        first = tmp_path / "first.fcstm"
        second = tmp_path / "second.fcstm"
        first.write_text(
            "state FirstState { event Go; state A; [*] -> A; }",
            encoding="utf-8",
        )
        second.write_text(
            "state SecondState { event Stop; state B; [*] -> B; }",
            encoding="utf-8",
        )
        source = tmp_path / "root.fcstm"
        source.write_text(
            'state Root { import "./first.fcstm" as First; '
            'import "./second.fcstm" as Second; [*] -> First; }',
            encoding="utf-8",
        )
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(source), "fcstm Files (*.fcstm)"),
        )
        with qtbot.waitSignal(window.document_load_finished, timeout=3000):
            window._import_statechart()

        for alias, expected_uri in (
            ("First", SourceDocument.from_file(first).uri),
            ("Second", SourceDocument.from_file(second).uri),
        ):
            item = window.tree_all_state.findItems(
                alias, QtCore.Qt.MatchExactly | QtCore.Qt.MatchRecursive
            )[0]
            window.tree_all_state.setCurrentItem(item)
            qtbot.mouseClick(
                window.event_open_source_button, QtCore.Qt.LeftButton
            )
            assert window.workspace_tabs.currentWidget().property("source_uri") == expected_uri

        assert len(
            window.findChildren(QtWidgets.QWidget, "imported_source_workspace")
        ) == 1
        assert len(
            window.findChildren(QtWidgets.QPlainTextEdit, "imported_source_editor")
        ) == 1

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

    def test_composite_state_rename_edits_name_token_and_external_references(
        self, window, tmp_path
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

        changed = window._rename_projected_state(group, "Renamed")

        assert changed
        assert window.document_session.source_revision == session.source_revision + 1
        assert "state Renamed { state A; [*] -> A; A -> [*]; }" in (
            window.document_session.source_text
        )
        assert "[*] -> Renamed; Renamed -> [*];" in (
            window.document_session.source_text
        )
        assert "state Group" not in window.document_session.source_text
        assert (
            window.state_manager.get_state_by_path("Root.Renamed.A") is not None
        )

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
        inspect_actions = window.menu_inspect.actions()
        generation_actions = window.menu_generation.actions()
        export_actions = window.menu_export.actions()
        view_actions = window.menu_view.actions()

        assert window.action_import_state_machine in file_actions
        assert window.action_export_state_machine in export_actions
        assert window.action_validate_state_machine in inspect_actions
        assert window.action_graph_gen in view_actions
        assert window.action_code_gen in generation_actions

        for action in (
            window.action_import_state_machine,
            window.action_export_state_machine,
            window.action_validate_state_machine,
            window.action_graph_gen,
            window.action_code_gen,
        ):
            assert action.receivers(action.triggered) >= 1

    def test_invalid_document_populates_diagnostics_and_locates_source(
        self, qtbot, window, tmp_path
    ):
        source = tmp_path / "invalid.fcstm"
        source.write_text("state Root { state ; }", encoding="utf-8")
        session = window.document_service.load(source)

        window._set_active_document_session(session)

        assert session.validation_state is ValidationState.INVALID_SYNTAX
        assert window.workspace_tabs.isTabEnabled(
            window.workspace_tabs.indexOf(window.diagnostics_workspace)
        )
        assert window.stackedWidget_state_machine.currentWidget() is (
            window.page_state_machine_detail
        )
        assert window.diagnostics_panel.table.rowCount() >= 1
        locate = window.diagnostics_panel.table.cellWidget(
            0, window.diagnostics_panel.COLUMN_ACTION
        )
        assert locate.isEnabled()
        window.show()
        window.activateWindow()
        qtbot.mouseClick(locate, QtCore.Qt.LeftButton)
        QtWidgets.QApplication.processEvents()
        assert window.workspace_tabs.currentWidget() is window.source_workspace
        assert window.source_editor.textCursor().hasSelection()
