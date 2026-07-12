from __future__ import unicode_literals

import json

from app import self_check


def test_self_check_writes_versioned_report(monkeypatch, tmp_path):
    monkeypatch.setattr(
        self_check,
        "_checks",
        lambda: [
            ("import example", lambda: "imported"),
            ("Z3 integer SAT and model", lambda: "solved"),
        ],
    )
    target = tmp_path / "self-check.json"

    assert self_check.run_self_check(str(target)) == 0

    report = json.loads(target.read_text(encoding="utf-8"))
    assert report["schema"] == "fcstm-gui.self-check-report"
    assert report["version"] == 1
    assert report["status"] == "passed"
    assert report["counts"] == {
        "total": 2,
        "passed": 2,
        "failed": 0,
        "module_closure": 1,
        "behavior": 1,
    }


def test_self_check_registry_has_independent_z3_and_acceptance_items():
    names = [name for name, _ in self_check._checks()]
    assert len(names) == len(set(names))
    assert [name for name in names if name.startswith("Z3 ")] == [
        "Z3 integer SAT and model",
        "Z3 UNSAT",
        "Z3 exact real",
        "Z3 bit-vector",
        "Z3 Optimize maximize",
    ]
    for required in (
        "loader text success",
        "loader file success",
        "loader syntax failure position",
        "loader model assembly failure",
        "inspect warning/code/span",
        "simulation initialization",
        "simulation multiple cycles state variables",
        "simulation terminal state",
        "simulation exception cause rollback",
        "dynamic mutation mismatch",
        "dynamic restored resource rerun",
        "packaged template inventory",
    ):
        assert required in names


def test_report_schemas_are_versioned_resources():
    resource_dir = self_check.os.path.join(
        self_check.os.path.dirname(self_check.__file__), "resources", "self_check"
    )
    for name, report_name in (
        ("self_check_report.schema.json", "fcstm-gui.self-check-report"),
        ("acceptance_check_report.schema.json", "fcstm-gui.acceptance-check-report"),
    ):
        with open(self_check.os.path.join(resource_dir, name), encoding="utf-8") as stream:
            schema = json.load(stream)
        assert schema["properties"]["schema"]["const"] == report_name
        assert schema["properties"]["version"]["const"] == 1
