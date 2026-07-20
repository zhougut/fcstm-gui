import json
import time

import pytest

from app.application.task_runner import (
    TaskResult,
    TaskStamp,
    TaskStatus as RunnerTaskStatus,
)
from app.application.tasks import (
    HistoryCorruptWarning,
    PathRedactor,
    TaskArtifact,
    TaskBoundary,
    TaskCenter,
    TaskRecord,
    TaskStatus,
)


def make_record(task_id="task-1", created_at=None, **overrides):
    if created_at is None:
        created_at = time.time()
    values = dict(
        task_id=task_id,
        kind="inspect",
        session_id="session-1",
        source_revision=7,
        dependency_fingerprints={"file:///dep.fcstm": "abc"},
        created_at=created_at,
        status=TaskStatus.QUEUED,
        summary="queued",
        messages=({"severity": "info", "message": "queued"},),
        artifacts=(),
        retry_descriptor={"kind": "inspect"},
        exception_chain=(),
        boundary=TaskBoundary.EXPLICIT,
    )
    values.update(overrides)
    return TaskRecord(**values)


def test_task_record_accepts_only_declared_state_transitions():
    record = make_record()
    running = record.transition(TaskStatus.RUNNING, now=110.0)
    cancelling = running.transition(TaskStatus.CANCEL_REQUESTED, now=120.0)
    cancelled = cancelling.transition(TaskStatus.CANCELLED, now=130.0)

    assert running.started_at == 110.0
    assert cancelled.finished_at == 130.0
    assert cancelled.status is TaskStatus.CANCELLED
    with pytest.raises(ValueError, match="invalid task status transition"):
        record.transition(TaskStatus.SUCCESS, now=110.0)
    with pytest.raises(ValueError, match="invalid task status transition"):
        running.transition(TaskStatus.CANCELLED, now=120.0)
    with pytest.raises(ValueError, match="terminal"):
        cancelled.transition(TaskStatus.RUNNING, now=140.0)


def test_queued_task_can_be_cancelled_without_running():
    cancelled = make_record().transition(TaskStatus.CANCELLED, now=110.0)
    assert cancelled.started_at is None
    assert cancelled.finished_at == 110.0


@pytest.mark.parametrize(
    "terminal",
    [TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.STALE],
)
def test_running_task_reaches_each_non_cancel_terminal_status(terminal):
    completed = (
        make_record()
        .transition(TaskStatus.RUNNING, now=110.0)
        .transition(terminal, now=120.0)
    )

    assert completed.status is terminal
    assert completed.finished_at == 120.0


def test_cancel_requested_task_may_become_stale_at_completion_boundary():
    stale = (
        make_record()
        .transition(TaskStatus.RUNNING, now=110.0)
        .transition(TaskStatus.CANCEL_REQUESTED, now=120.0)
        .transition(TaskStatus.STALE, now=130.0)
    )

    assert stale.status is TaskStatus.STALE


def test_task_center_marks_transient_boundary_and_does_not_persist_it(tmp_path):
    center = TaskCenter(data_location_provider=lambda: str(tmp_path))
    center.add(make_record("explicit"))
    center.add(make_record("debounce", boundary=TaskBoundary.TRANSIENT))

    center.save()
    restored = TaskCenter(data_location_provider=lambda: str(tmp_path))
    restored.load()

    assert [item.task_id for item in center.records] == ["explicit", "debounce"]
    assert [item.task_id for item in restored.records] == ["explicit"]


def test_task_center_consumes_task_runner_result_and_removes_finished_transient(tmp_path):
    center = TaskCenter(data_location_provider=lambda: str(tmp_path))
    center.add(
        make_record("runner-task", boundary=TaskBoundary.TRANSIENT).transition(
            TaskStatus.RUNNING, now=101.0
        )
    )
    result = TaskResult(
        stamp=TaskStamp(
            task_id="runner-task",
            channel="inspect",
            session_id="session-1",
            source_revision=7,
            request_generation=1,
        ),
        status=RunnerTaskStatus.SUCCESS,
        value={"ok": True},
    )

    completed = center.apply_result(result, now=102.0, summary="complete")

    assert completed.status is TaskStatus.SUCCESS
    assert completed.finished_at == 102.0
    assert center.records == ()


def test_superseded_running_transient_result_cancels_and_releases_capacity(tmp_path):
    center = TaskCenter(
        data_location_provider=lambda: str(tmp_path), max_transient_records=1
    )
    center.add(
        make_record("superseded", boundary=TaskBoundary.TRANSIENT).transition(
            TaskStatus.RUNNING, now=101.0
        )
    )
    result = TaskResult(
        stamp=TaskStamp(
            task_id="superseded",
            channel="inspect",
            session_id="session-1",
            source_revision=7,
            request_generation=1,
        ),
        status=RunnerTaskStatus.CANCELLED,
    )

    completed = center.apply_result(result, now=102.0, summary="superseded")
    center.add(make_record("replacement", boundary=TaskBoundary.TRANSIENT))

    assert completed.status is TaskStatus.CANCELLED
    assert completed.finished_at == 102.0
    assert [item.task_id for item in center.records] == ["replacement"]


def test_task_center_accepts_runner_terminal_status_in_transition(tmp_path):
    center = TaskCenter(data_location_provider=lambda: str(tmp_path))
    center.add(make_record().transition(TaskStatus.RUNNING, now=101.0))

    completed = center.transition(
        "task-1", RunnerTaskStatus.STALE, now=102.0
    )

    assert completed.status is TaskStatus.STALE


def test_task_record_normalizes_runner_terminal_status():
    record = make_record(
        status=RunnerTaskStatus.FAILED,
        started_at=101.0,
        finished_at=102.0,
    )

    assert record.status is TaskStatus.FAILED


def test_task_center_rejects_mismatched_task_result_stamp(tmp_path):
    center = TaskCenter(data_location_provider=lambda: str(tmp_path))
    center.add(make_record().transition(TaskStatus.RUNNING, now=101.0))
    result = TaskResult(
        stamp=TaskStamp(
            task_id="task-1",
            channel="inspect",
            session_id="different-session",
            source_revision=7,
            request_generation=1,
        ),
        status=RunnerTaskStatus.SUCCESS,
    )

    with pytest.raises(ValueError, match="session_id"):
        center.apply_result(result, now=102.0)

    assert center.records[0].status is TaskStatus.RUNNING


def test_failed_task_result_captures_exception_chain_for_redacted_history(tmp_path):
    workspace = tmp_path / "workspace"
    center = TaskCenter(
        data_location_provider=lambda: str(tmp_path / "data"),
        workspace=str(workspace),
    )
    center.add(make_record().transition(TaskStatus.RUNNING, now=101.0))
    cause = OSError("cannot read {}".format(workspace / "input.fcstm"))
    try:
        raise RuntimeError("task failed at {}".format(workspace)) from cause
    except RuntimeError as error:
        result = TaskResult(
            stamp=TaskStamp(
                task_id="task-1",
                channel="inspect",
                session_id="session-1",
                source_revision=7,
                request_generation=1,
            ),
            status=RunnerTaskStatus.FAILED,
            error=error,
        )

    completed = center.apply_result(result, now=102.0)
    center.save()

    assert completed.exception_chain[0].startswith("RuntimeError:")
    assert completed.exception_chain[1].startswith("OSError:")
    assert str(workspace) not in center.history_path.read_text(encoding="utf-8")


def test_invalid_task_result_transition_does_not_partially_mutate_record(tmp_path):
    center = TaskCenter(data_location_provider=lambda: str(tmp_path))
    cancelling = (
        make_record()
        .transition(TaskStatus.RUNNING, now=101.0)
        .transition(TaskStatus.CANCEL_REQUESTED, now=102.0)
    )
    center.add(cancelling)
    result = TaskResult(
        stamp=TaskStamp(
            task_id="task-1",
            channel="inspect",
            session_id="session-1",
            source_revision=7,
            request_generation=1,
        ),
        status=RunnerTaskStatus.FAILED,
        error=RuntimeError("late failure"),
    )

    with pytest.raises(ValueError, match="invalid task status transition"):
        center.apply_result(result, now=103.0)

    assert center.records == (cancelling,)


def test_complete_persistent_atomically_updates_terminal_payload_and_session_stamp(
    tmp_path,
):
    center = TaskCenter(data_location_provider=lambda: str(tmp_path))
    center.add(
        make_record(
            "load",
            kind="document-load",
            session_id="",
            source_revision=0,
            dependency_fingerprints={},
        ).transition(TaskStatus.RUNNING, now=101.0)
    )
    messages = ({"severity": "info", "message": "loaded"},)
    artifacts = (TaskArtifact("source", "/workspace/input.fcstm", "source"),)

    completed = center.complete_persistent(
        "load",
        TaskStatus.SUCCESS,
        summary="loaded",
        now=102.0,
        session_id="actual-session",
        source_revision=3,
        dependency_fingerprints={"file:///dep.fcstm": "sha256:123"},
        messages=messages,
        artifacts=artifacts,
    )

    assert completed.status is TaskStatus.SUCCESS
    assert completed.session_id == "actual-session"
    assert completed.source_revision == 3
    assert completed.dependency_fingerprints == {
        "file:///dep.fcstm": "sha256:123"
    }
    assert completed.messages == messages
    assert completed.artifacts == artifacts
    restored = TaskCenter(data_location_provider=lambda: str(tmp_path))
    restored.load()
    assert restored.records[0].session_id == "actual-session"
    assert restored.records[0].source_revision == 3


def test_complete_persistent_running_cancel_is_published_only_as_terminal(tmp_path):
    center = TaskCenter(data_location_provider=lambda: str(tmp_path))
    running = make_record("load").transition(TaskStatus.RUNNING, now=101.0)
    center.add(running)
    observed_statuses = []
    original_write = center._write

    def observe_write(encoded):
        observed_statuses.append(center.records[0].status)
        original_write(encoded)

    center._write = observe_write

    completed = center.complete_persistent(
        "load", TaskStatus.CANCELLED, summary="cancelled", now=102.0
    )

    assert observed_statuses == [TaskStatus.RUNNING]
    assert completed.status is TaskStatus.CANCELLED
    assert center.records[0].status is TaskStatus.CANCELLED
    assert json.loads(center.history_path.read_text(encoding="utf-8"))["records"][0][
        "status"
    ] == "cancelled"


def test_complete_persistent_captures_exception_chain(tmp_path):
    center = TaskCenter(data_location_provider=lambda: str(tmp_path))
    center.add(make_record().transition(TaskStatus.RUNNING, now=101.0))
    cause = OSError("read failed")
    try:
        raise RuntimeError("load failed") from cause
    except RuntimeError as error:
        completed = center.complete_persistent(
            "task-1",
            TaskStatus.FAILED,
            summary="failed",
            now=102.0,
            exception=error,
        )

    assert completed.exception_chain == (
        "RuntimeError: load failed",
        "OSError: read failed",
    )


def test_complete_persistent_write_failure_publishes_memory_and_preserves_old_history(
    tmp_path, monkeypatch
):
    center = TaskCenter(data_location_provider=lambda: str(tmp_path))
    center.add(make_record("old", status=TaskStatus.SUCCESS, finished_at=100.0))
    center.save()
    center.add(make_record("load").transition(TaskStatus.RUNNING, now=101.0))
    old_bytes = center.history_path.read_bytes()
    monkeypatch.setattr(
        center,
        "_write",
        lambda encoded: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(OSError, match="disk full"):
        center.complete_persistent(
            "load",
            TaskStatus.SUCCESS,
            summary="loaded",
            now=102.0,
            session_id="actual-session",
            source_revision=2,
        )

    assert center.records[-1].status is TaskStatus.SUCCESS
    assert center.records[-1].session_id == "actual-session"
    assert center.records[-1].source_revision == 2
    assert center.history_path.read_bytes() == old_bytes


def test_transient_tasks_are_bounded_and_terminal_records_are_not_retained(tmp_path):
    center = TaskCenter(
        data_location_provider=lambda: str(tmp_path), max_transient_records=2
    )
    center.add(make_record("one", boundary=TaskBoundary.TRANSIENT))
    center.add(make_record("two", boundary=TaskBoundary.TRANSIENT))

    with pytest.raises(RuntimeError, match="transient task capacity"):
        center.add(make_record("three", boundary=TaskBoundary.TRANSIENT))

    center.transition("one", TaskStatus.CANCELLED, now=102.0)
    center.add(make_record("three", boundary=TaskBoundary.TRANSIENT))
    center.add(
        make_record(
            "already-finished",
            boundary=TaskBoundary.TRANSIENT,
            status=TaskStatus.SUCCESS,
            finished_at=103.0,
        )
    )

    assert [item.task_id for item in center.records] == ["two", "three"]


def test_path_redactor_handles_home_temp_workspace_and_nested_values(tmp_path):
    home = tmp_path / "home"
    temp = tmp_path / "temp"
    workspace = home / "work" / "project"
    redactor = PathRedactor(
        home=str(home), temp=str(temp), workspace=str(workspace)
    )
    value = {
        "message": "failed at {} and {}".format(workspace / "a.fcstm", temp / "x"),
        "nested": [str(home / "notes.txt")],
    }

    safe = redactor.redact(value)

    assert safe["message"] == "failed at <WORKSPACE>/a.fcstm and <TEMP>/x"
    assert safe["nested"] == ["<HOME>/notes.txt"]


def test_path_redactor_does_not_replace_a_sibling_with_the_same_prefix(tmp_path):
    home = tmp_path / "user"
    redactor = PathRedactor(home=str(home))

    assert redactor.redact_text("{} {}".format(home, str(home) + "-backup")) == (
        "<HOME> " + str(home) + "-backup"
    )


def test_path_redactor_redacts_percent_encoded_file_uri(tmp_path):
    workspace = tmp_path / "中文 workspace"
    redactor = PathRedactor(workspace=str(workspace))

    source_uri = (workspace / "models" / "example.fcstm").as_uri()

    assert redactor.redact_text(source_uri) == "<WORKSPACE>/models/example.fcstm"


def test_default_history_redacts_artifact_and_exception_paths(tmp_path):
    home = tmp_path / "home"
    workspace = home / "project"
    artifact = workspace / "out" / "report.json"
    center = TaskCenter(
        data_location_provider=lambda: str(tmp_path / "data"),
        home=str(home),
        temp=str(tmp_path / "temp"),
        workspace=str(workspace),
    )
    center.add(
        make_record(
            status=TaskStatus.FAILED,
            started_at=101.0,
            finished_at=102.0,
            summary="failed at {}".format(artifact),
            artifacts=(TaskArtifact("report", str(artifact), "json"),),
            exception_chain=("OSError: cannot write {}".format(artifact),),
        )
    )

    center.save()
    raw = center.history_path.read_text(encoding="utf-8")
    restored = TaskCenter(data_location_provider=lambda: str(tmp_path / "data"))
    restored.load()

    assert str(home) not in raw
    assert "<WORKSPACE>/out/report.json" in raw
    assert restored.records[0].artifacts[0].path == "<WORKSPACE>/out/report.json"
    assert restored.records[0].artifacts[0].raw_path_available is False
    assert "<WORKSPACE>" in restored.records[0].exception_chain[0]


def test_artifact_label_kind_and_metadata_are_redacted_by_default(tmp_path):
    workspace = tmp_path / "workspace"
    secret_path = str(workspace / "secret.fcstm")
    center = TaskCenter(
        data_location_provider=lambda: str(tmp_path / "data"),
        workspace=str(workspace),
    )
    center.add(
        make_record(
            kind="export from {}".format(secret_path),
            artifacts=(
                TaskArtifact(
                    "generated from {}".format(secret_path),
                    secret_path,
                    "report at {}".format(secret_path),
                    metadata={
                        "source {}".format(secret_path): secret_path,
                        "nested": ["failed at {}".format(secret_path)],
                    },
                ),
            ),
        )
    )

    center.save()
    raw = center.history_path.read_text(encoding="utf-8")
    artifact = json.loads(raw)["records"][0]["artifacts"][0]

    assert str(workspace) not in raw
    assert artifact["label"] == "generated from <WORKSPACE>/secret.fcstm"
    assert artifact["kind"] == "report at <WORKSPACE>/secret.fcstm"
    assert artifact["metadata"]["source <WORKSPACE>/secret.fcstm"] == (
        "<WORKSPACE>/secret.fcstm"
    )

    restored = TaskCenter(data_location_provider=lambda: str(tmp_path / "data"))
    restored.load()
    assert restored.records[0].artifacts[0].metadata["nested"] == [
        "failed at <WORKSPACE>/secret.fcstm"
    ]


def test_raw_path_persistence_requires_explicit_opt_in(tmp_path):
    artifact = tmp_path / "workspace" / "out.txt"
    center = TaskCenter(
        data_location_provider=lambda: str(tmp_path / "data"),
        workspace=str(tmp_path / "workspace"),
        persist_raw_paths=True,
    )
    center.add(
        make_record(
            status=TaskStatus.SUCCESS,
            finished_at=102.0,
            artifacts=(TaskArtifact("out", str(artifact)),),
        )
    )

    center.save()
    restored = TaskCenter(data_location_provider=lambda: str(tmp_path / "data"))
    restored.load()

    payload = json.loads(center.history_path.read_text(encoding="utf-8"))
    assert payload["records"][0]["artifacts"][0]["path"] == str(artifact)
    assert restored.records[0].artifacts[0].raw_path_available is True


def test_copy_payload_is_redacted_unless_raw_paths_are_explicitly_requested(tmp_path):
    workspace = tmp_path / "workspace"
    record = make_record(summary="created {}".format(workspace / "out.txt"))
    center = TaskCenter(
        data_location_provider=lambda: str(tmp_path / "data"),
        workspace=str(workspace),
    )

    assert str(workspace) not in center.copy_payload(record)
    payload = json.loads(center.copy_payload(record, include_raw_paths=True))
    assert payload["summary"] == "created {}".format(workspace / "out.txt")


def test_history_uses_versioned_json_and_injected_data_location(tmp_path):
    data_dir = tmp_path / "app-data"
    center = TaskCenter(data_location_provider=lambda: str(data_dir))
    center.add(make_record())

    center.save()
    payload = json.loads(center.history_path.read_text(encoding="utf-8"))

    assert center.history_path.parent == data_dir
    assert payload["schema"] == "fcstm-gui.task-history"
    assert payload["version"] == 1


def test_history_evicts_records_older_than_retention_period(tmp_path):
    center = TaskCenter(
        data_location_provider=lambda: str(tmp_path), now_provider=lambda: 40 * 86400.0
    )
    center.add(
        make_record(
            "expired", created_at=1.0, status=TaskStatus.SUCCESS, finished_at=2.0
        )
    )
    center.add(
        make_record(
            "current",
            created_at=39 * 86400.0,
            status=TaskStatus.SUCCESS,
            finished_at=39 * 86400.0 + 1,
        )
    )

    center.save()

    assert [item.task_id for item in center.records] == ["current"]


def test_history_evicts_oldest_records_above_count_limit(tmp_path):
    center = TaskCenter(
        data_location_provider=lambda: str(tmp_path), max_records=2, now_provider=lambda: 10.0
    )
    for index in range(3):
        center.add(
            make_record(
                str(index),
                created_at=float(index + 1),
                status=TaskStatus.SUCCESS,
                finished_at=float(index + 2),
            )
        )

    center.save()

    assert [item.task_id for item in center.records] == ["1", "2"]


def test_zero_count_limit_disables_persistent_history(tmp_path):
    center = TaskCenter(
        data_location_provider=lambda: str(tmp_path),
        max_records=0,
    )
    center.add(make_record(status=TaskStatus.SUCCESS, finished_at=102.0))

    center.save()

    assert center.records == ()
    assert json.loads(center.history_path.read_text(encoding="utf-8"))["records"] == []


def test_history_evicts_oldest_records_until_json_fits_byte_limit(tmp_path):
    center = TaskCenter(
        data_location_provider=lambda: str(tmp_path),
        max_bytes=700,
        now_provider=lambda: 10.0,
    )
    for index in range(4):
        center.add(
            make_record(
                str(index),
                created_at=float(index + 1),
                summary="x" * 120,
                status=TaskStatus.SUCCESS,
                finished_at=float(index + 2),
            )
        )

    center.save()

    assert center.history_path.stat().st_size <= 700
    assert center.records
    assert center.records[-1].task_id == "3"
    assert center.records[0].task_id != "0"


def test_restored_history_is_pruned_against_current_retention_limits(tmp_path):
    writer = TaskCenter(
        data_location_provider=lambda: str(tmp_path),
        retention_days=365,
        now_provider=lambda: 100 * 86400.0,
    )
    writer.add(make_record("old", created_at=10 * 86400.0))
    writer.add(make_record("recent", created_at=99 * 86400.0))
    writer.save()

    reader = TaskCenter(
        data_location_provider=lambda: str(tmp_path),
        retention_days=30,
        now_provider=lambda: 100 * 86400.0,
    )
    reader.load()

    assert [item.task_id for item in reader.records] == ["recent"]
    assert "old" not in reader.history_path.read_text(encoding="utf-8")


def test_save_write_failure_keeps_memory_and_existing_history_unchanged(
    tmp_path, monkeypatch
):
    center = TaskCenter(
        data_location_provider=lambda: str(tmp_path),
        max_records=1,
        now_provider=lambda: 10.0,
    )
    center.add(make_record("old", created_at=1.0))
    center.save()
    original_bytes = center.history_path.read_bytes()
    center.add(make_record("new", created_at=2.0))
    before = center.records

    monkeypatch.setattr(center, "_write", lambda encoded: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(OSError, match="disk full"):
        center.save()

    assert center.records == before
    assert center.history_path.read_bytes() == original_bytes


def test_load_pruning_write_failure_reports_warning_and_keeps_disk_state_in_memory(
    tmp_path, monkeypatch
):
    writer = TaskCenter(
        data_location_provider=lambda: str(tmp_path),
        retention_days=365,
        now_provider=lambda: 100 * 86400.0,
    )
    writer.add(make_record("old", created_at=10 * 86400.0))
    writer.add(make_record("recent", created_at=99 * 86400.0))
    writer.save()
    original_bytes = writer.history_path.read_bytes()
    reader = TaskCenter(
        data_location_provider=lambda: str(tmp_path),
        retention_days=30,
        now_provider=lambda: 100 * 86400.0,
    )
    monkeypatch.setattr(reader, "_write", lambda encoded: (_ for _ in ()).throw(OSError("read-only")))

    warnings = reader.load()

    assert len(warnings) == 1
    assert "清理未能写回" in warnings[0].reason
    assert [item.task_id for item in reader.records] == ["old", "recent"]
    assert reader.history_path.read_bytes() == original_bytes


def test_load_interrupted_normalization_write_failure_keeps_safe_runtime_state(
    tmp_path, monkeypatch
):
    writer = TaskCenter(
        data_location_provider=lambda: str(tmp_path), now_provider=lambda: 10.0
    )
    writer.add(
        make_record("running").transition(TaskStatus.RUNNING, now=2.0)
    )
    writer.save()
    original_bytes = writer.history_path.read_bytes()
    reader = TaskCenter(
        data_location_provider=lambda: str(tmp_path), now_provider=lambda: 20.0
    )
    monkeypatch.setattr(
        reader,
        "_write",
        lambda encoded: (_ for _ in ()).throw(OSError("read-only")),
    )

    warnings = reader.load()

    assert len(warnings) == 1
    assert "清理未能写回" in warnings[0].reason
    assert reader.records[0].status is TaskStatus.STALE
    assert reader.records[0].finished_at == 20.0
    assert "中断" in reader.records[0].summary
    assert reader.history_path.read_bytes() == original_bytes


def test_atomic_write_cleans_temporary_file_when_replace_fails(tmp_path, monkeypatch):
    center = TaskCenter(data_location_provider=lambda: str(tmp_path))
    center.add(make_record())

    def fail_replace(source, target):
        raise OSError("replace failed")

    monkeypatch.setattr("app.application.tasks.os.replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        center.save()

    assert not center.history_path.exists()
    assert not center.history_path.with_name("task-history.json.tmp").exists()


def test_clear_write_failure_does_not_commit_memory_change(tmp_path, monkeypatch):
    center = TaskCenter(data_location_provider=lambda: str(tmp_path))
    center.add(make_record("failed", status=TaskStatus.FAILED, finished_at=101.0))
    center.add(make_record("success", status=TaskStatus.SUCCESS, finished_at=102.0))
    center.save()
    before = center.records
    original_bytes = center.history_path.read_bytes()
    monkeypatch.setattr(
        center,
        "_write",
        lambda encoded: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(OSError, match="disk full"):
        center.clear_filtered(lambda item: item.status is TaskStatus.FAILED)

    assert center.records == before
    assert center.history_path.read_bytes() == original_bytes


def test_corrupt_history_is_quarantined_and_reported_without_blocking_startup(tmp_path):
    history = tmp_path / "task-history.json"
    history.write_text("{not-json", encoding="utf-8")
    center = TaskCenter(data_location_provider=lambda: str(tmp_path))

    warnings = center.load()

    assert center.records == ()
    assert len(warnings) == 1
    assert isinstance(warnings[0], HistoryCorruptWarning)
    assert warnings[0].quarantine_path.exists()
    assert not history.exists()


def test_clear_filtered_and_clear_all_are_distinct_persistent_operations(tmp_path):
    center = TaskCenter(data_location_provider=lambda: str(tmp_path))
    center.add(make_record("failed", status=TaskStatus.FAILED, finished_at=101.0))
    center.add(make_record("success", status=TaskStatus.SUCCESS, finished_at=102.0))
    center.add(make_record("transient", boundary=TaskBoundary.TRANSIENT))
    center.save()

    removed = center.clear_filtered(lambda item: item.status is TaskStatus.FAILED)

    assert removed == 1
    assert [item.task_id for item in center.records] == ["success", "transient"]
    assert "failed" not in center.history_path.read_text(encoding="utf-8")

    removed = center.clear_all_persistent()

    assert removed == 1
    assert [item.task_id for item in center.records] == ["transient"]
    assert json.loads(center.history_path.read_text(encoding="utf-8"))["records"] == []


def test_clear_completed_only_removes_successful_explicit_tasks(tmp_path):
    center = TaskCenter(data_location_provider=lambda: str(tmp_path))
    center.add(make_record("success", status=TaskStatus.SUCCESS, finished_at=101.0))
    center.add(make_record("failed", status=TaskStatus.FAILED, finished_at=102.0))
    center.add(make_record("cancelled", status=TaskStatus.CANCELLED, finished_at=103.0))
    center.add(make_record("transient", boundary=TaskBoundary.TRANSIENT))
    center.save()

    assert center.clear_completed() == 1
    assert [item.task_id for item in center.records] == [
        "failed",
        "cancelled",
        "transient",
    ]
    assert "success" not in center.history_path.read_text(encoding="utf-8")


def test_clear_and_retention_never_remove_active_explicit_tasks(tmp_path):
    center = TaskCenter(
        data_location_provider=lambda: str(tmp_path),
        retention_days=0,
        max_records=0,
        max_bytes=512,
        now_provider=lambda: 1000.0,
    )
    running = make_record("running", created_at=1.0).transition(
        TaskStatus.RUNNING, now=2.0
    )
    center.add(running)
    center.add(
        make_record(
            "finished",
            created_at=1.0,
            status=TaskStatus.SUCCESS,
            finished_at=2.0,
        )
    )

    center.save()
    assert [item.task_id for item in center.records] == ["running"]
    assert center.clear_filtered(lambda item: True) == 0
    assert center.clear_completed() == 0
    assert center.clear_all_persistent() == 0
    assert center.records == (running,)


@pytest.mark.parametrize(
    "status",
    (TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED),
)
def test_load_normalizes_interrupted_tasks_to_stale(tmp_path, status):
    writer = TaskCenter(
        data_location_provider=lambda: str(tmp_path), now_provider=lambda: 10.0
    )
    record = make_record("interrupted", status=status)
    if status is TaskStatus.RUNNING:
        record = make_record("interrupted").transition(TaskStatus.RUNNING, now=2.0)
    elif status is TaskStatus.CANCEL_REQUESTED:
        record = (
            make_record("interrupted")
            .transition(TaskStatus.RUNNING, now=2.0)
            .transition(TaskStatus.CANCEL_REQUESTED, now=3.0)
        )
    writer.add(record)
    writer.save()

    reader = TaskCenter(
        data_location_provider=lambda: str(tmp_path), now_provider=lambda: 20.0
    )
    reader.load()

    restored = reader.records[0]
    assert restored.status is TaskStatus.STALE
    assert restored.finished_at == 20.0
    assert "中断" in restored.summary


def test_load_rejects_wrong_schema_and_quarantines_it(tmp_path):
    history = tmp_path / "task-history.json"
    history.write_text(
        json.dumps({"schema": "other", "version": 1, "records": []}),
        encoding="utf-8",
    )
    center = TaskCenter(data_location_provider=lambda: str(tmp_path))

    warnings = center.load()

    assert len(warnings) == 1
    assert warnings[0].reason.startswith("unsupported history schema")
