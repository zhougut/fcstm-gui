import time

import pytest
from PyQt5 import QtCore, QtWidgets

from app.widget import AppMainWindow
from app.widget import main_window


SOURCE = "state Root { state Idle; [*] -> Idle; Idle -> [*]; }"


@pytest.fixture
def window(qtbot, tmp_path):
    settings = QtCore.QSettings(
        str(tmp_path / "menu-settings.ini"), QtCore.QSettings.IniFormat
    )
    value = AppMainWindow(settings=settings)
    qtbot.addWidget(value)
    return value


def _install_document(window, path):
    path.write_text(SOURCE, encoding="utf-8")
    session = window.document_service.load(path)
    window.command_stack.reset_document(session)
    window._set_active_document_session(session)
    return session


def _recent_entry_actions(window):
    return [
        action
        for action in window.menu_recent_files.actions()
        if action.property("recent_path")
    ]


def test_product_menu_information_architecture_and_workspace_shortcuts(window, tmp_path):
    assert [action.text() for action in window.menuBar().actions()] == [
        "文件",
        "编辑",
        "模型",
        "检查",
        "仿真",
        "生成",
        "导出",
        "视图",
    ]
    assert [
        action.menu().objectName() for action in window.menuBar().actions()
    ] == [
        "menu_file",
        "menu_edit",
        "menu_model",
        "menu_inspect",
        "menu_simulation",
        "menu_generation",
        "menu_export",
        "menu_view",
    ]

    source = tmp_path / "workspaces.fcstm"
    _install_document(window, source)
    actions = (
        (window.action_show_model, window.model_workspace),
        (window.action_show_source, window.source_workspace),
        (window.action_show_graph, window.graph_workspace),
        (window.action_show_diagnostics, window.diagnostics_workspace),
        (window.action_show_simulation, window.simulation_workspace),
        (window.action_show_dynamic_validation, window.dynamic_validation_workspace),
    )
    shortcuts = []
    for action, page in actions:
        assert action.objectName()
        assert action.shortcut().toString()
        shortcuts.append(action.shortcut().toString())
        action.trigger()
        assert window.workspace_tabs.currentWidget() is page
    assert len(set(shortcuts)) == 6
    assert not window.action_graph_gen.shortcut().toString()

    assert window.action_validate_state_machine in window.menu_inspect.actions()
    assert window.action_code_gen in window.menu_generation.actions()
    assert window.action_unified_export in window.menu_export.actions()
    assert window.action_graph_gen not in window.menu_export.actions()
    assert window.action_graph_gen in window.menu_view.actions()


def test_recent_files_menu_redacts_by_default_and_follows_full_path_opt_in(
    window, tmp_path
):
    source = tmp_path / "private" / "recent.fcstm"
    source.parent.mkdir()
    source.write_text(SOURCE, encoding="utf-8")

    window._record_recent_file(str(source))
    entries = _recent_entry_actions(window)

    assert len(entries) == 1
    assert entries[0].text() == "1. recent.fcstm"
    assert str(source.resolve()) not in entries[0].toolTip()
    assert entries[0].toolTip() == window.task_center.redactor.redact_text(
        str(source.resolve())
    )

    window.task_result_dock.show_full_paths_action.setChecked(True)
    entries = _recent_entry_actions(window)
    assert entries[0].toolTip() == str(source.resolve())


def test_recent_file_reopen_uses_dirty_replacement_gate(
    monkeypatch, window, tmp_path
):
    current_path = tmp_path / "current.fcstm"
    target_path = tmp_path / "target.fcstm"
    current = _install_document(window, current_path)
    target_path.write_text("state Target;", encoding="utf-8")
    dirty = window.document_service.replace_source_text(
        current, current.source_text + "\n// dirty"
    )
    window._set_active_document_session(dirty)
    window._record_recent_file(str(target_path))
    target_action = _recent_entry_actions(window)[0]
    started = []
    monkeypatch.setattr(window, "_start_document_load", started.append)
    monkeypatch.setattr(window, "_confirm_document_replacement", lambda: False)

    target_action.trigger()
    assert started == []
    assert window.document_session is dirty

    monkeypatch.setattr(window, "_confirm_document_replacement", lambda: True)
    target_action.trigger()
    assert started == [str(target_path.resolve())]


def test_missing_recent_file_is_removed_without_replacing_document(
    monkeypatch, window, tmp_path
):
    current_path = tmp_path / "current.fcstm"
    current = _install_document(window, current_path)
    missing = tmp_path / "missing.fcstm"
    window._record_recent_file(str(missing))
    action = _recent_entry_actions(window)[0]
    started = []
    warnings = []
    monkeypatch.setattr(window, "_start_document_load", started.append)
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args),
    )

    action.trigger()

    assert started == []
    assert warnings
    assert window.document_session is current
    assert str(missing.resolve()) not in window.settings.value(
        "recent_files", [], type=list
    )
    assert [action.property("recent_path") for action in _recent_entry_actions(window)] == [
        str(current_path.resolve())
    ]


def test_clear_recent_files_resets_menu(window, tmp_path):
    first = tmp_path / "first.fcstm"
    second = tmp_path / "second.fcstm"
    window._record_recent_file(str(first))
    window._record_recent_file(str(second))
    assert len(_recent_entry_actions(window)) == 2

    window.action_clear_recent_files.trigger()

    assert window.settings.value("recent_files", [], type=list) == []
    assert not _recent_entry_actions(window)
    placeholder = window.menu_recent_files.actions()[0]
    assert placeholder.text() == "暂无最近文件"
    assert not placeholder.isEnabled()


def test_explicit_task_success_stays_collapsed_and_failure_requests_attention(
    qtbot, window
):
    window.show()
    window.task_result_dock.hide()
    QtWidgets.QApplication.processEvents()

    def complete(task_id, result_status, history_status):
        now = time.time()
        window.task_center.add(
            main_window.TaskRecord(
                task_id=task_id,
                kind="graph-render",
                session_id="session",
                source_revision=1,
                dependency_fingerprints={},
                created_at=now,
                started_at=now,
                status=main_window.HistoryTaskStatus.RUNNING,
                summary="运行中",
                messages=(),
                artifacts=(),
                retry_descriptor=None,
                exception_chain=(),
                boundary=main_window.TaskBoundary.EXPLICIT,
            )
        )
        result = main_window.TaskResult(
            stamp=main_window.TaskStamp(
                task_id=task_id,
                channel="graph-render",
                session_id="session",
                source_revision=1,
                request_generation=1,
            ),
            status=result_status,
            error=(RuntimeError("render failed") if result_status is main_window.TaskStatus.FAILED else None),
        )
        window._complete_workspace_history(
            result, history_status, "完成" if result.error is None else "失败"
        )
        QtWidgets.QApplication.processEvents()

    complete(
        "success-task",
        main_window.TaskStatus.SUCCESS,
        main_window.HistoryTaskStatus.SUCCESS,
    )
    assert not window.task_result_dock.isVisible()

    complete(
        "failed-task",
        main_window.TaskStatus.FAILED,
        main_window.HistoryTaskStatus.FAILED,
    )
    assert window.task_result_dock.isVisible()
