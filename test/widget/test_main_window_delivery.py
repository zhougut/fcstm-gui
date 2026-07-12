from __future__ import unicode_literals

import json
import threading

import pytest
from PyQt5 import QtCore, QtWidgets

from app.application.tasks import TaskStatus as HistoryTaskStatus
from app.application.task_runner import TaskStatus
from app.widget import AppMainWindow, DialogCodeGen, DialogExport


SOURCE = """
def int count = 0;
state Root {
    state Idle;
    state Running;
    [*] -> Idle;
    Idle -> Running :: Start effect { count = count + 1; }
    Running -> [*] :: Stop;
}
"""


@pytest.fixture
def delivery_window(qtbot, tmp_path):
    source = tmp_path / "delivery.fcstm"
    source.write_text(SOURCE, encoding="utf-8")
    settings = QtCore.QSettings(
        str(tmp_path / "settings.ini"), QtCore.QSettings.IniFormat
    )
    window = AppMainWindow(settings=settings)
    qtbot.addWidget(window)
    window._set_active_document_session(window.document_service.load(source))
    return window


def test_graph_workspace_refresh_selection_controls_and_real_svg_export(
    monkeypatch, qtbot, delivery_window, tmp_path
):
    window = delivery_window
    with qtbot.waitSignal(window.graph_task_finished, timeout=15000):
        handle = window._graph_gen()

    assert handle is not None
    assert window.workspace_tabs.currentWidget() is window.graph_workspace
    assert window.graph_panel.view.scene() is not None
    assert not window.graph_panel.view.scene().sceneRect().isEmpty()
    assert "就绪" in window.graph_panel.status_label.text()
    root_item = window.tree_all_state.topLevelItem(0)
    child_item = root_item.child(0)
    window.tree_all_state.setCurrentItem(child_item)
    assert "Root.Idle" in window.graph_panel.status_label.text()
    window.graph_panel.actual_button.click()
    assert window.graph_panel.view.transform().m11() == 1.0
    window.graph_panel.fit_button.click()
    window.graph_panel.reset_button.click()

    target = tmp_path / "statechart.svg"
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(target), "所有文件 (*)"),
    )
    with qtbot.waitSignal(window.graph_task_finished, timeout=15000):
        window._export_graph_kind("svg")

    assert b"<svg" in target.read_bytes()[:4096].lower()
    record = [item for item in window.task_center.records if item.kind == "graph-render"][-1]
    assert record.status is HistoryTaskStatus.SUCCESS
    assert record.artifacts[0].path == str(target)


def test_source_edit_does_not_schedule_projection_variable_commit(
    qtbot, delivery_window
):
    window = delivery_window
    initial_revision = window.document_session.source_revision

    with qtbot.waitSignal(window.document_validation_finished, timeout=3000):
        window.source_editor.insertPlainText("\n")

    validated_revision = window.document_session.source_revision
    assert validated_revision == initial_revision + 1
    assert not window._variable_edit_timer.isActive()
    qtbot.wait(500)
    assert window.document_session.source_revision == validated_revision


def test_generation_dialog_filters_languages_and_generates_real_packaged_template(
    qtbot, delivery_window, tmp_path
):
    window = delivery_window
    dialog = DialogCodeGen(window, window.generation_service.list_templates())
    qtbot.addWidget(dialog)
    dialog.generate_requested.connect(
        lambda request: window._start_generation(request, dialog)
    )
    dialog.cancel_requested.connect(
        lambda: window._cancel_workspace_kind("code-generation")
    )
    dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("c"))
    assert [
        dialog.template_combo.itemData(index)
        for index in range(dialog.template_combo.count())
    ] == ["c", "c_poll"]
    dialog.language_combo.setCurrentIndex(
        dialog.language_combo.findData("python")
    )
    assert dialog.template_combo.currentData() == "python"
    output = tmp_path / "generated-python"
    dialog.output_edit.setText(str(output))

    with qtbot.waitSignal(window.generation_finished, timeout=15000):
        dialog.generate_button.click()

    assert dialog.result_table.rowCount() >= 1
    assert (output / "machine.py").stat().st_size > 0
    assert "生成完成" in dialog.status_label.text()
    record = [
        item for item in window.task_center.records if item.kind == "code-generation"
    ][-1]
    assert record.status is HistoryTaskStatus.SUCCESS
    assert record.artifacts[0].kind == "directory"
    assert record.artifacts[0].metadata["files"] == dialog.result_table.rowCount()


def test_unified_export_dialog_writes_inspect_json_and_preserves_existing_file(
    qtbot, delivery_window, tmp_path
):
    window = delivery_window
    dialog = DialogExport(window, dynamic_available=False)
    qtbot.addWidget(dialog)
    dialog.export_requested.connect(
        lambda request: window._start_unified_export(request, dialog)
    )
    inspect_index = dialog.kind_combo.findData("inspect-json")
    dialog.kind_combo.setCurrentIndex(inspect_index)
    target = tmp_path / "inspect.json"
    dialog.path_edit.setText(str(target))

    with qtbot.waitSignal(window.unified_export_finished, timeout=5000):
        dialog.start_button.click()

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert "导出完成" in dialog.status_label.text()
    record = [
        item for item in window.task_center.records if item.kind == "unified-export"
    ][-1]
    assert record.status is HistoryTaskStatus.SUCCESS
    assert record.artifacts[0].path == str(target)

    target.write_text("old", encoding="utf-8")
    dialog.path_edit.setText(str(target))
    dialog.overwrite_check.setChecked(False)
    with qtbot.waitSignal(window.unified_export_finished, timeout=5000):
        dialog.start_button.click()
    assert target.read_text(encoding="utf-8") == "old"
    assert dialog.status_label.text().startswith("失败：")
    failed = [
        item for item in window.task_center.records if item.kind == "unified-export"
    ][-1]
    assert failed.status is HistoryTaskStatus.FAILED


def test_export_terminal_states_use_localized_user_text(qtbot):
    dialog = DialogExport(dynamic_available=False)
    qtbot.addWidget(dialog)

    dialog.show_cancelled()
    assert dialog.status_label.text() == "已取消，既有文件未修改"

    dialog.show_error("boom")
    assert dialog.status_label.text() == "失败：boom"


def test_generation_custom_mode_replaces_builtin_template_description(
    qtbot, delivery_window
):
    dialog = DialogCodeGen(
        delivery_window, delivery_window.generation_service.list_templates()
    )
    qtbot.addWidget(dialog)
    builtin_description = dialog.description_edit.toPlainText()

    dialog.template_mode_combo.setCurrentIndex(1)

    assert "自定义模板" in dialog.description_edit.toPlainText()
    assert dialog.description_edit.toPlainText() != builtin_description
    assert dialog.custom_template_edit.isEnabled()
    assert not dialog.template_combo.isEnabled()


def test_delivery_controls_are_accessible_and_tables_have_headers(delivery_window):
    window = delivery_window
    dialogs = (
        DialogCodeGen(window, window.generation_service.list_templates()),
        DialogExport(window),
    )
    for widget in (window.graph_panel,) + dialogs:
        for button in widget.findChildren(QtWidgets.QPushButton):
            assert button.accessibleName()
            assert button.toolTip()
        for table in widget.findChildren(QtWidgets.QTableWidget):
            assert all(
                table.horizontalHeaderItem(column).text()
                for column in range(table.columnCount())
            )


def test_generation_revision_change_blocks_publication_at_service_boundary(
    monkeypatch, qtbot, delivery_window, tmp_path
):
    window = delivery_window
    dialog = DialogCodeGen(window, window.generation_service.list_templates())
    qtbot.addWidget(dialog)
    started = threading.Event()
    release = threading.Event()
    target = tmp_path / "stale-output"

    def controlled_generate(
        model,
        output_dir,
        template_name=None,
        custom_template_dir=None,
        overwrite=False,
        cancel_token=None,
    ):
        started.set()
        assert release.wait(5)
        cancel_token.raise_if_cancelled()
        target.mkdir()
        raise AssertionError("stale generation crossed publication guard")

    monkeypatch.setattr(window.generation_service, "generate", controlled_generate)
    dialog.generate_requested.connect(
        lambda request: window._start_generation(request, dialog)
    )
    dialog.output_edit.setText(str(target))
    completed = []
    window.generation_finished.connect(completed.append)
    dialog.generate_button.click()
    qtbot.waitUntil(started.is_set, timeout=3000)

    window.source_editor.insertPlainText("\n")
    release.set()
    qtbot.waitUntil(lambda: bool(completed), timeout=5000)

    assert completed[0].status is TaskStatus.STALE
    assert not target.exists()
    record = [
        item for item in window.task_center.records if item.kind == "code-generation"
    ][-1]
    assert record.status is HistoryTaskStatus.STALE
