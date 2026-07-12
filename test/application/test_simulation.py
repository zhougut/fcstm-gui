from __future__ import unicode_literals

from app.application.simulation import SimulationRunControl, SimulationService
from pyfcstm.simulate import SimulationRuntime


BASIC_SOURCE = """
def int x = 2;
def int y = 0;
state Root {
    state A { during { x = x + 1; } }
    state B { during { y = y + 10; } }
    state C { during { y = y + 100; } }
    [*] -> A;
    A -> B :: Go effect { x = x + 5; }
    B -> C :: Next;
    C -> [*] :: Stop;
}
"""


def test_start_creates_independent_runtime_with_stamp_and_initial_values():
    service = SimulationService()
    session = service.start(
        BASIC_SOURCE,
        source_uri="file:///machine.fcstm",
        source_revision=7,
        dependency_fingerprint="deps-a",
        initial_state=("Root", "B"),
        initial_vars={"x": 40, "y": 2},
    )

    assert isinstance(session.runtime, SimulationRuntime)
    assert session.source_revision == 7
    assert session.dependency_fingerprint == "deps-a"
    assert session.matches(7, "deps-a")
    assert not session.matches(8, "deps-a")
    assert session.snapshot().state_path == ("Root", "B")
    assert session.snapshot().vars == {"x": 40, "y": 2}

    result = service.cycle(session)

    assert result.error is None
    assert result.snapshot.state_path == ("Root", "B")
    assert result.snapshot.vars == {"x": 40, "y": 12}
    assert result.snapshot.cycle == 1
    assert result.snapshot.ended is False
    assert result.snapshot.source_revision == 7
    assert result.snapshot.dependency_fingerprint == "deps-a"


def test_cycle_reports_same_cycle_multi_event_accounting_and_state():
    service = SimulationService()
    session = service.start(
        BASIC_SOURCE,
        source_uri="memory://basic",
        source_revision=1,
        dependency_fingerprint="deps-b",
    )
    service.cycle(session)

    result = service.cycle(session, events=("Go", "Root.B.Next"))

    assert result.error is None
    assert result.input_events == ("Root.A.Go", "Root.B.Next")
    assert result.consumed_events == ("Root.A.Go",)
    assert result.unconsumed_events == ("Root.B.Next",)
    assert result.snapshot.state_path == ("Root", "B")
    assert result.snapshot.vars == {"x": 8, "y": 10}
    assert result.snapshot.ended is False
    assert result.snapshot.cycle == 2


def test_cycle_can_end_and_reports_cycle_boundary():
    service = SimulationService()
    session = service.start(
        BASIC_SOURCE,
        source_uri="memory://end",
        source_revision=2,
        dependency_fingerprint=None,
        initial_state=("Root", "C"),
        initial_vars={"x": 2, "y": 0},
    )

    result = service.cycle(session, events="Stop")

    assert result.error is None
    assert result.consumed_events == ("Root.C.Stop",)
    assert result.snapshot.ended is True
    assert result.snapshot.state_path == ()
    assert result.snapshot.cycle == 1


class BoundaryCancelToken(object):
    def __init__(self, cancel_on_call):
        self.cancel_on_call = cancel_on_call
        self.calls = 0

    def is_cancelled(self):
        self.calls += 1
        return self.calls >= self.cancel_on_call


def test_run_many_checks_cancel_token_only_between_cycles():
    service = SimulationService()
    session = service.start(
        BASIC_SOURCE,
        source_uri="memory://run",
        source_revision=3,
        dependency_fingerprint="deps-run",
    )
    token = BoundaryCancelToken(cancel_on_call=3)

    run = service.run(session, max_cycles=5, cancel_token=token)

    assert token.calls == 3
    assert run.cancelled is True
    assert len(run.cycles) == 2
    assert run.cycles[-1].snapshot.cycle == 2
    assert run.cycles[-1].snapshot.state_path == ("Root", "A")
    assert run.cycles[-1].snapshot.vars == {"x": 4, "y": 0}


class BoundaryRunControl(object):
    def __init__(self, pause_on_call=None, stale_on_call=None):
        self.pause_on_call = pause_on_call
        self.stale_on_call = stale_on_call
        self.pause_calls = 0
        self.stale_calls = 0

    def is_pause_requested(self):
        self.pause_calls += 1
        return (
            self.pause_on_call is not None
            and self.pause_calls >= self.pause_on_call
        )

    def is_stale_requested(self):
        self.stale_calls += 1
        return (
            self.stale_on_call is not None
            and self.stale_calls >= self.stale_on_call
        )


def test_run_pauses_at_cycle_boundary_and_same_runtime_can_continue():
    service = SimulationService()
    session = service.start(
        BASIC_SOURCE,
        source_uri="memory://pause",
        source_revision=8,
        dependency_fingerprint="deps-pause",
    )
    control = BoundaryRunControl(pause_on_call=3)

    paused = service.run(session, max_cycles=5, run_control=control)

    assert paused.paused is True
    assert paused.cancelled is False
    assert paused.stale is False
    assert len(paused.cycles) == 2
    runtime = session.runtime
    continued = service.run(session, max_cycles=2)
    assert session.runtime is runtime
    assert len(continued.cycles) == 2
    assert continued.cycles[-1].snapshot.cycle == 4


def test_run_stale_wins_over_pause_at_same_cycle_boundary():
    service = SimulationService()
    session = service.start(
        BASIC_SOURCE,
        source_uri="memory://stale",
        source_revision=9,
        dependency_fingerprint="deps-stale",
    )
    control = BoundaryRunControl(pause_on_call=2, stale_on_call=2)

    result = service.run(session, max_cycles=5, run_control=control)

    assert result.stale is True
    assert result.paused is False
    assert result.cancelled is False
    assert len(result.cycles) == 1


def test_run_stops_after_terminal_cycle_and_accounts_iterable_events():
    service = SimulationService()
    session = service.start(
        BASIC_SOURCE,
        source_uri="memory://terminal-run",
        source_revision=10,
        dependency_fingerprint=None,
        initial_state=("Root", "C"),
        initial_vars={"x": 2, "y": 0},
    )

    result = service.run(
        session,
        max_cycles=5,
        events_per_cycle=(("Stop",),),
    )

    assert len(result.cycles) == 1
    assert result.cycles[0].input_events == ("Root.C.Stop",)
    assert result.cycles[0].snapshot.ended is True


def test_run_accepts_cancelled_method_or_boolean_property_tokens():
    service = SimulationService()

    class CallableToken(object):
        def cancelled(self):
            return True

    class BooleanToken(object):
        cancelled = True

    for token in (CallableToken(), BooleanToken()):
        session = service.start(
            BASIC_SOURCE,
            source_uri="memory://cancel-shape",
            source_revision=11,
            dependency_fingerprint=None,
        )
        result = service.run(session, max_cycles=1, cancel_token=token)
        assert result.cancelled is True
        assert result.cycles == ()


def test_long_run_crosses_cooperative_gui_scheduling_boundary():
    service = SimulationService()
    session = service.start(
        BASIC_SOURCE,
        source_uri="memory://cooperative-yield",
        source_revision=12,
        dependency_fingerprint=None,
    )

    result = service.run(session, max_cycles=33)

    assert len(result.cycles) == 33
    assert result.cycles[-1].snapshot.cycle == 33


def test_thread_safe_run_control_records_pause_and_stale_requests():
    control = SimulationRunControl()
    assert control.is_pause_requested() is False
    assert control.is_stale_requested() is False

    control.request_pause()
    control.request_stale()

    assert control.is_pause_requested() is True
    assert control.is_stale_requested() is True


def test_reset_creates_new_runtime_and_restores_initial_configuration():
    service = SimulationService()
    session = service.start(
        BASIC_SOURCE,
        source_uri="memory://reset",
        source_revision=4,
        dependency_fingerprint="deps-reset",
        initial_state=("Root", "B"),
        initial_vars={"x": 1, "y": 5},
    )
    old_runtime = session.runtime
    service.cycle(session)

    snapshot = service.reset(session)

    assert session.runtime is not old_runtime
    assert isinstance(session.runtime, SimulationRuntime)
    assert snapshot.cycle == 0
    assert snapshot.state_path == ("Root", "B")
    assert snapshot.vars == {"x": 1, "y": 5}
    assert service.cycle(session).snapshot.vars == {"x": 1, "y": 15}


def test_cycle_exception_records_type_message_cause_and_rolls_runtime_back():
    source = """
def int x = 0;
def int y = 1;
state Root {
    state A { during { x = x + 1; } }
    state B;
    [*] -> A;
    A -> B :: Boom effect { x = x + 10; y = 1 / 0; }
}
"""
    service = SimulationService()
    session = service.start(
        source,
        source_uri="memory://boom",
        source_revision=5,
        dependency_fingerprint="deps-boom",
    )
    service.cycle(session)
    before = session.snapshot()

    result = service.cycle(session, events="Boom")
    after = session.snapshot()

    assert result.error is not None
    assert result.error.type == "SimulationRuntimeExpressionError"
    assert "division by zero" in result.error.message
    assert result.error.cause_type == "ZeroDivisionError"
    assert result.error.cause_message == "division by zero"
    assert result.input_events == ("Boom",)
    assert result.rollback_preserved is True
    assert result.snapshot == before
    assert after == before
    assert session.runtime.vars == {"x": 1, "y": 1}
    assert session.runtime.current_state.path == ("Root", "A")


def test_start_rejects_dynamic_expected_payloads_in_plain_simulation():
    service = SimulationService()

    try:
        service.start(
            BASIC_SOURCE,
            source_uri="memory://expected",
            source_revision=6,
            dependency_fingerprint="deps-expected",
            expected={"state": "Root.A"},
        )
    except TypeError as error:
        assert "expected" in str(error)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("plain simulation accepted dynamic validation expected data")


def test_start_uses_file_context_for_imports_or_an_existing_valid_model(tmp_path):
    child = tmp_path / "child.fcstm"
    child.write_text("state Child;", encoding="utf-8")
    root = tmp_path / "root.fcstm"
    source = (
        'state Root { import "./child.fcstm" as Child; '
        "[*] -> Child; Child -> [*]; }"
    )
    root.write_text(source, encoding="utf-8")
    service = SimulationService()

    from_file_context = service.start(
        source,
        "file:///root.fcstm",
        0,
        "deps",
        source_path=str(root),
    )
    from_model = service.start(
        "not parsed when model is supplied",
        "file:///root.fcstm",
        0,
        "deps",
        model=from_file_context.model,
    )

    assert service.cycle(from_file_context).snapshot.state_path == (
        "Root",
        "Child",
    )
    assert service.cycle(from_model).snapshot.state_path == ("Root", "Child")
