import json
import os
import re
import tempfile
import time
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple


HISTORY_SCHEMA = "fcstm-gui.task-history"
HISTORY_VERSION = 1
HISTORY_FILE_NAME = "task-history.json"


class TaskStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    STALE = "stale"
    CANCEL_REQUESTED = "cancel-requested"
    CANCELLED = "cancelled"


class TaskBoundary(Enum):
    EXPLICIT = "explicit"
    TRANSIENT = "transient"


_TERMINAL_STATUSES = {
    TaskStatus.SUCCESS,
    TaskStatus.FAILED,
    TaskStatus.STALE,
    TaskStatus.CANCELLED,
}

_TRANSITIONS = {
    TaskStatus.QUEUED: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {
        TaskStatus.SUCCESS,
        TaskStatus.FAILED,
        TaskStatus.STALE,
        TaskStatus.CANCEL_REQUESTED,
    },
    TaskStatus.CANCEL_REQUESTED: {TaskStatus.CANCELLED, TaskStatus.STALE},
}


@dataclass(frozen=True)
class TaskArtifact:
    label: str
    path: str
    kind: str = "file"
    raw_path_available: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self, redactor, preserve_raw_paths):
        payload = {
            "label": self.label,
            "path": self.path,
            "kind": self.kind,
            "raw_path_available": bool(preserve_raw_paths and self.raw_path_available),
            "metadata": dict(self.metadata),
        }
        return payload if preserve_raw_paths else redactor.redact(payload)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("artifact must be an object")
        raw_path_available = value.get("raw_path_available", False)
        metadata = value.get("metadata", {})
        if not isinstance(raw_path_available, bool):
            raise ValueError("raw_path_available must be a boolean")
        if not isinstance(metadata, dict):
            raise ValueError("artifact metadata must be an object")
        return cls(
            label=_required_string(value, "label"),
            path=_required_string(value, "path"),
            kind=_optional_string(value, "kind", "file"),
            raw_path_available=raw_path_available,
            metadata=dict(metadata),
        )


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    kind: str
    session_id: str
    source_revision: int
    dependency_fingerprints: Mapping[str, str]
    created_at: float
    status: TaskStatus
    summary: str
    messages: Tuple[Mapping[str, Any], ...]
    artifacts: Tuple[TaskArtifact, ...]
    retry_descriptor: Optional[Mapping[str, Any]]
    exception_chain: Tuple[str, ...]
    boundary: TaskBoundary
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def __post_init__(self):
        object.__setattr__(self, "status", _coerce_task_status(self.status))

    def transition(self, target, now=None, summary=None):
        target = _coerce_task_status(target)
        if self.status in _TERMINAL_STATUSES:
            raise ValueError("terminal task status cannot transition")
        if target not in _TRANSITIONS.get(self.status, set()):
            raise ValueError(
                "invalid task status transition: {} -> {}".format(
                    self.status.value, target.value
                )
            )
        timestamp = time.time() if now is None else float(now)
        started_at = self.started_at
        finished_at = self.finished_at
        if target is TaskStatus.RUNNING:
            started_at = timestamp
        if target in _TERMINAL_STATUSES:
            finished_at = timestamp
        return replace(
            self,
            status=target,
            summary=self.summary if summary is None else summary,
            started_at=started_at,
            finished_at=finished_at,
        )

    def to_dict(self, redactor, preserve_raw_paths=False):
        payload = {
            "task_id": self.task_id,
            "kind": self.kind,
            "session_id": self.session_id,
            "source_revision": self.source_revision,
            "dependency_fingerprints": dict(self.dependency_fingerprints),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status.value,
            "summary": self.summary,
            "messages": [dict(item) for item in self.messages],
            "artifacts": [
                item.to_dict(redactor, preserve_raw_paths) for item in self.artifacts
            ],
            "retry_descriptor": (
                None if self.retry_descriptor is None else dict(self.retry_descriptor)
            ),
            "exception_chain": list(self.exception_chain),
            "boundary": self.boundary.value,
        }
        return payload if preserve_raw_paths else redactor.redact(payload)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("task record must be an object")
        try:
            status = TaskStatus(_required_string(value, "status"))
            boundary = TaskBoundary(_required_string(value, "boundary"))
        except ValueError as error:
            raise ValueError("invalid task record enum: {}".format(error))
        fingerprints = value.get("dependency_fingerprints")
        messages = value.get("messages")
        artifacts = value.get("artifacts")
        exception_chain = value.get("exception_chain")
        retry_descriptor = value.get("retry_descriptor")
        if not isinstance(fingerprints, dict):
            raise ValueError("dependency_fingerprints must be an object")
        if not all(
            isinstance(key, str) and isinstance(item, str)
            for key, item in fingerprints.items()
        ):
            raise ValueError("dependency_fingerprints must map strings to strings")
        if not isinstance(messages, list):
            raise ValueError("messages must be an array")
        if not all(isinstance(item, dict) for item in messages):
            raise ValueError("each message must be an object")
        if not isinstance(artifacts, list):
            raise ValueError("artifacts must be an array")
        if not isinstance(exception_chain, list) or not all(
            isinstance(item, str) for item in exception_chain
        ):
            raise ValueError("exception_chain must be an array of strings")
        if retry_descriptor is not None and not isinstance(retry_descriptor, dict):
            raise ValueError("retry_descriptor must be an object or null")
        return cls(
            task_id=_required_string(value, "task_id"),
            kind=_required_string(value, "kind"),
            session_id=_required_string(value, "session_id", allow_empty=True),
            source_revision=_required_int(value, "source_revision"),
            dependency_fingerprints=dict(fingerprints),
            created_at=_required_number(value, "created_at"),
            started_at=_optional_number(value, "started_at"),
            finished_at=_optional_number(value, "finished_at"),
            status=status,
            summary=_required_string(value, "summary", allow_empty=True),
            messages=tuple(dict(item) for item in messages),
            artifacts=tuple(TaskArtifact.from_dict(item) for item in artifacts),
            retry_descriptor=None if retry_descriptor is None else dict(retry_descriptor),
            exception_chain=tuple(exception_chain),
            boundary=boundary,
        )


@dataclass(frozen=True)
class HistoryCorruptWarning:
    reason: str
    quarantine_path: Path


class PathRedactor:
    def __init__(self, home=None, temp=None, workspace=None):
        roots = []
        for marker, path in (
            ("<WORKSPACE>", workspace),
            ("<TEMP>", temp),
            ("<HOME>", home),
        ):
            if path:
                normalized = os.path.normpath(
                    os.path.realpath(os.path.abspath(os.path.expanduser(path)))
                )
                roots.append((normalized, marker))
        self._roots = tuple(sorted(roots, key=lambda item: len(item[0]), reverse=True))

    def redact_text(self, value):
        result = value
        for root, marker in self._roots:
            variants = {root, root.replace("\\", "/"), root.replace("/", "\\")}
            try:
                # Source references are represented as percent-encoded file URIs.
                # Redacting only native paths leaves the same local directory visible
                # in diagnostics and property inspectors.
                variants.add(Path(root).as_uri())
            except ValueError:
                pass
            for variant in sorted(variants, key=len, reverse=True):
                result = re.sub(
                    re.escape(variant) + r"(?![A-Za-z0-9_.-])",
                    marker,
                    result,
                    flags=re.IGNORECASE,
                )
        result = re.sub(
            r"(<(?:WORKSPACE|TEMP|HOME)>)([\\/][^\s\"'<>]*)",
            lambda match: match.group(1) + match.group(2).replace("\\", "/"),
            result,
        )
        return result

    def redact(self, value):
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, dict):
            return {
                self.redact_text(key) if isinstance(key, str) else key: self.redact(item)
                for key, item in value.items()
            }
        if isinstance(value, tuple):
            return tuple(self.redact(item) for item in value)
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        return value


class TaskCenter:
    def __init__(
        self,
        data_location_provider=None,
        now_provider=None,
        home=None,
        temp=None,
        workspace=None,
        persist_raw_paths=False,
        retention_days=30,
        max_records=1000,
        max_bytes=10 * 1024 * 1024,
        max_transient_records=1000,
    ):
        self._data_location_provider = (
            data_location_provider or _default_data_location
        )
        self._now_provider = now_provider or time.time
        self.persist_raw_paths = bool(persist_raw_paths)
        self.retention_days = int(retention_days)
        self.max_records = int(max_records)
        self.max_bytes = int(max_bytes)
        self.max_transient_records = int(max_transient_records)
        if (
            self.retention_days < 0
            or self.max_records < 0
            or self.max_bytes < 1
            or self.max_transient_records < 0
        ):
            raise ValueError("history limits must be non-negative and max_bytes positive")
        self.redactor = PathRedactor(
            home=os.path.expanduser("~") if home is None else home,
            temp=tempfile.gettempdir() if temp is None else temp,
            workspace=workspace,
        )
        self._records = []

    @property
    def records(self):
        return tuple(self._records)

    @property
    def history_path(self):
        return Path(self._data_location_provider()) / HISTORY_FILE_NAME

    def add(self, record):
        if not isinstance(record, TaskRecord):
            raise TypeError("record must be a TaskRecord")
        if any(item.task_id == record.task_id for item in self._records):
            raise ValueError("duplicate task id: {}".format(record.task_id))
        if (
            record.boundary is TaskBoundary.TRANSIENT
            and record.status in _TERMINAL_STATUSES
        ):
            return
        transient_count = sum(
            item.boundary is TaskBoundary.TRANSIENT for item in self._records
        )
        if (
            record.boundary is TaskBoundary.TRANSIENT
            and transient_count >= self.max_transient_records
        ):
            raise RuntimeError("transient task capacity reached")
        self._records.append(record)

    def transition(self, task_id, target, now=None, summary=None):
        for index, record in enumerate(self._records):
            if record.task_id == task_id:
                updated = record.transition(target, now=now, summary=summary)
                if (
                    updated.boundary is TaskBoundary.TRANSIENT
                    and updated.status in _TERMINAL_STATUSES
                ):
                    self._records.pop(index)
                else:
                    self._records[index] = updated
                return updated
        raise KeyError(task_id)

    def apply_result(self, result, now=None, summary=None):
        """Apply a task_runner.TaskResult without coupling history to Qt."""
        stamp = getattr(result, "stamp", None)
        if stamp is None or not isinstance(getattr(stamp, "task_id", None), str):
            raise TypeError("result must provide a TaskStamp")
        status = _coerce_task_status(getattr(result, "status", None))
        if status not in _TERMINAL_STATUSES:
            raise ValueError("task result status must be terminal")
        for index, record in enumerate(self._records):
            if record.task_id != stamp.task_id:
                continue
            if record.session_id != stamp.session_id:
                raise ValueError("task result session_id does not match record")
            if record.source_revision != stamp.source_revision:
                raise ValueError("task result source_revision does not match record")
            error = getattr(result, "error", None)
            working = record
            if error is not None:
                working = replace(
                    working, exception_chain=_format_exception_chain(error)
                )
            if working.status is TaskStatus.QUEUED and status is not TaskStatus.CANCELLED:
                working = working.transition(TaskStatus.RUNNING, now=now)
            result_summary = summary
            if result_summary is None:
                result_summary = str(error) if error is not None else status.value
            completed = _transition_to_terminal(
                working, status, now=now, summary=result_summary
            )
            if completed.boundary is TaskBoundary.TRANSIENT:
                self._records.pop(index)
            else:
                self._records[index] = completed
            return completed
        raise KeyError(stamp.task_id)

    def complete_persistent(
        self,
        task_id,
        status,
        summary=None,
        now=None,
        session_id=None,
        source_revision=None,
        dependency_fingerprints=None,
        messages=None,
        artifacts=None,
        exception=None,
    ):
        """Atomically complete and persist an explicit task record.

        The optional session fields let a logical load task replace its
        placeholder stamp with the session that was actually installed.
        Neither memory nor the existing history file changes unless the new
        terminal record has been written successfully.
        """
        status = _coerce_task_status(status)
        if status not in _TERMINAL_STATUSES:
            raise ValueError("completed task status must be terminal")
        for index, record in enumerate(self._records):
            if record.task_id != task_id:
                continue
            if record.boundary is not TaskBoundary.EXPLICIT:
                raise ValueError("only explicit tasks can be persisted")
            changes = {}
            if session_id is not None:
                if not isinstance(session_id, str):
                    raise TypeError("session_id must be a string")
                changes["session_id"] = session_id
            if source_revision is not None:
                if not isinstance(source_revision, int) or isinstance(
                    source_revision, bool
                ):
                    raise TypeError("source_revision must be an integer")
                changes["source_revision"] = source_revision
            if dependency_fingerprints is not None:
                changes["dependency_fingerprints"] = _copy_fingerprints(
                    dependency_fingerprints
                )
            if messages is not None:
                changes["messages"] = _copy_messages(messages)
            if artifacts is not None:
                changes["artifacts"] = _copy_artifacts(artifacts)
            if exception is not None:
                if not isinstance(exception, BaseException):
                    raise TypeError("exception must be an exception")
                changes["exception_chain"] = _format_exception_chain(exception)
            working = replace(record, **changes) if changes else record
            result_summary = status.value if summary is None else summary
            if not isinstance(result_summary, str):
                raise TypeError("summary must be a string")
            completed = _transition_to_terminal(
                working, status, now=now, summary=result_summary
            )
            candidate = list(self._records)
            candidate[index] = completed
            try:
                self._save_candidate(candidate)
            except OSError:
                self._records = candidate
                raise
            return completed
        raise KeyError(task_id)

    def filtered(self, predicate):
        return tuple(record for record in self._records if predicate(record))

    def copy_payload(self, record, include_raw_paths=False):
        payload = record.to_dict(
            self.redactor, preserve_raw_paths=bool(include_raw_paths)
        )
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)

    def save(self):
        persistent, retained = self._calculate_limits(self._records)
        encoded = self._encode(persistent)
        self._write(encoded)
        self._records = retained

    def _calculate_limits(self, records):
        active = [
            record
            for record in records
            if record.boundary is TaskBoundary.EXPLICIT
            and record.status not in _TERMINAL_STATUSES
        ]
        terminal = [
            record
            for record in records
            if record.boundary is TaskBoundary.EXPLICIT
            and record.status in _TERMINAL_STATUSES
        ]
        active.sort(key=lambda item: (item.created_at, item.task_id))
        terminal.sort(key=lambda item: (item.created_at, item.task_id))
        cutoff = self._now_provider() - self.retention_days * 86400.0
        terminal = [record for record in terminal if record.created_at >= cutoff]
        if self.max_records == 0:
            terminal = []
        else:
            available = max(0, self.max_records - len(active))
            if len(terminal) > available:
                terminal = terminal[-available:] if available else []
        persistent = active + terminal
        persistent.sort(key=lambda item: (item.created_at, item.task_id))
        while terminal and len(self._encode(persistent)) > self.max_bytes:
            removed = terminal.pop(0)
            persistent.remove(removed)
        kept_ids = {record.task_id for record in persistent}
        retained = [
            record
            for record in records
            if record.boundary is TaskBoundary.TRANSIENT or record.task_id in kept_ids
        ]
        return persistent, retained

    def _write(self, encoded):
        path = self.history_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        try:
            with temporary.open("wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(str(temporary), str(path))
            _fsync_directory(path.parent)
        finally:
            try:
                temporary.unlink()
            except OSError:
                pass

    def load(self):
        path = self.history_path
        if not path.exists():
            return ()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            records = self._decode(payload)
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as error:
            warning = self._quarantine(error)
            self._records = []
            return (warning,)
        disk_records = records
        interrupted = {
            TaskStatus.QUEUED,
            TaskStatus.RUNNING,
            TaskStatus.CANCEL_REQUESTED,
        }
        had_interrupted = any(record.status in interrupted for record in records)
        now = self._now_provider()
        records = [
            replace(
                record,
                status=TaskStatus.STALE,
                summary="应用上次退出时任务被中断",
                finished_at=now,
            )
            if record.status in interrupted
            else record
            for record in records
        ]
        retained_persistent, retained = self._calculate_limits(records)
        if retained != records or had_interrupted:
            try:
                self._write(self._encode(retained_persistent))
            except OSError as error:
                # Pruning may roll back to the disk state. Interrupted tasks
                # are different: exposing them as RUNNING without live
                # handles would create permanent zombie tasks for this
                # process, so retain the normalized (but unpruned) view.
                self._records = records if had_interrupted else disk_records
                return (
                    HistoryCorruptWarning(
                        "任务历史清理未能写回：{}".format(
                            self.redactor.redact_text(str(error))
                        ),
                        path,
                    ),
                )
        self._records = retained
        return ()

    def clear_filtered(self, predicate):
        removed_ids = {
            record.task_id
            for record in self._records
            if record.boundary is TaskBoundary.EXPLICIT
            and record.status in _TERMINAL_STATUSES
            and predicate(record)
        }
        candidate = [
            record for record in self._records if record.task_id not in removed_ids
        ]
        self._save_candidate(candidate)
        return len(removed_ids)

    def clear_completed(self):
        removed_ids = {
            record.task_id
            for record in self._records
            if record.boundary is TaskBoundary.EXPLICIT
            and record.status is TaskStatus.SUCCESS
        }
        candidate = [
            record for record in self._records if record.task_id not in removed_ids
        ]
        self._save_candidate(candidate)
        return len(removed_ids)

    def clear_all_persistent(self):
        removed = sum(
            record.boundary is TaskBoundary.EXPLICIT
            and record.status in _TERMINAL_STATUSES
            for record in self._records
        )
        candidate = [
            record
            for record in self._records
            if record.boundary is TaskBoundary.TRANSIENT
            or record.status not in _TERMINAL_STATUSES
        ]
        self._save_candidate(candidate)
        return removed

    def _save_candidate(self, records):
        persistent, retained = self._calculate_limits(records)
        self._write(self._encode(persistent))
        self._records = retained

    def _payload(self, records):
        return {
            "schema": HISTORY_SCHEMA,
            "version": HISTORY_VERSION,
            "records": [
                record.to_dict(self.redactor, self.persist_raw_paths)
                for record in records
            ],
        }

    def _encode(self, records):
        return json.dumps(
            self._payload(records),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def _decode(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("history root must be an object")
        if (
            payload.get("schema") != HISTORY_SCHEMA
            or payload.get("version") != HISTORY_VERSION
        ):
            raise ValueError(
                "unsupported history schema/version: {!r}/{}".format(
                    payload.get("schema"), payload.get("version")
                )
            )
        raw_records = payload.get("records")
        if not isinstance(raw_records, list):
            raise ValueError("history records must be an array")
        records = [TaskRecord.from_dict(item) for item in raw_records]
        if any(record.boundary is not TaskBoundary.EXPLICIT for record in records):
            raise ValueError("transient task found in persistent history")
        task_ids = [record.task_id for record in records]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("duplicate task id in persistent history")
        return records

    def _quarantine(self, error):
        path = self.history_path
        suffix = int(self._now_provider() * 1000)
        quarantine = path.with_name("{}.corrupt-{}".format(path.name, suffix))
        counter = 1
        while quarantine.exists():
            quarantine = path.with_name(
                "{}.corrupt-{}-{}".format(path.name, suffix, counter)
            )
            counter += 1
        try:
            os.replace(str(path), str(quarantine))
        except OSError:
            quarantine = path
        return HistoryCorruptWarning(str(error), quarantine)


def _default_data_location():
    from PyQt5.QtCore import QStandardPaths

    return QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)


def _coerce_task_status(value):
    if isinstance(value, TaskStatus):
        return value
    raw_value = getattr(value, "value", None)
    try:
        return TaskStatus(raw_value)
    except (TypeError, ValueError):
        raise TypeError("target must be a compatible TaskStatus")


def _transition_to_terminal(record, target, now=None, summary=None):
    """Follow required internal states while returning only the terminal record."""
    target = _coerce_task_status(target)
    if target not in _TERMINAL_STATUSES:
        raise ValueError("target task status must be terminal")
    working = record
    if working.status is TaskStatus.QUEUED and target is not TaskStatus.CANCELLED:
        working = working.transition(TaskStatus.RUNNING, now=now)
    if working.status is TaskStatus.RUNNING and target is TaskStatus.CANCELLED:
        working = working.transition(TaskStatus.CANCEL_REQUESTED, now=now)
    return working.transition(target, now=now, summary=summary)


def _copy_fingerprints(value):
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) and isinstance(item, str)
        for key, item in value.items()
    ):
        raise TypeError("dependency_fingerprints must map strings to strings")
    return dict(value)


def _copy_messages(value):
    try:
        items = tuple(value)
    except TypeError:
        raise TypeError("messages must be iterable")
    if not all(isinstance(item, Mapping) for item in items):
        raise TypeError("messages must contain mappings")
    return tuple(dict(item) for item in items)


def _copy_artifacts(value):
    try:
        copied = tuple(value)
    except TypeError:
        raise TypeError("artifacts must be iterable")
    if not all(isinstance(item, TaskArtifact) for item in copied):
        raise TypeError("artifacts must contain TaskArtifact values")
    return copied


def _format_exception_chain(error):
    chain = []
    current = error
    seen = set()
    while isinstance(current, BaseException) and id(current) not in seen:
        seen.add(id(current))
        chain.append("{}: {}".format(type(current).__name__, current))
        current = current.__cause__ or current.__context__
    return tuple(chain)


def _fsync_directory(path):
    if os.name == "nt":
        return
    descriptor = None
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
        os.fsync(descriptor)
    except OSError:
        # The file itself was already flushed and atomically replaced. Some
        # filesystems do not support fsync on directory descriptors.
        return
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _required_string(value, key, allow_empty=False):
    result = value.get(key)
    if not isinstance(result, str) or (not allow_empty and not result):
        raise ValueError("{} must be a string".format(key))
    return result


def _optional_string(value, key, default):
    result = value.get(key, default)
    if not isinstance(result, str):
        raise ValueError("{} must be a string".format(key))
    return result


def _required_int(value, key):
    result = value.get(key)
    if not isinstance(result, int) or isinstance(result, bool):
        raise ValueError("{} must be an integer".format(key))
    return result


def _required_number(value, key):
    result = value.get(key)
    if not isinstance(result, (int, float)) or isinstance(result, bool):
        raise ValueError("{} must be a number".format(key))
    return float(result)


def _optional_number(value, key):
    result = value.get(key)
    if result is None:
        return None
    if not isinstance(result, (int, float)) or isinstance(result, bool):
        raise ValueError("{} must be a number or null".format(key))
    return float(result)


__all__ = [
    "HISTORY_SCHEMA",
    "HISTORY_VERSION",
    "HistoryCorruptWarning",
    "PathRedactor",
    "TaskArtifact",
    "TaskBoundary",
    "TaskCenter",
    "TaskRecord",
    "TaskStatus",
]
