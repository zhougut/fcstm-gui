"""Application service for ordinary pyfcstm simulation sessions."""

from __future__ import unicode_literals

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from pyfcstm.model import load_state_machine_from_text
from pyfcstm.simulate import SimulationRuntime, SimulationRuntimeTerminalStateError


@dataclass(frozen=True)
class SimulationSnapshot:
    source_uri: str
    source_revision: int
    dependency_fingerprint: Optional[str]
    cycle: int
    state_path: Tuple[str, ...]
    vars: Dict[str, Any]
    ended: bool


@dataclass(frozen=True)
class SimulationErrorRecord:
    type: str
    message: str
    cause_type: Optional[str]
    cause_message: Optional[str]


@dataclass(frozen=True)
class SimulationCycleResult:
    snapshot: SimulationSnapshot
    input_events: Tuple[str, ...]
    consumed_events: Tuple[str, ...]
    unconsumed_events: Tuple[str, ...]
    error: Optional[SimulationErrorRecord] = None
    rollback_preserved: Optional[bool] = None


@dataclass(frozen=True)
class SimulationRunResult:
    cycles: Tuple[SimulationCycleResult, ...]
    cancelled: bool


@dataclass
class SimulationSession:
    source_uri: str
    source_revision: int
    dependency_fingerprint: Optional[str]
    model: Any
    initial_state: Optional[Any]
    initial_vars: Optional[Dict[str, Any]]
    runtime: SimulationRuntime

    def matches(
        self,
        source_revision: int,
        dependency_fingerprint: Optional[str],
    ) -> bool:
        return (
            self.source_revision == source_revision
            and self.dependency_fingerprint == dependency_fingerprint
        )

    def snapshot(self) -> SimulationSnapshot:
        return _snapshot(
            self.runtime,
            self.source_uri,
            self.source_revision,
            self.dependency_fingerprint,
        )


class SimulationService:
    """Create and advance stateful pyfcstm SimulationRuntime sessions."""

    def start(
        self,
        source_text: str,
        source_uri: str,
        source_revision: int,
        dependency_fingerprint: Optional[str],
        initial_state: Optional[Any] = None,
        initial_vars: Optional[Mapping[str, Any]] = None,
        source_path: Optional[str] = None,
        model: Optional[Any] = None,
        **kwargs: Any
    ) -> SimulationSession:
        if kwargs:
            names = ", ".join(sorted(kwargs))
            raise TypeError(
                "plain simulation does not accept dynamic validation payloads: "
                + names
            )
        if model is None:
            model = load_state_machine_from_text(source_text, path=source_path)
        runtime_initial_vars = dict(initial_vars) if initial_vars is not None else None
        runtime = SimulationRuntime(
            model,
            initial_state=initial_state,
            initial_vars=runtime_initial_vars,
        )
        stored_initial_vars = (
            dict(initial_vars) if initial_vars is not None else None
        )
        return SimulationSession(
            source_uri=source_uri,
            source_revision=source_revision,
            dependency_fingerprint=dependency_fingerprint,
            model=model,
            initial_state=initial_state,
            initial_vars=stored_initial_vars,
            runtime=runtime,
        )

    def cycle(
        self,
        session: SimulationSession,
        events: Any = None,
    ) -> SimulationCycleResult:
        before = session.snapshot()
        try:
            native = session.runtime.cycle(events)
        except Exception as error:  # noqa: BLE001 - service records runtime errors
            after = session.snapshot()
            return SimulationCycleResult(
                snapshot=after,
                input_events=_event_inputs(events),
                consumed_events=(),
                unconsumed_events=(),
                error=_error_record(error),
                rollback_preserved=after == before,
            )
        return SimulationCycleResult(
            snapshot=session.snapshot(),
            input_events=tuple(native.input_events),
            consumed_events=tuple(native.consumed_events),
            unconsumed_events=tuple(native.unconsumed_events),
        )

    def run(
        self,
        session: SimulationSession,
        max_cycles: int,
        events_per_cycle: Sequence[Any] = (),
        cancel_token: Optional[Any] = None,
    ) -> SimulationRunResult:
        cycles = []
        cancelled = False
        for index in range(max(0, max_cycles)):
            if _is_cancelled(cancel_token):
                cancelled = True
                break
            events = events_per_cycle[index] if index < len(events_per_cycle) else None
            result = self.cycle(session, events=events)
            cycles.append(result)
            if result.error is not None or result.snapshot.ended:
                break
        return SimulationRunResult(cycles=tuple(cycles), cancelled=cancelled)

    def reset(self, session: SimulationSession) -> SimulationSnapshot:
        initial_vars = (
            dict(session.initial_vars) if session.initial_vars is not None else None
        )
        session.runtime = SimulationRuntime(
            session.model,
            initial_state=session.initial_state,
            initial_vars=initial_vars,
        )
        return session.snapshot()


def _snapshot(
    runtime: SimulationRuntime,
    source_uri: str,
    source_revision: int,
    dependency_fingerprint: Optional[str],
) -> SimulationSnapshot:
    return SimulationSnapshot(
        source_uri=source_uri,
        source_revision=source_revision,
        dependency_fingerprint=dependency_fingerprint,
        cycle=runtime.cycle_count,
        state_path=_state_path(runtime),
        vars=dict(runtime.vars),
        ended=runtime.is_ended,
    )


def _state_path(runtime: SimulationRuntime) -> Tuple[str, ...]:
    if runtime.is_ended or not runtime.stack:
        return ()
    try:
        return tuple(runtime.current_state.path)
    except SimulationRuntimeTerminalStateError:
        return ()


def _error_record(error: BaseException) -> SimulationErrorRecord:
    cause = error.__cause__ or error.__context__
    return SimulationErrorRecord(
        type=type(error).__name__,
        message=str(error),
        cause_type=type(cause).__name__ if cause is not None else None,
        cause_message=str(cause) if cause is not None else None,
    )


def _event_inputs(events: Any) -> Tuple[str, ...]:
    if events is None:
        return ()
    if isinstance(events, str):
        return (events,)
    return tuple(str(item) for item in events)


def _is_cancelled(cancel_token: Optional[Any]) -> bool:
    if cancel_token is None:
        return False
    checker = getattr(cancel_token, "is_cancelled", None)
    if callable(checker):
        return bool(checker())
    checker = getattr(cancel_token, "cancelled", None)
    if callable(checker):
        return bool(checker())
    return bool(checker)
