from __future__ import unicode_literals

import json
from copy import deepcopy

import pytest

from app.application.dynamic_validation import (
    DynamicValidationCaseReport,
    DynamicValidationProvenanceReport,
    DynamicValidationService,
    DynamicValidationSuiteReport,
    _diff_expected,
    _exception_dict,
    _is_cancelled,
    _validate_provenance_payload,
)


SIMPLE_SOURCE = """
def int x = 0;
def int y = 9;
state Root {
    state A { during { x = x + 1; } }
    state B { during { x = x + 10; } }
    [*] -> A;
    A -> B :: Go;
    B -> A :: Back;
}
"""


def _scenario(model_file, steps, initial=None, case_id="user_case"):
    return {
        "schema": "fcstm-gui.dynamic-validation-scenario",
        "version": 1,
        "case_id": case_id,
        "model_file": model_file,
        "initial": initial or {"state": None, "variables": {}},
        "steps": steps,
    }


def test_loader_is_strict_versioned_json_and_expected_types(tmp_path):
    service = DynamicValidationService()
    model = tmp_path / "m.fcstm"
    model.write_text(SIMPLE_SOURCE, encoding="utf-8")
    scenario = _scenario(
        "m.fcstm",
        [{"events": [], "commands": [], "expected": {"state": "Root.A"}}],
    )

    loaded = service.load_scenario(scenario, base_dir=tmp_path)
    assert loaded.case_id == "user_case"
    assert loaded.model_text == SIMPLE_SOURCE

    invalid = dict(scenario)
    invalid["version"] = 2
    try:
        service.load_scenario(invalid, base_dir=tmp_path)
    except ValueError as error:
        assert "version" in str(error)
    else:
        raise AssertionError("accepted wrong scenario version")

    invalid = dict(scenario)
    invalid["extra"] = True
    try:
        service.load_scenario(invalid, base_dir=tmp_path)
    except ValueError as error:
        assert "unexpected" in str(error)
    else:
        raise AssertionError("accepted additional scenario field")

    invalid = dict(scenario)
    invalid["steps"] = [
        {"events": [], "commands": [], "expected": {"variables": []}}
    ]
    try:
        service.load_scenario(invalid, base_dir=tmp_path)
    except ValueError as error:
        assert "expected.variables" in str(error)
    else:
        raise AssertionError("accepted invalid expected variables")


def test_user_scenario_runs_independent_runtime_multi_event_reset_and_json_roundtrip(tmp_path):
    service = DynamicValidationService()
    (tmp_path / "m.fcstm").write_text(SIMPLE_SOURCE, encoding="utf-8")
    scenario = _scenario(
        "m.fcstm",
        [
            {
                "events": [],
                "commands": [],
                "expected": {"state": "Root.A", "variables": {"x": 1}, "ended": False},
            },
            {
                "events": ["Root.A.Go", "Root.B.Back"],
                "commands": [],
                "expected": {"state": "Root.B", "variables": {"x": 11}, "ended": False},
            },
            {
                "events": [],
                "commands": ["reset"],
                "expected": {"state": "Root.A", "variables": {"x": 1}, "ended": False},
            },
        ],
    )

    first = service.run_scenario(scenario, base_dir=tmp_path)
    second = service.run_scenario(scenario, base_dir=tmp_path)

    assert first.status == "passed"
    assert second.status == "passed"
    assert [step.status for step in first.steps] == ["passed", "passed", "passed"]
    assert first.steps[1].input_events == ("Root.A.Go", "Root.B.Back")
    assert first.steps[1].consumed_events == ("Root.A.Go",)
    assert first.steps[1].unconsumed_events == ("Root.B.Back",)
    assert first.steps[2].commands == ("reset",)
    assert first.steps[2].actual["cycle"] == 1

    encoded = json.dumps(first.to_json_dict(), sort_keys=True)
    decoded = json.loads(encoded)
    assert decoded["schema"] == "fcstm-gui.dynamic-validation-report.case"
    assert decoded["version"] == 1
    assert decoded["case_id"] == "user_case"
    assert decoded["status"] == "passed"
    assert decoded["source_revision"] == 1
    assert len(decoded["dependency_fingerprint"]) == 64
    assert len(decoded["scenario_sha256"]) == 64
    assert decoded["steps"][1]["diffs"] == []


def test_expected_exception_and_rollback_are_compared_from_real_runtime():
    service = DynamicValidationService()
    report = service.run_packaged_case("expression_failure_transition_guard_raises_expression_error")

    assert report.status == "passed"
    failing = report.steps[-1]
    assert failing.status == "expected_exception_passed"
    assert failing.actual["exception"]["type"] == "SimulationRuntimeExpressionError"
    assert failing.actual["exception"]["cause_type"] == "ZeroDivisionError"
    assert failing.actual["rollback"] is True


def test_state_mutation_reports_precise_state_diff_and_original_packaged_case_still_passes(tmp_path):
    service = DynamicValidationService()
    source_dir = service.resource_dir
    model_text = (
        source_dir / "design_validation_failure_multilevel_transition.fcstm"
    ).read_text(encoding="utf-8")
    scenario = json.loads(
        (source_dir / "design_validation_failure_multilevel_transition.json").read_text(
            encoding="utf-8"
        )
    )
    scenario["model_file"] = "design_validation_failure_multilevel_transition.fcstm"
    scenario["case_id"] = "root_mutated_expected"
    scenario["steps"][3]["expected"]["state"] = "Root.Mutated"
    (tmp_path / scenario["model_file"]).write_text(model_text, encoding="utf-8")

    report = service.run_scenario(scenario, base_dir=tmp_path)

    assert report.status == "mismatch"
    assert [step.status for step in report.steps[:3]] == ["passed", "passed", "passed"]
    assert report.steps[3].status == "mismatch"
    assert report.steps[3].actual["state"] == "Root.A"
    assert report.steps[3].diffs == [
        {"path": "state", "expected": "Root.Mutated", "actual": "Root.A"}
    ]

    original = service.run_packaged_case("design_validation_failure_multilevel_transition")
    assert original.status == "passed"


def test_packaged_provenance_checks_all_eight_resource_hashes_and_all_cases_pass():
    service = DynamicValidationService()

    provenance = service.verify_packaged_provenance()
    assert provenance.status == "passed"
    assert len(provenance.resources) == 8
    assert all(item["ok"] for item in provenance.resources)

    report = service.run_packaged_cases()
    assert report.status == "passed"
    assert sorted(item.case_id for item in report.cases) == [
        "design_evented_pseudo_chain_invalid_then_valid",
        "design_validation_failure_multilevel_transition",
        "expression_failure_transition_guard_raises_expression_error",
        "pseudo_self_loop_step_limit_raises_dfs_error",
    ]
    assert all(item.status == "passed" for item in report.cases)


def test_runtime_error_without_expected_exception_is_failed(tmp_path):
    service = DynamicValidationService()
    (tmp_path / "m.fcstm").write_text(SIMPLE_SOURCE, encoding="utf-8")
    scenario = _scenario(
        "m.fcstm",
        [
            {
                "events": ["Root.Missing.Event"],
                "commands": [],
                "expected": {"state": "Root.A"},
            }
        ],
    )

    report = service.run_scenario(scenario, base_dir=tmp_path)

    assert report.status == "failed"
    assert report.steps[0].status == "failed"
    assert report.steps[0].actual["exception"]["type"] == "SimulationRuntimeEventError"


def test_default_resource_dir_supports_pyinstaller_meipass(monkeypatch, tmp_path):
    import app.application.dynamic_validation as dynamic_validation

    monkeypatch.setattr(dynamic_validation.sys, "frozen", True, raising=False)
    monkeypatch.setattr(dynamic_validation.sys, "_MEIPASS", str(tmp_path), raising=False)

    assert dynamic_validation._default_resource_dir() == (
        tmp_path / "app" / "resources" / "self_check" / "dynamic_validation"
    )


class CancelAfterFirst(object):
    def __init__(self):
        self.calls = 0

    def is_cancelled(self):
        self.calls += 1
        return self.calls > 1


def test_cancel_token_is_checked_on_step_boundary(tmp_path):
    service = DynamicValidationService()
    (tmp_path / "m.fcstm").write_text(SIMPLE_SOURCE, encoding="utf-8")
    scenario = _scenario(
        "m.fcstm",
        [
            {
                "events": [],
                "commands": [],
                "expected": {"state": "Root.A", "variables": {"x": 1}},
            },
            {
                "events": [],
                "commands": [],
                "expected": {"state": "Root.A", "variables": {"x": 2}},
            },
        ],
    )

    report = service.run_scenario(
        scenario, base_dir=tmp_path, cancel_token=CancelAfterFirst()
    )

    assert report.status == "cancelled"
    assert len(report.steps) == 1
    assert report.steps[0].status == "passed"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: [], "JSON object"),
        (lambda value: {key: item for key, item in value.items() if key != "case_id"}, "missing"),
        (lambda value: dict(value, schema="wrong"), "schema"),
        (lambda value: dict(value, case_id=""), "case_id"),
        (lambda value: dict(value, model_file="nested/m.fcstm"), "model_file"),
        (lambda value: dict(value, initial={"state": None}), "initial"),
        (lambda value: dict(value, initial={"state": 1, "variables": {}}), "initial.state"),
        (lambda value: dict(value, initial={"state": None, "variables": []}), "initial.variables"),
        (lambda value: dict(value, steps=[]), "non-empty"),
        (lambda value: dict(value, steps=[{"events": [], "expected": {}}]), "exactly"),
        (
            lambda value: dict(
                value,
                steps=[{"events": [1], "commands": [], "expected": {}}],
            ),
            "events",
        ),
        (
            lambda value: dict(
                value,
                steps=[{"events": [], "commands": ["stop"], "expected": {}}],
            ),
            "commands",
        ),
        (
            lambda value: dict(
                value,
                steps=[{"events": [], "commands": [], "expected": []}],
            ),
            "expected must",
        ),
        (
            lambda value: dict(
                value,
                steps=[{"events": [], "commands": [], "expected": {"other": 1}}],
            ),
            "unexpected",
        ),
        (
            lambda value: dict(
                value,
                steps=[{"events": [], "commands": [], "expected": {"state": 1}}],
            ),
            "expected.state",
        ),
        (
            lambda value: dict(
                value,
                steps=[{"events": [], "commands": [], "expected": {"ended": 1}}],
            ),
            "expected.ended",
        ),
        (
            lambda value: dict(
                value,
                steps=[{"events": [], "commands": [], "expected": {"rollback": 1}}],
            ),
            "expected.rollback",
        ),
        (
            lambda value: dict(
                value,
                steps=[{"events": [], "commands": [], "expected": {"exception": []}}],
            ),
            "exception must",
        ),
        (
            lambda value: dict(
                value,
                steps=[
                    {"events": [], "commands": [], "expected": {"exception": {"other": 1}}}
                ],
            ),
            "unexpected",
        ),
        (
            lambda value: dict(
                value,
                steps=[
                    {"events": [], "commands": [], "expected": {"exception": {"type": 1}}}
                ],
            ),
            "exception.type",
        ),
        (
            lambda value: dict(
                value,
                steps=[
                    {
                        "events": [],
                        "commands": [],
                        "expected": {"exception": {"cause_contains": 1}},
                    }
                ],
            ),
            "cause_contains",
        ),
    ],
)
def test_scenario_schema_rejects_each_invalid_shape(tmp_path, mutate, message):
    (tmp_path / "m.fcstm").write_text(SIMPLE_SOURCE, encoding="utf-8")
    valid = _scenario(
        "m.fcstm", [{"events": [], "commands": [], "expected": {}}]
    )

    with pytest.raises(ValueError, match=message):
        DynamicValidationService().load_scenario(mutate(deepcopy(valid)), base_dir=tmp_path)


def test_input_file_failures_return_structured_case_failure(tmp_path):
    service = DynamicValidationService(tmp_path)
    invalid_json = tmp_path / "broken.json"
    invalid_json.write_text("{", encoding="utf-8")

    invalid_report = service.run_scenario(invalid_json)
    missing_report = service.run_scenario(tmp_path / "missing.json")
    missing_model = service.run_scenario(
        _scenario("missing.fcstm", [{"events": [], "commands": [], "expected": {}}]),
        base_dir=tmp_path,
    )

    assert invalid_report.case_id == "broken"
    assert invalid_report.failure["type"] == "ValueError"
    assert "invalid scenario JSON" in invalid_report.failure["message"]
    assert missing_report.case_id == "missing"
    assert "cannot read scenario JSON" in missing_report.failure["message"]
    assert missing_model.case_id == "user_case"
    assert "cannot read scenario model" in missing_model.failure["message"]


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"schema": "wrong", "version": 1, "cases": {}},
        {"schema": "fcstm-gui.dynamic-validation-provenance", "version": 2, "cases": {}},
        {"schema": "fcstm-gui.dynamic-validation-provenance", "version": 1, "cases": []},
        {
            "schema": "fcstm-gui.dynamic-validation-provenance",
            "version": 1,
            "cases": {"case": []},
        },
        {
            "schema": "fcstm-gui.dynamic-validation-provenance",
            "version": 1,
            "cases": {"case": {}},
        },
    ],
)
def test_provenance_schema_rejects_invalid_payloads(payload):
    with pytest.raises(ValueError):
        _validate_provenance_payload(payload)


def test_invalid_provenance_json_and_hash_mismatch_are_visible(tmp_path):
    service = DynamicValidationService()
    for source in service.resource_dir.iterdir():
        if source.is_file():
            (tmp_path / source.name).write_bytes(source.read_bytes())

    (tmp_path / "provenance.json").write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid provenance JSON"):
        DynamicValidationService(tmp_path).verify_packaged_provenance()

    (tmp_path / "provenance.json").write_bytes(
        (service.resource_dir / "provenance.json").read_bytes()
    )
    target = tmp_path / "design_validation_failure_multilevel_transition.fcstm"
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    report = DynamicValidationService(tmp_path).verify_packaged_provenance()

    assert report.status == "mismatch"
    assert not next(item for item in report.resources if item["path"] == target.name)["ok"]
    assert json.loads(json.dumps(report.to_json_dict()))["schema"].endswith(".provenance")


def test_expected_exception_diffs_cover_missing_message_and_cause_fields():
    expected = {
        "state": "Root.B",
        "variables": {"x": 2},
        "ended": True,
        "rollback": True,
        "exception": {
            "type": "WantedError",
            "message_contains": "wanted message",
            "cause_type": "WantedCause",
            "cause_contains": "wanted cause",
        },
    }
    actual = {
        "state": "Root.A",
        "variables": {"x": 1},
        "ended": False,
        "rollback": False,
        "exception": {
            "type": "ActualError",
            "message": "actual message",
            "cause_type": "ActualCause",
            "cause_message": "actual cause",
        },
    }

    paths = [item["path"] for item in _diff_expected(expected, actual)]
    assert paths == [
        "state",
        "variables.x",
        "ended",
        "rollback",
        "exception.type",
        "exception.message",
        "exception.cause_type",
        "exception.cause_message",
    ]
    assert _diff_expected({"exception": {"cause_contains": None}}, actual)[0]["path"] == (
        "exception.cause_message"
    )
    assert _diff_expected({"exception": {"type": "WantedError"}}, {}) == [
        {"path": "exception", "expected": {"type": "WantedError"}, "actual": None}
    ]


def test_suite_status_priority_and_report_serialization(monkeypatch):
    service = DynamicValidationService()
    monkeypatch.setattr(
        service,
        "_load_provenance",
        lambda: {"cases": {"passed": {}, "mismatch": {}, "cancelled": {}, "failed": {}}},
    )

    def fake_run(case_id, cancel_token=None):
        return DynamicValidationCaseReport(case_id=case_id, status=case_id, steps=())

    monkeypatch.setattr(service, "run_packaged_case", fake_run)
    report = service.run_packaged_cases()

    assert report.status == "failed"
    assert json.loads(json.dumps(report.to_json_dict()))["schema"].endswith(".suite")

    only_mismatch = DynamicValidationSuiteReport(
        status="mismatch",
        cases=(DynamicValidationCaseReport("case", "mismatch", ()),),
    )
    assert only_mismatch.to_json_dict()["cases"][0]["status"] == "mismatch"
    provenance = DynamicValidationProvenanceReport("passed", ({"ok": True},))
    assert provenance.to_json_dict()["resources"] == [{"ok": True}]


def test_exception_chain_and_cancel_token_compatibility():
    try:
        try:
            raise KeyError("root")
        except KeyError as cause:
            raise ValueError("outer") from cause
    except ValueError as error:
        structured = _exception_dict(error)

    assert structured["cause_type"] == "KeyError"
    assert _is_cancelled(None) is False
    assert _is_cancelled(type("Token", (), {"cancelled": lambda self: True})()) is True
    assert _is_cancelled(type("Token", (), {"cancelled": True})()) is True
