"""Dynamic validation scenario runner for packaged and user FCSTM cases."""

from __future__ import unicode_literals

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from app.application.simulation import SimulationService

SCENARIO_SCHEMA = "fcstm-gui.dynamic-validation-scenario"
PROVENANCE_SCHEMA = "fcstm-gui.dynamic-validation-provenance"
SCENARIO_VERSION = 1
PROVENANCE_VERSION = 1
REPORT_SCHEMA = "fcstm-gui.dynamic-validation-report"
REPORT_VERSION = 1


def _default_resource_dir():
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        return (
            Path(sys._MEIPASS)
            / "app"
            / "resources"
            / "self_check"
            / "dynamic_validation"
        )
    return (
        Path(__file__).resolve().parents[1]
        / "resources"
        / "self_check"
        / "dynamic_validation"
    )


DEFAULT_RESOURCE_DIR = _default_resource_dir()


@dataclass(frozen=True)
class DynamicValidationScenarioStep:
    events: Tuple[str, ...]
    commands: Tuple[str, ...]
    expected: Dict[str, Any]


@dataclass(frozen=True)
class DynamicValidationScenario:
    case_id: str
    model_file: str
    model_path: str
    model_text: str
    initial_state: Optional[Tuple[str, ...]]
    initial_variables: Dict[str, Any]
    steps: Tuple[DynamicValidationScenarioStep, ...]
    scenario_sha256: str
    model_sha256: str
    upstream_case_id: Optional[str] = None
    upstream_commit: Optional[str] = None


@dataclass(frozen=True)
class DynamicValidationStepReport:
    index: int
    status: str
    commands: Tuple[str, ...]
    input_events: Tuple[str, ...]
    consumed_events: Tuple[str, ...]
    unconsumed_events: Tuple[str, ...]
    expected: Dict[str, Any]
    actual: Dict[str, Any]
    diffs: List[Dict[str, Any]]

    def to_json_dict(self):
        return {
            "schema": REPORT_SCHEMA + ".step",
            "version": REPORT_VERSION,
            "index": self.index,
            "status": self.status,
            "commands": list(self.commands),
            "input_events": list(self.input_events),
            "consumed_events": list(self.consumed_events),
            "unconsumed_events": list(self.unconsumed_events),
            "expected": self.expected,
            "actual": self.actual,
            "diffs": self.diffs,
        }


@dataclass(frozen=True)
class DynamicValidationCaseReport:
    case_id: str
    status: str
    steps: Tuple[DynamicValidationStepReport, ...]
    upstream_case_id: Optional[str] = None
    upstream_commit: Optional[str] = None
    failure: Optional[Dict[str, Any]] = None
    source_revision: Optional[int] = None
    dependency_fingerprint: Optional[str] = None
    scenario_sha256: Optional[str] = None

    def to_json_dict(self):
        data = {
            "schema": REPORT_SCHEMA + ".case",
            "version": REPORT_VERSION,
            "case_id": self.case_id,
            "status": self.status,
            "steps": [step.to_json_dict() for step in self.steps],
            "upstream_case_id": self.upstream_case_id,
            "upstream_commit": self.upstream_commit,
            "failure": self.failure,
            "source_revision": self.source_revision,
            "dependency_fingerprint": self.dependency_fingerprint,
            "scenario_sha256": self.scenario_sha256,
        }
        return data


@dataclass(frozen=True)
class DynamicValidationSuiteReport:
    status: str
    cases: Tuple[DynamicValidationCaseReport, ...]

    def to_json_dict(self):
        return {
            "schema": REPORT_SCHEMA + ".suite",
            "version": REPORT_VERSION,
            "status": self.status,
            "cases": [case.to_json_dict() for case in self.cases],
        }


@dataclass(frozen=True)
class DynamicValidationProvenanceReport:
    status: str
    resources: Tuple[Dict[str, Any], ...]

    def to_json_dict(self):
        return {
            "schema": REPORT_SCHEMA + ".provenance",
            "version": REPORT_VERSION,
            "status": self.status,
            "resources": list(self.resources),
        }


class DynamicValidationService(object):
    """Load strict JSON scenarios and run them through fresh simulation runtimes."""

    def __init__(self, resource_dir=None):
        self.resource_dir = (
            Path(resource_dir) if resource_dir is not None else DEFAULT_RESOURCE_DIR
        )

    def load_scenario(self, payload_or_path, base_dir=None):
        payload, payload_path = self._read_payload(payload_or_path)
        base = Path(base_dir) if base_dir is not None else (
            payload_path.parent if payload_path is not None else self.resource_dir
        )
        _validate_scenario_payload(payload)
        model_file = payload["model_file"]
        model_path = (base / model_file).resolve()
        try:
            model_text = model_path.read_text(encoding="utf-8")
        except OSError as error:
            raise ValueError(
                "cannot read scenario model file {0}: {1}".format(model_file, error)
            )
        initial = payload["initial"]
        initial_state = _state_tuple(initial["state"])
        steps = []
        for raw_step in payload["steps"]:
            steps.append(
                DynamicValidationScenarioStep(
                    events=tuple(raw_step["events"]),
                    commands=tuple(raw_step["commands"]),
                    expected=dict(raw_step["expected"]),
                )
            )
        return DynamicValidationScenario(
            case_id=payload["case_id"],
            upstream_case_id=payload.get("upstream_case_id"),
            upstream_commit=payload.get("upstream_commit"),
            model_file=model_file,
            model_path=str(model_path),
            model_text=model_text,
            initial_state=initial_state,
            initial_variables=dict(initial["variables"]),
            steps=tuple(steps),
            scenario_sha256=_json_sha256(payload),
            model_sha256=_text_sha256(model_text),
        )

    def run_packaged_case(self, case_id, cancel_token=None):
        return self.run_scenario(
            self.resource_dir / (case_id + ".json"), cancel_token=cancel_token
        )

    def run_packaged_cases(self, cancel_token=None):
        case_ids = sorted(self._load_provenance()["cases"])
        reports = []
        status = "passed"
        for case_id in case_ids:
            report = self.run_packaged_case(case_id, cancel_token=cancel_token)
            reports.append(report)
            if report.status == "failed":
                status = "failed"
            elif report.status == "cancelled" and status not in ("failed",):
                status = "cancelled"
            elif report.status == "mismatch" and status == "passed":
                status = "mismatch"
        return DynamicValidationSuiteReport(status=status, cases=tuple(reports))

    def run_scenario(self, payload_or_path, base_dir=None, cancel_token=None):
        try:
            scenario = self.load_scenario(payload_or_path, base_dir=base_dir)
            service = SimulationService()
            session = service.start(
                scenario.model_text,
                source_uri="dynamic-validation://" + scenario.case_id,
                source_revision=1,
                dependency_fingerprint=_text_sha256(scenario.model_text),
                initial_state=scenario.initial_state,
                initial_vars=scenario.initial_variables,
                source_path=scenario.model_path,
            )
        except Exception as error:  # noqa: BLE001 - structured validation failure
            case_id = _payload_case_id(payload_or_path)
            return DynamicValidationCaseReport(
                case_id=case_id,
                status="failed",
                steps=(),
                failure=_exception_dict(error),
            )

        step_reports = []
        overall = "passed"
        for index, step in enumerate(scenario.steps):
            if _is_cancelled(cancel_token):
                overall = "cancelled"
                break
            try:
                for command in step.commands:
                    if command == "reset":
                        service.reset(session)
                    else:  # validated before, kept defensive for direct construction
                        raise ValueError("unsupported dynamic validation command: " + command)
                cycle = service.cycle(session, events=step.events)
                actual = _actual_from_cycle(cycle)
                diffs = _diff_expected(step.expected, actual)
                if cycle.error is not None and "exception" not in step.expected:
                    status = "failed"
                    if overall != "failed":
                        overall = "failed"
                elif not diffs and "exception" in step.expected:
                    status = "expected_exception_passed"
                else:
                    status = "passed" if not diffs else "mismatch"
                if status == "mismatch" and overall == "passed":
                    overall = "mismatch"
                elif status == "failed":
                    overall = "failed"
                step_reports.append(
                    DynamicValidationStepReport(
                        index=index,
                        status=status,
                        commands=step.commands,
                        input_events=cycle.input_events,
                        consumed_events=cycle.consumed_events,
                        unconsumed_events=cycle.unconsumed_events,
                        expected=step.expected,
                        actual=actual,
                        diffs=diffs,
                    )
                )
                if status == "failed":
                    break
            except Exception as error:  # noqa: BLE001 - report as failed step
                overall = "failed"
                step_reports.append(
                    DynamicValidationStepReport(
                        index=index,
                        status="failed",
                        commands=step.commands,
                        input_events=step.events,
                        consumed_events=(),
                        unconsumed_events=(),
                        expected=step.expected,
                        actual={"exception": _exception_dict(error)},
                        diffs=[
                            {
                                "path": "exception",
                                "expected": step.expected.get("exception"),
                                "actual": _exception_dict(error),
                            }
                        ],
                    )
                )
                break
        return DynamicValidationCaseReport(
            case_id=scenario.case_id,
            upstream_case_id=scenario.upstream_case_id,
            upstream_commit=scenario.upstream_commit,
            status=overall,
            steps=tuple(step_reports),
            source_revision=1,
            dependency_fingerprint=scenario.model_sha256,
            scenario_sha256=scenario.scenario_sha256,
        )

    def verify_packaged_provenance(self):
        provenance = self._load_provenance()
        resources = []
        status = "passed"
        for case_id in sorted(provenance["cases"]):
            entry = provenance["cases"][case_id]
            for suffix, key in (
                (".fcstm", "packaged_fcstm_sha256"),
                (".json", "packaged_scenario_sha256"),
            ):
                path = self.resource_dir / (case_id + suffix)
                actual = _file_sha256(path)
                expected = entry[key]
                upstream_fcstm = entry.get("upstream_fcstm_sha256")
                ok = actual == expected
                item = {
                    "case_id": case_id,
                    "path": path.name,
                    "sha256": actual,
                    "expected_sha256": expected,
                    "ok": ok,
                }
                if suffix == ".fcstm":
                    item["upstream_fcstm_sha256"] = upstream_fcstm
                    item["upstream_matches_packaged"] = upstream_fcstm == expected
                    ok = ok and item["upstream_matches_packaged"]
                    item["ok"] = ok
                if not ok:
                    status = "mismatch"
                resources.append(item)
        return DynamicValidationProvenanceReport(status=status, resources=tuple(resources))

    def _read_payload(self, payload_or_path):
        if isinstance(payload_or_path, Mapping):
            return dict(payload_or_path), None
        if not isinstance(payload_or_path, (str, bytes, Path)):
            raise ValueError("scenario must be a JSON object or file path")
        path = Path(payload_or_path)
        try:
            with path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except ValueError as error:
            raise ValueError("invalid scenario JSON: {0}".format(error))
        except OSError as error:
            raise ValueError("cannot read scenario JSON: {0}".format(error))
        return payload, path

    def _load_provenance(self):
        path = self.resource_dir / "provenance.json"
        try:
            with path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except ValueError as error:
            raise ValueError("invalid provenance JSON: {0}".format(error))
        _validate_provenance_payload(payload)
        return payload


def _validate_scenario_payload(payload):
    if not isinstance(payload, Mapping):
        raise ValueError("scenario must be a JSON object")
    required = set(["schema", "version", "case_id", "model_file", "initial", "steps"])
    optional = set(["upstream_case_id", "upstream_commit"])
    keys = set(payload)
    missing = sorted(required - keys)
    if missing:
        raise ValueError("scenario missing required fields: " + ", ".join(missing))
    unexpected = sorted(keys - required - optional)
    if unexpected:
        raise ValueError("scenario has unexpected fields: " + ", ".join(unexpected))
    if payload["schema"] != SCENARIO_SCHEMA:
        raise ValueError("unsupported scenario schema: " + repr(payload["schema"]))
    if payload["version"] != SCENARIO_VERSION:
        raise ValueError("unsupported scenario version: " + repr(payload["version"]))
    if not isinstance(payload["case_id"], str) or not payload["case_id"]:
        raise ValueError("case_id must be a non-empty string")
    model_file = payload["model_file"]
    if (
        not isinstance(model_file, str)
        or "/" in model_file
        or "\\" in model_file
        or not model_file.endswith(".fcstm")
    ):
        raise ValueError("model_file must name a sibling .fcstm file")
    initial = payload["initial"]
    if not isinstance(initial, Mapping) or set(initial) != set(["state", "variables"]):
        raise ValueError("initial must contain exactly state and variables")
    if initial["state"] is not None and not isinstance(initial["state"], str):
        raise ValueError("initial.state must be string or null")
    if not isinstance(initial["variables"], Mapping):
        raise ValueError("initial.variables must be an object")
    steps = payload["steps"]
    if not isinstance(steps, list) or not steps:
        raise ValueError("steps must be a non-empty array")
    for index, step in enumerate(steps):
        if not isinstance(step, Mapping) or set(step) != set(
            ["events", "commands", "expected"]
        ):
            raise ValueError(
                "step {0} must contain exactly events, commands, expected".format(
                    index
                )
            )
        if not isinstance(step["events"], list) or not all(
            isinstance(item, str) for item in step["events"]
        ):
            raise ValueError("step {0}.events must be an array of strings".format(index))
        if not isinstance(step["commands"], list) or not all(
            item == "reset" for item in step["commands"]
        ):
            raise ValueError("step {0}.commands only supports reset".format(index))
        _validate_expected_payload(step["expected"], index)


def _validate_provenance_payload(payload):
    if not isinstance(payload, Mapping):
        raise ValueError("provenance must be a JSON object")
    if payload.get("schema") != PROVENANCE_SCHEMA:
        raise ValueError("unsupported provenance schema")
    if payload.get("version") != PROVENANCE_VERSION:
        raise ValueError("unsupported provenance version")
    cases = payload.get("cases")
    if not isinstance(cases, Mapping):
        raise ValueError("provenance cases must be an object")
    for case_id, entry in cases.items():
        if not isinstance(entry, Mapping):
            raise ValueError("provenance case {0} must be an object".format(case_id))
        for key in (
            "upstream_yaml_sha256",
            "upstream_fcstm_sha256",
            "packaged_fcstm_sha256",
            "packaged_scenario_sha256",
        ):
            value = entry.get(key)
            if not isinstance(value, str) or len(value) != 64:
                raise ValueError(
                    "provenance case {0} has invalid {1}".format(case_id, key)
                )


def _validate_expected_payload(expected, index):
    if not isinstance(expected, Mapping):
        raise ValueError("step {0}.expected must be an object".format(index))
    allowed = set(["state", "variables", "ended", "exception", "rollback"])
    unexpected = sorted(set(expected) - allowed)
    if unexpected:
        raise ValueError(
            "step {0}.expected has unexpected fields: {1}".format(
                index, ", ".join(unexpected)
            )
        )
    if (
        "state" in expected
        and expected["state"] is not None
        and not isinstance(expected["state"], str)
    ):
        raise ValueError("step {0}.expected.state must be string or null".format(index))
    if "variables" in expected and not isinstance(expected["variables"], Mapping):
        raise ValueError("step {0}.expected.variables must be an object".format(index))
    if "ended" in expected and not isinstance(expected["ended"], bool):
        raise ValueError("step {0}.expected.ended must be boolean".format(index))
    if "rollback" in expected and not isinstance(expected["rollback"], bool):
        raise ValueError("step {0}.expected.rollback must be boolean".format(index))
    if "exception" in expected:
        _validate_expected_exception(expected["exception"], index)


def _validate_expected_exception(expected, index):
    if not isinstance(expected, Mapping):
        raise ValueError("step {0}.expected.exception must be an object".format(index))
    allowed = set(["type", "message_contains", "cause_type", "cause_contains"])
    unexpected = sorted(set(expected) - allowed)
    if unexpected:
        raise ValueError(
            "step {0}.expected.exception has unexpected fields: {1}".format(
                index, ", ".join(unexpected)
            )
        )
    for key in ("type", "message_contains"):
        if key in expected and not isinstance(expected[key], str):
            raise ValueError(
                "step {0}.expected.exception.{1} must be string".format(index, key)
            )
    for key in ("cause_type", "cause_contains"):
        if (
            key in expected
            and expected[key] is not None
            and not isinstance(expected[key], str)
        ):
            raise ValueError(
                "step {0}.expected.exception.{1} must be string or null".format(
                    index, key
                )
            )


def _actual_from_cycle(cycle):
    actual = {
        "state": _state_string(cycle.snapshot.state_path),
        "variables": dict(cycle.snapshot.vars),
        "ended": cycle.snapshot.ended,
        "cycle": cycle.snapshot.cycle,
    }
    if cycle.error is not None:
        actual["exception"] = {
            "type": cycle.error.type,
            "message": cycle.error.message,
            "cause_type": cycle.error.cause_type,
            "cause_message": cycle.error.cause_message,
        }
        actual["rollback"] = cycle.rollback_preserved
    return actual


def _diff_expected(expected, actual):
    diffs = []
    if "state" in expected:
        _append_diff(diffs, "state", expected["state"], actual.get("state"))
    if "variables" in expected:
        actual_variables = actual.get("variables") or {}
        for key, value in expected["variables"].items():
            _append_diff(
                diffs,
                "variables." + str(key),
                value,
                actual_variables.get(key),
            )
    if "ended" in expected:
        _append_diff(diffs, "ended", expected["ended"], actual.get("ended"))
    if "rollback" in expected:
        _append_diff(diffs, "rollback", expected["rollback"], actual.get("rollback"))
    if "exception" in expected:
        _diff_exception(diffs, expected["exception"], actual.get("exception"))
    elif actual.get("exception") is not None:
        diffs.append(
            {"path": "exception", "expected": None, "actual": actual.get("exception")}
        )
    return diffs


def _diff_exception(diffs, expected, actual):
    if actual is None:
        diffs.append({"path": "exception", "expected": expected, "actual": None})
        return
    if "type" in expected:
        _append_diff(diffs, "exception.type", expected["type"], actual.get("type"))
    if "message_contains" in expected:
        needle = expected["message_contains"]
        message = actual.get("message") or ""
        if needle not in message:
            diffs.append(
                {
                    "path": "exception.message",
                    "expected_contains": needle,
                    "actual": message,
                }
            )
    if "cause_type" in expected:
        _append_diff(
            diffs,
            "exception.cause_type",
            expected["cause_type"],
            actual.get("cause_type"),
        )
    if "cause_contains" in expected:
        needle = expected["cause_contains"]
        message = actual.get("cause_message")
        if needle is None:
            if message is not None:
                diffs.append(
                    {
                        "path": "exception.cause_message",
                        "expected": None,
                        "actual": message,
                    }
                )
        elif needle not in (message or ""):
            diffs.append(
                {
                    "path": "exception.cause_message",
                    "expected_contains": needle,
                    "actual": message,
                }
            )


def _append_diff(diffs, path, expected, actual):
    if expected != actual:
        diffs.append({"path": path, "expected": expected, "actual": actual})


def _state_tuple(value):
    if value is None:
        return None
    return tuple(part for part in value.split(".") if part)


def _state_string(path):
    return ".".join(path) if path else None


def _file_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json_sha256(payload):
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _exception_dict(error):
    cause = error.__cause__ or error.__context__
    return {
        "type": type(error).__name__,
        "message": str(error),
        "cause_type": type(cause).__name__ if cause is not None else None,
        "cause_message": str(cause) if cause is not None else None,
    }


def _payload_case_id(payload_or_path):
    if isinstance(payload_or_path, Mapping):
        value = payload_or_path.get("case_id")
        return value if isinstance(value, str) and value else "<invalid>"
    return Path(payload_or_path).stem


def _is_cancelled(cancel_token):
    if cancel_token is None:
        return False
    checker = getattr(cancel_token, "is_cancelled", None)
    if callable(checker):
        return bool(checker())
    checker = getattr(cancel_token, "cancelled", None)
    if callable(checker):
        return bool(checker())
    return bool(checker)
