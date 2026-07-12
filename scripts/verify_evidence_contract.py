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

PREAPPROVED_COCOA_OVERLAPS = frozenset(
    {
        ("simulation_cycle_button", "simulation_initialize_button"),
        ("simulation_cycle_button", "simulation_run_button"),
        ("simulation_pause_button", "simulation_run_button"),
        ("simulation_pause_button", "simulation_reset_button"),
        ("simulation_cancel_button", "simulation_reset_button"),
    }
)

OVERLAP_FUNCTIONAL_VERDICTS = (
    "text_visible",
    "hit_test_passed",
    "click_passed",
    "focus_passed",
    "accessible_name_passed",
    "business_fact_passed",
    "artifact_fact_passed",
)

VISUAL_REVIEW_SAMPLE_COUNT = 54
VISUAL_REVIEW_LAYOUTS = ("onedir", "onefile")
VISUAL_REVIEW_PLATFORMS = {
    "Linux": ("xcb", "linux-x86_64"),
    "Windows": ("windows", "windows-x86_64"),
    "Darwin": ("cocoa", "macos-x86_64"),
}
VISUAL_REVIEW_FIELDS = frozenset(
    {
        "schema",
        "version",
        "reviewer",
        "reviewed_at",
        "commit",
        "run_id",
        "samples_expected",
        "samples_reviewed",
        "status",
        "items",
        "blocking_findings",
        "non_blocking_findings",
    }
)
VISUAL_REVIEW_ITEM_FIELDS = frozenset(
    {
        "join_key",
        "platform",
        "qt_platform",
        "layout",
        "artifact",
        "product",
        "product_sha256",
        "acceptance_report_path",
        "acceptance_report_sha256",
        "image_path",
        "image_sha256",
        "viewport",
        "scale",
        "acceptance_item",
        "overlap_exemption_join_keys",
        "text_visible",
        "hit_test_passed",
        "click_passed",
        "focus_passed",
        "accessible_name_passed",
        "business_fact_passed",
        "artifact_fact_passed",
        "status",
        "notes",
    }
)
NON_BLOCKING_FINDING_FIELDS = frozenset(
    {"id", "join_key", "category", "description", "impairs_use", "evidence_path"}
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


def _verify_overlap_exemptions(report, artifact_root):
    geometry = report.get("geometry") or {}
    exemptions = geometry.get("overlap_exemptions") or []
    _require(isinstance(exemptions, list), "overlap exemptions are not a list")
    seen = set()
    platform_record = report.get("platform") or {}
    for index, item in enumerate(exemptions):
        label = "overlap_exemptions[{}]".format(index)
        _require(isinstance(item, dict), label + " is not an object")
        widgets = tuple(sorted(item.get("widgets") or ()))
        _require(
            widgets in PREAPPROVED_COCOA_OVERLAPS,
            label + " is not preapproved",
        )
        _require(item.get("platform") == "Darwin", label + " bad platform")
        _require(item.get("qt_platform") == "cocoa", label + " bad Qt platform")
        _require(
            platform_record.get("system") == item.get("platform"),
            label + " platform/report mismatch",
        )
        _require(
            platform_record.get("qt_platform") == item.get("qt_platform"),
            label + " Qt platform/report mismatch",
        )
        _require(
            item.get("parent") == "ordinary_simulation_panel",
            label + " bad parent",
        )
        _require(
            item.get("acceptance_item") == "geometry.active-workspaces",
            label + " bad acceptance item",
        )
        _require(
            item.get("layout") in {"source", "onedir", "onefile"},
            label + " bad layout",
        )
        _require(item.get("viewport") == report.get("viewport"), label + " viewport mismatch")
        _require(
            item.get("scale") == str(report.get("qt_scale_factor")),
            label + " scale mismatch",
        )
        expected_key = "|".join(
            (
                "Darwin",
                item["layout"],
                item["viewport"],
                item["scale"],
                "geometry.active-workspaces",
                widgets[0],
                widgets[1],
            )
        )
        _require(item.get("join_key") == expected_key, label + " join key mismatch")
        _require(expected_key not in seen, label + " duplicate join key")
        seen.add(expected_key)
        _require(
            all(item.get(key) is True for key in OVERLAP_FUNCTIONAL_VERDICTS),
            label + " functional verdict failed",
        )
        intersection = item.get("intersection")
        _require(
            isinstance(intersection, list)
            and len(intersection) == 4
            and all(isinstance(value, int) for value in intersection)
            and intersection[2] > 0
            and intersection[3] > 0,
            label + " bad intersection",
        )
        screenshot = Path(artifact_root) / str(item.get("screenshot_path") or "")
        _require(screenshot.is_file(), label + " screenshot does not exist")
        _require(
            _sha256(screenshot) == item.get("screenshot_sha256"),
            label + " screenshot sha256 mismatch",
        )


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
    _verify_overlap_exemptions(report, artifact_root)
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


def verify_visual_review_attestation(attestation_path, artifact_root):
    attestation = _load_json(attestation_path)
    root = Path(artifact_root)
    _require(set(attestation) == VISUAL_REVIEW_FIELDS, "visual review fields mismatch")
    _require(
        attestation.get("schema") == "fcstm-gui.visual-review",
        "bad visual review schema",
    )
    _require(attestation.get("version") == 1, "bad visual review version")
    _require(attestation.get("reviewer"), "visual review has no reviewer")
    _require(str(attestation.get("reviewed_at") or "").endswith("Z"), "bad reviewed_at")
    commit = str(attestation.get("commit") or "")
    _require(len(commit) == 40 and all(char in "0123456789abcdef" for char in commit), "bad commit")
    _require(str(attestation.get("run_id") or "").isdigit(), "bad run id")
    _require(
        attestation.get("samples_expected") == VISUAL_REVIEW_SAMPLE_COUNT,
        "visual review expected sample count mismatch",
    )
    _require(
        attestation.get("samples_reviewed") == VISUAL_REVIEW_SAMPLE_COUNT,
        "visual review reviewed sample count mismatch",
    )
    _require(attestation.get("status") == "passed", "visual review did not pass")
    _require(attestation.get("blocking_findings") == [], "blocking visual finding exists")
    non_blocking = attestation.get("non_blocking_findings")
    _require(isinstance(non_blocking, list), "non-blocking findings are not a list")

    items = attestation.get("items")
    _require(
        isinstance(items, list) and len(items) == VISUAL_REVIEW_SAMPLE_COUNT,
        "visual review must contain exactly 54 items",
    )
    seen_items = set()
    seen_exemptions = set()
    expected_exemptions = set()
    combination_counts = {}
    for index, item in enumerate(items):
        label = "visual-review.items[{}]".format(index)
        _require(isinstance(item, dict), label + " is not an object")
        _require(set(item) == VISUAL_REVIEW_ITEM_FIELDS, label + " fields mismatch")
        platform_system = item.get("platform")
        _require(platform_system in VISUAL_REVIEW_PLATFORMS, label + " bad platform")
        expected_qt, platform_label = VISUAL_REVIEW_PLATFORMS[platform_system]
        _require(item.get("qt_platform") == expected_qt, label + " bad Qt platform")
        layout = item.get("layout")
        _require(layout in VISUAL_REVIEW_LAYOUTS, label + " bad layout")
        expected_artifact = "fcstm-gui-{}{}".format(
            platform_label,
            "-onefile" if layout == "onefile" else "",
        )
        _require(item.get("artifact") == expected_artifact, label + " bad artifact")
        image_path = str(item.get("image_path") or "")
        expected_key = "|".join(
            (
                platform_system,
                layout,
                str(item.get("viewport") or ""),
                str(item.get("scale") or ""),
                str(item.get("acceptance_item") or ""),
                image_path,
            )
        )
        _require(item.get("join_key") == expected_key, label + " join key mismatch")
        _require(expected_key not in seen_items, label + " duplicate join key")
        seen_items.add(expected_key)
        combination = (platform_system, layout)
        combination_counts[combination] = combination_counts.get(combination, 0) + 1
        _require(item.get("acceptance_item") == "geometry.active-workspaces", label + " bad acceptance item")
        _require(item.get("status") == "passed", label + " did not pass")
        _require(
            all(item.get(key) is True for key in OVERLAP_FUNCTIONAL_VERDICTS),
            label + " functional verdict failed",
        )

        product_path = root / str(item.get("product") or "")
        _require(product_path.is_file(), label + " product does not exist")
        _require(_sha256(product_path) == item.get("product_sha256"), label + " product sha256 mismatch")
        report_path = root / str(item.get("acceptance_report_path") or "")
        _require(report_path.is_file(), label + " acceptance report does not exist")
        _require(
            _sha256(report_path) == item.get("acceptance_report_sha256"),
            label + " acceptance report sha256 mismatch",
        )
        image = root / image_path
        _require(image.is_file(), label + " image does not exist")
        _require(_sha256(image) == item.get("image_sha256"), label + " image sha256 mismatch")
        _require(image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"), label + " image is not PNG")

        report = _load_json(report_path)
        _require(report.get("status") == "passed", label + " acceptance report failed")
        _require(report.get("viewport") == item.get("viewport"), label + " viewport mismatch")
        _require(
            str(report.get("qt_scale_factor")) == item.get("scale"),
            label + " scale mismatch",
        )
        report_platform = report.get("platform") or {}
        _require(report_platform.get("system") == platform_system, label + " platform/report mismatch")
        _require(report_platform.get("qt_platform") == expected_qt, label + " Qt/report mismatch")
        result_names = {
            result.get("name")
            for result in report.get("results", [])
            if result.get("status") == "passed"
        }
        _require(item["acceptance_item"] in result_names, label + " acceptance item missing")
        screenshot_records = [
            record
            for record in report.get("artifacts", [])
            if record.get("sha256") == item.get("image_sha256")
            and "geometry-" in str(record.get("path") or "")
        ]
        _require(len(screenshot_records) == 1, label + " screenshot/report mismatch")
        report_exemptions = (report.get("geometry") or {}).get("overlap_exemptions") or []
        matching_exemptions = {
            exemption.get("join_key")
            for exemption in report_exemptions
            if exemption.get("screenshot_sha256") == item.get("image_sha256")
        }
        declared_exemptions = set(item.get("overlap_exemption_join_keys") or [])
        _require(
            declared_exemptions == matching_exemptions,
            label + " overlap exemption reconciliation mismatch",
        )
        _require(not seen_exemptions.intersection(declared_exemptions), label + " overlap exemption reused")
        seen_exemptions.update(declared_exemptions)
        expected_exemptions.update(
            exemption.get("join_key") for exemption in report_exemptions
        )

    for platform_system in VISUAL_REVIEW_PLATFORMS:
        for layout in VISUAL_REVIEW_LAYOUTS:
            _require(
                combination_counts.get((platform_system, layout)) == 9,
                "visual review must contain nine samples for {} {}".format(
                    platform_system, layout
                ),
            )
    _require(seen_exemptions == expected_exemptions, "unreviewed overlap exemption exists")
    for index, finding in enumerate(non_blocking):
        label = "non_blocking_findings[{}]".format(index)
        _require(isinstance(finding, dict), label + " is not an object")
        _require(set(finding) == NON_BLOCKING_FINDING_FIELDS, label + " fields mismatch")
        _require(finding.get("impairs_use") is False, label + " impairs use")
        _require(finding.get("join_key") in seen_items, label + " bad join key")
        evidence_path = root / str(finding.get("evidence_path") or "")
        _require(evidence_path.is_file(), label + " evidence does not exist")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify fcstm-gui evidence report contracts")
    parser.add_argument("--evidence")
    parser.add_argument("--reports")
    parser.add_argument("--artifact-root")
    parser.add_argument("--visual-review")
    parser.add_argument("--visual-root")
    args = parser.parse_args(argv)
    try:
        if args.evidence:
            _require(args.reports and args.artifact_root, "evidence verification needs reports and artifact root")
            verify_evidence(args.evidence, args.reports, args.artifact_root)
        if args.visual_review:
            _require(args.visual_root, "visual review verification needs visual root")
            verify_visual_review_attestation(args.visual_review, args.visual_root)
        _require(args.evidence or args.visual_review, "no evidence contract selected")
    except ContractError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
