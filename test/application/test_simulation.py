from __future__ import unicode_literals

from app.application.simulation import SimulationService
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
