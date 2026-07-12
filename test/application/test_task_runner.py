import threading

import pytest
from PyQt5 import QtCore

from app.application import task_runner
from app.application.task_runner import (
    CancellationToken,
    TaskHandle,
    TaskRunner,
    TaskStamp,
    TaskStatus,
)


@pytest.mark.unittest
def test_cancellation_token_is_cooperative_and_thread_safe():
    token = CancellationToken()
    assert not token.cancelled
    token.cancel()
    assert token.cancelled
    with pytest.raises(RuntimeError, match="cancelled"):
        token.raise_if_cancelled()


@pytest.mark.unittest
def test_task_runner_delivers_result_on_qt_thread(qtbot):
    runner = TaskRunner()
    main_thread = threading.current_thread()
    handle = runner.submit("load", 7, lambda token: (token.cancelled, 42))

    with qtbot.waitSignal(handle.finished, timeout=3000) as signal:
        pass

    result = signal.args[0]
    assert result.status is TaskStatus.SUCCESS
    assert result.value == (False, 42)
    assert threading.current_thread() is main_thread
    runner.shutdown()


@pytest.mark.unittest
def test_task_result_signal_reaches_a_qobject_on_the_main_thread(qtbot):
    class Receiver(QtCore.QObject):
        received = QtCore.pyqtSignal(object)

        @QtCore.pyqtSlot(object)
        def capture(self, result):
            self.received.emit((result, threading.current_thread().ident))

    runner = TaskRunner()
    receiver = Receiver()
    handle = runner.submit("load", 0, lambda token: threading.current_thread().ident)
    handle.finished.connect(receiver.capture)

    with qtbot.waitSignal(receiver.received, timeout=3000) as signal:
        pass

    result, callback_thread_id = signal.args[0]
    assert result.status is TaskStatus.SUCCESS
    assert result.worker_thread_id == result.value
    assert result.worker_thread_id != callback_thread_id
    assert callback_thread_id == threading.current_thread().ident
    runner.shutdown()


@pytest.mark.unittest
def test_same_revision_in_different_sessions_does_not_cross_the_gate(qtbot):
    runner = TaskRunner()
    first = runner.submit("validate", 4, lambda token: "A", session_id="A")
    second = runner.submit("validate", 4, lambda token: "B", session_id="B")

    qtbot.waitUntil(
        lambda: first.result is not None and second.result is not None,
        timeout=3000,
    )

    assert first.result.status is TaskStatus.SUCCESS
    assert second.result.status is TaskStatus.SUCCESS
    runner.shutdown()


@pytest.mark.unittest
def test_revision_gate_marks_completed_old_work_stale(qtbot):
    current_revision = [2]
    runner = TaskRunner(revision_provider=lambda: current_revision[0])
    release = threading.Event()
    handle = runner.submit("validate", 1, lambda token: release.wait(2) or "done")
    release.set()

    with qtbot.waitSignal(handle.finished, timeout=3000) as signal:
        pass

    assert signal.args[0].status is TaskStatus.STALE
    runner.shutdown()


@pytest.mark.unittest
def test_cancelled_task_does_not_publish_success(qtbot):
    runner = TaskRunner()
    started = threading.Event()
    release = threading.Event()

    def work(token):
        started.set()
        release.wait(2)
        token.raise_if_cancelled()
        return "must not publish"

    handle = runner.submit("load", 0, work)
    assert started.wait(2)
    handle.cancel()
    release.set()

    with qtbot.waitSignal(handle.finished, timeout=3000) as signal:
        pass

    assert signal.args[0].status is TaskStatus.CANCELLED
    runner.shutdown()


@pytest.mark.unittest
def test_dependency_stamp_is_checked_before_work_and_before_publish(qtbot):
    accepted = [True]
    work_called = []
    runner = TaskRunner(stamp_validator=lambda stamp: accepted[0])
    accepted[0] = False
    handle = runner.submit(
        "generate",
        3,
        lambda token: work_called.append(True),
        session_id="doc",
        dependency_fingerprint="abc",
    )

    with qtbot.waitSignal(handle.finished, timeout=3000) as signal:
        pass

    assert signal.args[0].status is TaskStatus.STALE
    assert not work_called
    assert handle.stamp.dependency_fingerprint == "abc"
    runner.shutdown()


@pytest.mark.unittest
@pytest.mark.parametrize("raise_on_call", [1, 2])
def test_dependency_validator_exception_still_publishes_failure(
    qtbot, raise_on_call
):
    calls = []

    def validator(stamp):
        calls.append(stamp)
        if len(calls) == raise_on_call:
            raise OSError("fingerprint unavailable")
        return True

    runner = TaskRunner(stamp_validator=validator)
    handle = runner.submit("inspect", 1, lambda token: "done")

    with qtbot.waitSignal(handle.finished, timeout=3000) as signal:
        pass

    assert signal.args[0].status is TaskStatus.FAILED
    assert isinstance(signal.args[0].error, OSError)
    runner.shutdown()


@pytest.mark.unittest
def test_worker_captures_value_and_base_exception_synchronously():
    stamp = TaskStamp("id", "test", "session", 1, 1)
    success_handle = TaskHandle(stamp, CancellationToken())
    success = task_runner._Worker(success_handle, lambda token: 42, None)
    success_payload = []
    success.signals.completed.connect(success_payload.append)
    success.run()
    assert success_payload[0][1:3] == (42, None)

    failure_handle = TaskHandle(stamp, CancellationToken())
    failure = task_runner._Worker(
        failure_handle,
        lambda token: (_ for _ in ()).throw(KeyboardInterrupt("stop")),
        None,
    )
    failure_payload = []
    failure.signals.completed.connect(failure_payload.append)
    failure.run()
    assert isinstance(failure_payload[0][2], KeyboardInterrupt)


@pytest.mark.unittest
def test_invalidate_cancels_matching_active_task_only(qtbot):
    runner = TaskRunner()
    release = threading.Event()
    first = runner.submit(
        "load", 1, lambda token: release.wait(2), session_id="A"
    )
    second = runner.submit("load", 1, lambda token: "B", session_id="B")
    runner.invalidate("load", "A")
    release.set()

    qtbot.waitUntil(
        lambda: first.result is not None and second.result is not None,
        timeout=3000,
    )
    assert first.result.status is TaskStatus.CANCELLED
    assert second.result.status is TaskStatus.SUCCESS
    runner.shutdown()


@pytest.mark.unittest
def test_supersede_marks_matching_active_task_stale_without_cancelling(qtbot):
    runner = TaskRunner()
    release = threading.Event()
    handle = runner.submit(
        "inspect", 1, lambda token: release.wait(2) or "done", session_id="A"
    )
    runner.supersede("inspect", "A")
    release.set()

    qtbot.waitUntil(lambda: handle.result is not None, timeout=3000)

    assert handle.result.status is TaskStatus.STALE
    assert not handle.token.cancelled
    runner.shutdown()


@pytest.mark.unittest
def test_new_generation_cancels_previous_and_shutdown_rejects_submit(qtbot):
    runner = TaskRunner()
    release = threading.Event()
    first = runner.submit("validate", 1, lambda token: release.wait(2))
    second = runner.submit("validate", 1, lambda token: "new")
    release.set()

    qtbot.waitUntil(
        lambda: first.result is not None and second.result is not None,
        timeout=3000,
    )
    assert first.result.status is TaskStatus.CANCELLED
    assert second.result.status is TaskStatus.SUCCESS
    runner.shutdown()
    with pytest.raises(RuntimeError, match="shut down"):
        runner.submit("late", 1, lambda token: None)


@pytest.mark.unittest
def test_post_execution_false_validator_marks_result_stale(qtbot):
    calls = []

    def validator(stamp):
        calls.append(stamp)
        return len(calls) == 1

    runner = TaskRunner(stamp_validator=validator)
    handle = runner.submit("inspect", 1, lambda token: "done")

    with qtbot.waitSignal(handle.finished, timeout=3000) as signal:
        pass

    assert signal.args[0].status is TaskStatus.STALE
    runner.shutdown()
