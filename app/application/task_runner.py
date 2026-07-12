import threading
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple

from PyQt5 import QtCore


class TaskStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STALE = "stale"


class TaskCancelledError(RuntimeError):
    pass


class TaskStaleError(RuntimeError):
    pass


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise TaskCancelledError("task was cancelled")


@dataclass(frozen=True)
class TaskStamp:
    task_id: str
    channel: str
    session_id: str
    source_revision: int
    request_generation: int
    dependency_fingerprint: Optional[str] = None


@dataclass(frozen=True)
class TaskResult:
    stamp: TaskStamp
    status: TaskStatus
    value: Any = None
    error: Optional[BaseException] = None
    worker_thread_id: Optional[int] = None


class TaskHandle(QtCore.QObject):
    finished = QtCore.pyqtSignal(object)

    def __init__(self, stamp: TaskStamp, token: CancellationToken) -> None:
        super().__init__()
        self.stamp = stamp
        self.token = token
        self.result = None  # type: Optional[TaskResult]

    def cancel(self) -> None:
        self.token.cancel()


class _WorkerSignals(QtCore.QObject):
    completed = QtCore.pyqtSignal(object)


class _Worker(QtCore.QRunnable):
    def __init__(
        self,
        handle: TaskHandle,
        work: Callable[[CancellationToken], Any],
        stamp_validator: Optional[Callable[[TaskStamp], bool]],
    ) -> None:
        super().__init__()
        self.handle = handle
        self.work = work
        self.stamp_validator = stamp_validator
        self.signals = _WorkerSignals()

    def run(self) -> None:
        value = None
        error = None
        try:
            self.handle.token.raise_if_cancelled()
            if (
                self.stamp_validator is not None
                and not self.stamp_validator(self.handle.stamp)
            ):
                raise TaskStaleError("task stamp is stale before execution")
            value = self.work(self.handle.token)
        except BaseException as caught:
            error = caught
        self.signals.completed.emit(
            (
                self.handle,
                value,
                error,
                threading.current_thread().ident,
            )
        )


class TaskRunner(QtCore.QObject):
    def __init__(
        self,
        revision_provider: Optional[Callable[[], int]] = None,
        stamp_validator: Optional[Callable[[TaskStamp], bool]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._pool = QtCore.QThreadPool()
        self._revision_provider = revision_provider
        self._stamp_validator = stamp_validator
        self._generations = {}  # type: Dict[Tuple[str, str], int]
        self._active = {}  # type: Dict[str, Tuple[TaskHandle, _Worker]]
        self._accepting = True

    def submit(
        self,
        kind: str,
        source_revision: int,
        work: Callable[[CancellationToken], Any],
        session_id: str = "",
        channel: Optional[str] = None,
        dependency_fingerprint: Optional[str] = None,
    ) -> TaskHandle:
        if not self._accepting:
            raise RuntimeError("task runner is shut down")
        channel = channel or kind
        key = (channel, session_id)
        generation = self._generations.get(key, 0) + 1
        self._generations[key] = generation
        for active_handle, _ in tuple(self._active.values()):
            if (
                active_handle.stamp.channel,
                active_handle.stamp.session_id,
            ) == key:
                active_handle.cancel()
        stamp = TaskStamp(
            task_id=uuid.uuid4().hex,
            channel=channel,
            session_id=session_id,
            source_revision=source_revision,
            request_generation=generation,
            dependency_fingerprint=dependency_fingerprint,
        )
        handle = TaskHandle(stamp, CancellationToken())
        worker = _Worker(handle, work, self._stamp_validator)
        worker.signals.completed.connect(
            self._complete,
            type=QtCore.Qt.QueuedConnection,
        )
        self._active[stamp.task_id] = (handle, worker)
        self._pool.start(worker)
        return handle

    def invalidate(self, channel: str, session_id: str = "") -> None:
        key = (channel, session_id)
        self._generations[key] = self._generations.get(key, 0) + 1
        for handle, _ in tuple(self._active.values()):
            if (handle.stamp.channel, handle.stamp.session_id) == key:
                handle.cancel()

    def supersede(self, channel: str, session_id: str = "") -> None:
        """Mark matching work stale without treating it as user cancellation."""
        key = (channel, session_id)
        self._generations[key] = self._generations.get(key, 0) + 1

    @QtCore.pyqtSlot(object)
    def _complete(self, payload) -> None:
        handle, value, error, worker_thread_id = payload
        stamp = handle.stamp
        key = (stamp.channel, stamp.session_id)
        current_generation = self._generations.get(key)
        post_error = None
        post_valid = True
        if error is None and self._stamp_validator is not None:
            try:
                post_valid = self._stamp_validator(stamp)
            except BaseException as caught:
                post_valid = False
                post_error = caught
        if handle.token.cancelled or isinstance(error, TaskCancelledError):
            status = TaskStatus.CANCELLED
        elif isinstance(error, TaskStaleError):
            status = TaskStatus.STALE
        elif current_generation != stamp.request_generation:
            status = TaskStatus.STALE
        elif (
            self._revision_provider is not None
            and self._revision_provider() != stamp.source_revision
        ):
            status = TaskStatus.STALE
        elif error is not None:
            status = TaskStatus.FAILED
        elif post_error is not None:
            status = TaskStatus.FAILED
            error = post_error
        elif not post_valid:
            status = TaskStatus.STALE
        else:
            status = TaskStatus.SUCCESS
        result = TaskResult(
            stamp=stamp,
            status=status,
            value=value,
            error=error,
            worker_thread_id=worker_thread_id,
        )
        handle.result = result
        self._active.pop(stamp.task_id, None)
        handle.finished.emit(result)

    def shutdown(self, wait: bool = True) -> None:
        self._accepting = False
        for handle, _ in tuple(self._active.values()):
            handle.cancel()
        self._pool.clear()
        if wait:
            self._pool.waitForDone(5000)
