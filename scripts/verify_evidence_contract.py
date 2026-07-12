from __future__ import unicode_literals

import argparse
import hashlib
import json
from pathlib import Path

ACCEPTANCE_NAMES = (
    "document.open",
    "document.recent-reopen",
    "document.cancel-load",
    "document.failed-load-preserves-session",
    "dirty.save",
    "dirty.discard",
    "dirty.cancel",
    "source.edit",
    "source.undo",
    "source.redo",
    "source.save",
    "source.fresh-reload",
    "imported.readonly",
    "imported.open-source",
    "rename.simple",
    "rename.composite",
    "rename.unicode-crlf",
    "diagnostics.syntax",
    "diagnostics.assembly",
    "diagnostics.inspect",
    "diagnostics.locate",
    "diagnostics.filter-search",
    "diagnostics.conflict-warning",
    "diagnostics.suggested-fix",
    "keyboard.workspace",
    "graph.refresh",
    "graph.fit",
    "graph.zoom",
    "graph.selection",
    "graph.reset",
    "simulation.initialize",
    "simulation.step",
    "simulation.run",
    "simulation.pause",
    "simulation.continue",
    "simulation.reset",
    "simulation.stop",
    "model.state.add",
    "model.state.edit",
    "model.state.delete",
    "model.variable.add",
    "model.variable.edit",
    "model.variable.delete",
    "model.event.add",
    "model.event.edit",
    "model.event.delete",
    "model.transition.add",
    "model.transition.edit",
    "model.transition.delete",
    "model.guard.add",
    "model.guard.edit",
    "model.guard.delete",
    "model.effect.add",
    "model.effect.edit",
    "model.effect.delete",
    "model.lifecycle.add",
    "model.lifecycle.edit",
    "model.lifecycle.delete",
    "dynamic.case.design_evented_pseudo_chain_invalid_then_valid",
    "dynamic.case.design_validation_failure_multilevel_transition",
    "dynamic.case.expression_failure_transition_guard_raises_expression_error",
    "dynamic.case.pseudo_self_loop_step_limit_raises_dfs_error",
    "dynamic.mutation",
    "dynamic.recover",
    "dynamic.user",
    "dynamic.export",
    "terminology.dynamic-not-formal",
    "formula.guard.valid",
    "formula.guard.invalid",
    "formula.effect.valid",
    "formula.effect.invalid",
    "formula.lifecycle.valid",
    "formula.lifecycle.invalid",
    "formula.numeric.valid",
    "formula.numeric.invalid",
    "formula.stale",
    "generation.python",
    "generation.c",
    "generation.c-poll",
    "generation.cpp",
    "generation.cpp-poll",
    "generation.custom",
    "generation.overwrite",
    "export.dsl",
    "export.word",
    "export.excel",
    "export.plantuml",
    "export.png",
    "export.svg",
    "export.pdf",
    "export.inspect-json",
    "export.dynamic-json",
    "graph.export.plantuml",
    "graph.export.png",
    "graph.export.svg",
    "graph.export.pdf",
    "tasks.copy",
    "tasks.filter",
    "tasks.export",
    "tasks.clear-filtered",
    "tasks.clear-completed",
    "tasks.clear-all",
    "tasks.retry",
    "tasks.cancel",
    "tasks.artifact",
    "tasks.redaction",
    "tasks.registry.load",
    "tasks.registry.inspect",
    "tasks.registry.graph",
    "tasks.registry.simulation",
    "tasks.registry.dynamic",
    "tasks.registry.generation",
    "tasks.registry.export",
    "tasks.transient.document-validation",
    "tasks.transient.formula-validation",
    "cancel.load",
    "cancel.simulation",
    "cancel.dynamic",
    "cancel.graph",
    "cancel.generation",
    "cancel.export",
    "stale.graph",
    "stale.simulation",
    "stale.dynamic",
    "stale.generation",
    "stale.export",
    "keyboard.model",
    "keyboard.inspect",
    "keyboard.generation",
    "keyboard.templates",
    "keyboard.graph",
    "keyboard.simulation",
    "keyboard.syntax",
    "keyboard.formula.guard",
    "keyboard.formula.effect",
    "keyboard.formula.lifecycle",
    "keyboard.formula.numeric",
    "graph.drag",
    "export.overwrite-preserves-target",
    "geometry.active-workspaces",
)

SELF_CHECK_TOTAL = 182
SELF_CHECK_MODULE_CLOSURE = 114
SELF_CHECK_BEHAVIOR = 68
SELF_CHECK_NAMES_SHA256 = "a7d5135e3061e16ce66d9a1c869999d6cd2b1e7703463f8b4f3b82c13a5aae4c"

REQUIRED_SELF_CHECK_NAMES = (
    "Z3 integer SAT and model",
    "Z3 UNSAT",
    "Z3 exact real",
    "Z3 bit-vector",
    "Z3 Optimize maximize",
    "simulation multiple cycles state variables",
    "dynamic mutation mismatch",
    "dynamic restored resource rerun",
    "dynamic provenance resource hashes",
)


class ContractError(ValueError):
    pass


def _load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as error:
        raise ContractError("invalid JSON {}: {}".format(path, error))


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _require(condition, message):
    if not condition:
        raise ContractError(message)


def _verify_file_record(record, root, label):
    for key in ("path", "size", "sha256"):
        _require(key in record, label + " missing " + key)
    path = Path(root) / record["path"]
    _require(path.is_file(), label + " file does not exist: " + str(path))
    _require(path.stat().st_size == record["size"], label + " size mismatch")
    _require(_sha256(path) == record["sha256"], label + " sha256 mismatch")


def _verify_counts(report):
    counts = report.get("counts") or {}
    results = report.get("results") or []
    failed = [item for item in results if item.get("status") == "failed"]
    _require(counts.get("total") == len(results), "report counts.total mismatch")
    _require(counts.get("failed") == len(failed), "report counts.failed mismatch")
    _require(
        counts.get("passed") == len(results) - len(failed),
        "report counts.passed mismatch",
    )


def verify_self_check_report(report):
    _require(report.get("schema") == "fcstm-gui.self-check-report", "bad self-check schema")
    _require(report.get("version") == 1, "bad self-check version")
    _require(report.get("status") == "passed", "self-check report did not pass")
    _verify_counts(report)
    names = [item.get("name") for item in report.get("results", [])]
    _require(len(names) == SELF_CHECK_TOTAL, "self-check item count mismatch")
    _require(len(names) == len(set(names)), "self-check names are not unique")
    names_digest = hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest()
    _require(
        names_digest == SELF_CHECK_NAMES_SHA256,
        "self-check item set/order digest mismatch",
    )
    _require(
        all(item.get("status") == "passed" for item in report.get("results", [])),
        "self-check contains a non-passed item",
    )
    missing = [name for name in REQUIRED_SELF_CHECK_NAMES if name not in names]
    _require(not missing, "self-check missing required items: " + ", ".join(missing))
    kind_counts = report.get("counts") or {}
    module_count = sum(item.get("kind") == "module-closure" for item in report.get("results", []))
    behavior_count = sum(item.get("kind") == "behavior" for item in report.get("results", []))
    _require(module_count == SELF_CHECK_MODULE_CLOSURE, "module closure total mismatch")
    _require(behavior_count == SELF_CHECK_BEHAVIOR, "behavior total mismatch")
    _require(kind_counts.get("module_closure") == module_count, "module_closure count mismatch")
    _require(kind_counts.get("behavior") == behavior_count, "behavior count mismatch")


def verify_acceptance_report(report, artifact_root):
    _require(report.get("schema") == "fcstm-gui.acceptance-check-report", "bad acceptance schema")
    _require(report.get("version") == 1, "bad acceptance version")
    _require(report.get("status") == "passed", "acceptance report did not pass")
    _verify_counts(report)
    names = [item.get("name") for item in report.get("results", [])]
    _require(tuple(names) == ACCEPTANCE_NAMES, "acceptance item set/order mismatch")
    _require(
        all(item.get("status") == "passed" for item in report.get("results", [])),
        "acceptance contains a non-passed item",
    )
    for index, result in enumerate(report.get("results", [])):
        artifacts = result.get("artifacts")
        _require(isinstance(artifacts, list) and artifacts, "acceptance result has no artifacts")
        for artifact_index, artifact in enumerate(artifacts):
            _verify_file_record(
                artifact,
                artifact_root,
                "results[{}].artifacts[{}]".format(index, artifact_index),
            )
    for index, artifact in enumerate(report.get("artifacts", [])):
        _verify_file_record(artifact, artifact_root, "artifacts[{}]".format(index))


def _artifact_base_for_report(flat_report_path, artifact_root):
    path = str(flat_report_path)
    if "__" in path:
        original = Path(path.replace("__", "/"))
        if original.name == "report.json":
            return Path(artifact_root) / original.parent / "artifacts"
    return Path(artifact_root)


def verify_evidence(evidence_path, reports_dir, artifact_root):
    evidence = _load_json(evidence_path)
    _require(evidence.get("schema") == "fcstm-gui.acceptance-evidence", "bad evidence schema")
    reports = evidence.get("reports")
    _require(isinstance(reports, list) and reports, "evidence has no reports")
    counts = evidence.get("counts") or {}
    for section in ("reports", "artifacts", "screenshots", "product_manifests"):
        items = evidence.get(section)
        _require(isinstance(items, list), "evidence.{} is not a list".format(section))
        _require(
            counts.get(section) == len(items),
            "evidence counts.{} mismatch".format(section),
        )
    for index, record in enumerate(reports):
        _verify_file_record(record, reports_dir, "evidence.reports[{}]".format(index))
        report = _load_json(Path(reports_dir) / record["path"])
        if record.get("schema") == "fcstm-gui.self-check-report":
            verify_self_check_report(report)
        elif record.get("schema") == "fcstm-gui.acceptance-check-report":
            verify_acceptance_report(
                report, _artifact_base_for_report(record["path"], artifact_root)
            )
        else:
            raise ContractError("unknown report schema: " + str(record.get("schema")))
    for section in ("artifacts", "product_manifests"):
        for index, record in enumerate(evidence[section]):
            _verify_file_record(
                record,
                artifact_root,
                "evidence.{}[{}]".format(section, index),
            )
    screenshot_root = Path(reports_dir).parent / "screenshots"
    for index, record in enumerate(evidence["screenshots"]):
        _verify_file_record(
            record,
            screenshot_root,
            "evidence.screenshots[{}]".format(index),
        )
    _require(evidence["artifacts"], "evidence has no artifacts")
    _require(evidence["screenshots"], "evidence has no screenshots")
    _require(
        len(evidence["product_manifests"]) == 1,
        "evidence must contain exactly one product manifest",
    )
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify fcstm-gui evidence report contracts")
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--reports", required=True)
    parser.add_argument("--artifact-root", required=True)
    args = parser.parse_args(argv)
    try:
        verify_evidence(args.evidence, args.reports, args.artifact_root)
    except ContractError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
