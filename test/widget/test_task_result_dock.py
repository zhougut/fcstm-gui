import json
import re
from dataclasses import replace
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets

from app.application.tasks import (
    TaskBoundary,
    TaskArtifact,
    TaskCenter,
    TaskRecord,
    TaskStatus,
)
from app.widget.task_result_dock import TaskResultDock


def _settings(tmp_path):
    return QtCore.QSettings(
        str(tmp_path / "task-result.ini"), QtCore.QSettings.IniFormat
    )


def _record(task_id, status, summary, retry=True, artifacts=(), retry_descriptor=None):
    terminal = status in {
        TaskStatus.SUCCESS,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.STALE,
    }
    return TaskRecord(
        task_id=task_id,
        kind="document-load",
        session_id="session",
        source_revision=1,
        dependency_fingerprints={},
        created_at=1.0,
        started_at=1.1,
        finished_at=1.2 if terminal else None,
        status=status,
        summary=summary,
        messages=(),
        artifacts=tuple(artifacts),
        retry_descriptor=(
            retry_descriptor
            if retry_descriptor is not None
            else ({"kind": "document-load"} if retry else {})
        ),
        exception_chain=(),
        boundary=TaskBoundary.EXPLICIT,
    )


def test_result_dock_filters_selects_copies_and_exports_redacted_detail(
    monkeypatch, qtbot, tmp_path
):
    workspace = tmp_path / "workspace"
    center = TaskCenter(
        data_location_provider=lambda: str(tmp_path / "data"),
        workspace=str(workspace),
    )
    center.add(
        _record(
            "failed",
            TaskStatus.FAILED,
            "failed at {}".format(workspace / "broken.fcstm"),
        )
    )
    center.add(_record("success", TaskStatus.SUCCESS, "loaded"))
    dock = TaskResultDock(center, settings=_settings(tmp_path))
    qtbot.addWidget(dock)
    dock.show()

    assert dock.table.rowCount() == 2
    dock.status_filter.setCurrentIndex(
        dock.status_filter.findData(TaskStatus.FAILED.value)
    )

    assert dock.table.rowCount() == 1
    assert dock.selected_record.task_id == "failed"
    assert dock.table.horizontalHeaderItem(2).text() == "版本"
    assert dock.table.item(0, 0).text() == "失败"
    assert dock.table.item(0, 2).text() == "r1"
    assert str(workspace) not in dock.table.item(0, 3).text()
    assert "<WORKSPACE>" in dock.table.item(0, 3).text()
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}",
        dock.table.item(0, 4).text(),
    )
    assert str(workspace) not in dock.detail.toPlainText()
    assert "<WORKSPACE>" in dock.detail.toPlainText()

    qtbot.mouseClick(dock.copy_button, QtCore.Qt.LeftButton)
    copied = QtWidgets.QApplication.clipboard().text()
    assert json.loads(copied)["task_id"] == "failed"
    assert str(workspace) not in copied

    output = tmp_path / "redacted.json"
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), "JSON Files (*.json)"),
    )
    assert dock.export_selected()
    exported = output.read_text(encoding="utf-8")
    assert str(workspace) not in exported
    assert "<WORKSPACE>" in exported


def test_result_dock_searches_only_redacted_visible_payload(qtbot, tmp_path):
    workspace = tmp_path / "workspace"
    center = TaskCenter(
        data_location_provider=lambda: str(tmp_path / "data"),
        workspace=str(workspace),
    )
    center.add(
        _record(
            "failed",
            TaskStatus.FAILED,
            "failed at {}".format(workspace / "needle.fcstm"),
        )
    )
    dock = TaskResultDock(center, settings=_settings(tmp_path))
    qtbot.addWidget(dock)

    dock.search_edit.setText("<WORKSPACE>")
    assert dock.table.rowCount() == 1

    dock.search_edit.setText(str(workspace))
    assert dock.table.rowCount() == 0


def test_result_dock_emits_retry_and_cancel_for_eligible_records(qtbot, tmp_path):
    center = TaskCenter(data_location_provider=lambda: str(tmp_path))
    center.add(_record("running", TaskStatus.RUNNING, "running", retry=False))
    center.add(_record("failed", TaskStatus.FAILED, "failed"))
    dock = TaskResultDock(center, settings=_settings(tmp_path))
    qtbot.addWidget(dock)
    dock.show()

    dock.table.selectRow(0)
    with qtbot.waitSignal(dock.cancel_requested) as blocker:
        qtbot.mouseClick(dock.cancel_button, QtCore.Qt.LeftButton)
    assert blocker.args == ["running"]

    dock.table.selectRow(1)
    with qtbot.waitSignal(dock.retry_requested) as blocker:
        qtbot.mouseClick(dock.retry_button, QtCore.Qt.LeftButton)
    assert blocker.args[0].task_id == "failed"


def test_each_result_row_has_stable_accessible_context_action(qtbot, tmp_path):
    center = TaskCenter(data_location_provider=lambda: str(tmp_path))
    center.add(_record("queued", TaskStatus.QUEUED, "queued", retry=False))
    center.add(_record("running", TaskStatus.RUNNING, "running", retry=False))
    center.add(_record("failed", TaskStatus.FAILED, "failed"))
    center.add(_record("done", TaskStatus.SUCCESS, "done", retry=False))
    center.add(
        _record(
            "cancelling",
            TaskStatus.CANCEL_REQUESTED,
            "cancelling",
            retry=False,
        )
    )
    dock = TaskResultDock(center, settings=_settings(tmp_path))
    qtbot.addWidget(dock)
    dock.show()

    assert dock.table.horizontalHeaderItem(5).text() == "操作"
    assert dock.table.item(2, 1).text() == "文档加载"
    assert "document-load" in dock.table.item(2, 1).toolTip()
    assert dock.table.item(2, 4).toolTip() == dock.table.item(2, 4).text()
    queued_button = dock.table.cellWidget(0, 5)
    running_button = dock.table.cellWidget(1, 5)
    retry_button = dock.table.cellWidget(2, 5)
    done_button = dock.table.cellWidget(3, 5)
    cancelling_button = dock.table.cellWidget(4, 5)
    assert queued_button.text() == "取消"
    assert running_button.text() == "取消"
    assert retry_button.text() == "重试"
    assert done_button.text() == "无操作"
    assert cancelling_button.text() == "无操作"
    assert done_button.isEnabled() is False
    assert cancelling_button.isEnabled() is False
    for button in (
        queued_button,
        running_button,
        retry_button,
        done_button,
        cancelling_button,
    ):
        assert button.accessibleName()
        assert button.toolTip()

    with qtbot.waitSignal(dock.cancel_requested) as blocker:
        qtbot.mouseClick(running_button, QtCore.Qt.LeftButton)
    assert blocker.args == ["running"]
    with qtbot.waitSignal(dock.retry_requested) as blocker:
        qtbot.mouseClick(retry_button, QtCore.Qt.LeftButton)
    assert blocker.args[0].task_id == "failed"

    dock.table.selectRow(2)
    dock.refresh()

    assert dock.selected_record.task_id == "failed"
    assert dock.table.cellWidget(2, 5).text() == "重试"
    assert dock.table.cellWidget(2, 5).property("task_id") == "failed"


def test_row_retry_is_disabled_when_descriptor_contains_only_redacted_path(
    qtbot, tmp_path
):
    workspace = tmp_path / "workspace"
    center = TaskCenter(
        data_location_provider=lambda: str(tmp_path), workspace=str(workspace)
    )
    center.add(
        _record(
            "failed",
            TaskStatus.FAILED,
            "failed",
            retry_descriptor={"path": "<WORKSPACE>/input.fcstm"},
        )
    )
    dock = TaskResultDock(center, settings=_settings(tmp_path))
    qtbot.addWidget(dock)

    button = dock.table.cellWidget(0, 5)
    assert button.text() == "重试"
    assert not button.isEnabled()
    assert "完整路径" in button.toolTip()


def test_cancel_requested_disables_duplicate_cancel(qtbot, tmp_path):
    center = TaskCenter(data_location_provider=lambda: str(tmp_path))
    center.add(
        _record("cancelling", TaskStatus.CANCEL_REQUESTED, "cancelling", retry=False)
    )
    dock = TaskResultDock(center, settings=_settings(tmp_path))
    qtbot.addWidget(dock)

    assert dock.selected_record.task_id == "cancelling"
    assert not dock.cancel_button.isEnabled()


def test_restored_placeholder_retry_descriptor_is_not_retryable(qtbot, tmp_path):
    workspace = tmp_path / "workspace"
    data = tmp_path / "data"
    center = TaskCenter(
        data_location_provider=lambda: str(data),
        workspace=str(workspace),
        now_provider=lambda: 1.2,
    )
    center.add(
        _record(
            "failed",
            TaskStatus.FAILED,
            "failed",
            retry_descriptor={
                "kind": "document-load",
                "path": str(workspace / "a.fcstm"),
            },
        )
    )
    center.save()
    restored = TaskCenter(
        data_location_provider=lambda: str(data),
        workspace=str(workspace),
        now_provider=lambda: 1.2,
    )
    assert restored.load() == ()
    dock = TaskResultDock(restored, settings=_settings(tmp_path))
    qtbot.addWidget(dock)

    assert "<WORKSPACE>" in json.dumps(restored.records[0].retry_descriptor)
    assert not dock.retry_button.isEnabled()


def test_result_dock_exports_and_has_three_confirmed_clear_operations(
    monkeypatch, qtbot, tmp_path
):
    center = TaskCenter(
        data_location_provider=lambda: str(tmp_path / "data"),
        now_provider=lambda: 1.2,
    )
    center.add(_record("failed", TaskStatus.FAILED, "failed"))
    center.add(_record("success", TaskStatus.SUCCESS, "success"))
    center.save()
    dock = TaskResultDock(center, settings=_settings(tmp_path))
    qtbot.addWidget(dock)
    dock.show()
    output = tmp_path / "task.json"
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), "JSON Files (*.json)"),
    )
    dock.table.setCurrentCell(0, 0)
    dock.table.selectRow(0)

    assert dock.export_selected()
    exported = json.loads(output.read_text(encoding="utf-8"))
    assert exported["task_id"] == "failed"

    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes,
    )
    dock.status_filter.setCurrentIndex(
        dock.status_filter.findData(TaskStatus.FAILED.value)
    )
    assert dock.clear_filtered() == 1
    assert [record.task_id for record in center.records] == ["success"]
    assert dock.clear_completed() == 1
    assert center.records == ()

    center.add(_record("cancelled", TaskStatus.CANCELLED, "cancelled"))
    dock.refresh()
    assert dock.clear_all() == 1
    assert center.records == ()


def test_artifact_actions_open_existing_raw_file_and_directory(
    monkeypatch, qtbot, tmp_path
):
    artifact_file = tmp_path / "output" / "result.json"
    artifact_file.parent.mkdir()
    artifact_file.write_text("{}", encoding="utf-8")
    center = TaskCenter(data_location_provider=lambda: str(tmp_path / "data"))
    center.add(
        _record(
            "success",
            TaskStatus.SUCCESS,
            "done",
            artifacts=(TaskArtifact("结果", str(artifact_file)),),
        )
    )
    opened = []
    monkeypatch.setattr(
        QtGui.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )
    dock = TaskResultDock(center, settings=_settings(tmp_path))
    qtbot.addWidget(dock)
    dock.show()

    assert dock.artifact_list.count() == 1
    assert dock.open_artifact_button.isEnabled()
    assert dock.open_artifact_directory_button.isEnabled()
    qtbot.mouseClick(dock.open_artifact_button, QtCore.Qt.LeftButton)
    qtbot.mouseClick(dock.open_artifact_directory_button, QtCore.Qt.LeftButton)

    assert [Path(item).resolve() for item in opened] == [
        artifact_file.resolve(),
        artifact_file.parent.resolve(),
    ]


def test_redacted_restored_artifact_has_no_open_action(qtbot, tmp_path):
    workspace = tmp_path / "workspace"
    artifact_file = workspace / "result.json"
    artifact_file.parent.mkdir()
    artifact_file.write_text("{}", encoding="utf-8")
    data = tmp_path / "data"
    center = TaskCenter(
        data_location_provider=lambda: str(data),
        workspace=str(workspace),
        now_provider=lambda: 1.2,
    )
    center.add(
        _record(
            "success",
            TaskStatus.SUCCESS,
            "done",
            artifacts=(TaskArtifact(str(artifact_file), str(artifact_file)),),
        )
    )
    center.save()
    restored = TaskCenter(
        data_location_provider=lambda: str(data),
        workspace=str(workspace),
        now_provider=lambda: 1.2,
    )
    restored.load()
    dock = TaskResultDock(restored, settings=_settings(tmp_path))
    qtbot.addWidget(dock)

    assert str(workspace) not in dock.artifact_list.item(0).text()
    assert "<WORKSPACE>" in dock.artifact_list.item(0).text()
    assert not dock.open_artifact_button.isEnabled()
    assert not dock.open_artifact_directory_button.isEnabled()


def test_full_path_display_requires_explicit_opt_in_and_persists_setting(
    monkeypatch, qtbot, tmp_path
):
    workspace = tmp_path / "workspace"
    artifact = workspace / "output.json"
    center = TaskCenter(
        data_location_provider=lambda: str(tmp_path / "data"),
        workspace=str(workspace),
    )
    center.add(
        _record(
            "success",
            TaskStatus.SUCCESS,
            "created {}".format(artifact),
            artifacts=(TaskArtifact("result {}".format(artifact), str(artifact)),),
        )
    )
    settings = _settings(tmp_path)
    dock = TaskResultDock(center, settings=settings)
    qtbot.addWidget(dock)

    assert not dock.show_full_paths_action.isChecked()
    assert str(workspace) not in dock.detail.toPlainText()
    assert str(workspace) not in dock.artifact_list.item(0).text()

    dock.show_full_paths_action.trigger()

    assert dock.show_full_paths_action.isChecked()
    detail_payload = json.loads(dock.detail.toPlainText())
    assert detail_payload["summary"] == "created {}".format(artifact)
    assert detail_payload["artifacts"][0]["label"] == "result {}".format(artifact)
    assert detail_payload["artifacts"][0]["path"] == str(artifact)
    assert str(workspace) in dock.artifact_list.item(0).text()
    qtbot.mouseClick(dock.copy_button, QtCore.Qt.LeftButton)
    copied = json.loads(QtWidgets.QApplication.clipboard().text())
    assert copied["summary"] == "created {}".format(artifact)
    output = tmp_path / "full-path.json"
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), "JSON Files (*.json)"),
    )
    assert dock.export_selected()
    exported = json.loads(output.read_text(encoding="utf-8"))
    assert exported["summary"] == "created {}".format(artifact)

    restored_dock = TaskResultDock(center, settings=settings)
    qtbot.addWidget(restored_dock)
    assert restored_dock.show_full_paths_action.isChecked()
    restored_payload = json.loads(restored_dock.detail.toPlainText())
    assert restored_payload["summary"] == "created {}".format(artifact)
    assert restored_payload["artifacts"][0]["path"] == str(artifact)


def test_result_dock_handles_non_finite_history_time(qtbot, tmp_path):
    center = TaskCenter(data_location_provider=lambda: str(tmp_path / "data"))
    center.add(
        replace(
            _record("failed", TaskStatus.FAILED, "failed"),
            created_at=float("nan"),
        )
    )
    dock = TaskResultDock(center, settings=_settings(tmp_path))
    qtbot.addWidget(dock)

    assert dock.table.item(0, 4).text() == "-"


def test_full_path_opt_in_cannot_recover_paths_from_redacted_history(qtbot, tmp_path):
    workspace = tmp_path / "workspace"
    artifact = workspace / "output.json"
    data = tmp_path / "data"
    writer = TaskCenter(
        data_location_provider=lambda: str(data),
        workspace=str(workspace),
        now_provider=lambda: 2.0,
    )
    writer.add(
        _record(
            "success",
            TaskStatus.SUCCESS,
            "created {}".format(artifact),
            artifacts=(TaskArtifact("result", str(artifact)),),
        )
    )
    writer.save()
    reader = TaskCenter(
        data_location_provider=lambda: str(data),
        workspace=str(workspace),
        now_provider=lambda: 2.0,
    )
    assert reader.load() == ()
    dock = TaskResultDock(reader, settings=_settings(tmp_path))
    qtbot.addWidget(dock)

    dock.show_full_paths_action.trigger()

    assert str(workspace) not in dock.detail.toPlainText()
    assert "<WORKSPACE>" in dock.detail.toPlainText()
    assert not dock.open_artifact_button.isEnabled()
