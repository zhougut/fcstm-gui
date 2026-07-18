from __future__ import unicode_literals

import hashlib
import json
import platform
from types import SimpleNamespace

from PyQt5 import QtWidgets

from app.acceptance_check import (
    AcceptanceDriver,
    _is_preapproved_native_overlap,
    _keyboard_replace,
    _parse_viewport,
    run_acceptance_check,
)
from app.application.task_runner import TaskResult, TaskStamp, TaskStatus


def test_parse_viewport_rejects_malformed_or_too_small_values():
    assert _parse_viewport("1280x720") == (1280, 720)
    for value in ("1280", "wide", "639x480", "1280x479"):
        try:
            _parse_viewport(value)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid viewport accepted: " + value)


def test_native_overlap_preapproval_is_exact_and_function_oriented():
    allowed = (
        "simulation_cycle_button",
        "simulation_initialize_button",
    )
    assert _is_preapproved_native_overlap(
        "Darwin", "cocoa", "ordinary_simulation_panel", allowed
    )
    assert _is_preapproved_native_overlap(
        "Darwin",
        "cocoa",
        "dynamic_validation_panel",
        ("dynamic_run_case_button", "dynamic_run_user_button"),
    )
    assert not _is_preapproved_native_overlap(
        "Linux", "xcb", "ordinary_simulation_panel", allowed
    )
    assert not _is_preapproved_native_overlap(
        "Darwin", "cocoa", "graph_panel", allowed
    )
    assert not _is_preapproved_native_overlap(
        "Darwin",
        "cocoa",
        "ordinary_simulation_panel",
        ("simulation_cancel_button", "unknown_button"),
    )


def test_current_validation_predicate_rejects_cancelled_same_revision(tmp_path):
    driver = AcceptanceDriver(tmp_path / "artifacts", (1280, 720))
    session = SimpleNamespace(
        session_id="session", source_revision=4, source_text="valid"
    )
    driver.window = SimpleNamespace(document_session=session)
    stamp = TaskStamp("task", "document", "session", 4, 1)

    assert not driver._is_current_validation(
        TaskResult(stamp=stamp, status=TaskStatus.CANCELLED)
    )
    assert driver._is_current_validation(
        TaskResult(
            stamp=stamp,
            status=TaskStatus.SUCCESS,
            value=SimpleNamespace(
                session_id="session", source_revision=4, source_text="valid"
            ),
        )
    )


def test_keyboard_replace_commits_multiline_unicode_without_clipboard(qtbot):
    editor = QtWidgets.QPlainTextEdit("old")
    qtbot.addWidget(editor)
    editor.show()

    _keyboard_replace(editor, "第一行\nstate Root;")

    assert editor.toPlainText() == "第一行\nstate Root;"


def test_full_gui_acceptance_writes_report(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    report_path = tmp_path / "acceptance.json"
    artifact_dir = tmp_path / "artifacts"

    assert run_acceptance_check(
        str(report_path), str(artifact_dir), "1280x720"
    ) == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["schema"] == "fcstm-gui.acceptance-check-report"
    assert report["version"] == 1
    assert report["status"] == "passed"
    assert report["counts"] == {"total": 140, "passed": 140, "failed": 0}
    names = [item["name"] for item in report["results"]]
    assert len(names) == len(set(names))
    assert hashlib.sha256(
        ("\n".join(names) + "\n").encode("utf-8")
    ).hexdigest() == "3f6b76bfb88f345bd0b1f8492c72406511580e8ea3f2afc68d0aaedfb2ecb1ea"
    for required in (
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
        "terminology.dynamic-not-formal",
        "geometry.active-workspaces",
    ):
        assert required in names
    assert {
        "formula.{}.{}".format(kind, validity)
        for kind in ("guard", "effect", "lifecycle", "numeric")
        for validity in ("valid", "invalid")
    } <= set(names)
    assert {
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
    } <= set(names)
    assert {
        "model.{}.{}".format(entity, operation)
        for entity in (
            "state",
            "variable",
            "event",
            "transition",
            "guard",
            "effect",
            "lifecycle",
        )
        for operation in ("add", "edit", "delete")
    } <= set(names)
    assert {
        "cancel.load",
        "cancel.simulation",
        "cancel.dynamic",
        "cancel.graph",
        "cancel.generation",
        "cancel.export",
    } <= set(names)
    assert {
        "stale.graph",
        "stale.simulation",
        "stale.dynamic",
        "stale.generation",
        "stale.export",
    } <= set(names)
    assert "formula.stale" in names
    assert {
        "generation.python",
        "generation.c",
        "generation.c-poll",
        "generation.cpp",
        "generation.cpp-poll",
        "generation.custom",
        "generation.overwrite",
    } <= set(names)
    assert {
        "export.dsl",
        "export.word",
        "export.excel",
        "export.plantuml",
        "export.png",
        "export.svg",
        "export.pdf",
        "export.inspect-json",
        "export.dynamic-json",
    } <= set(names)
    assert len([name for name in names if name.startswith("dynamic.case.")]) == 4
    assert {"dynamic.mutation", "dynamic.recover", "dynamic.user", "dynamic.export"} <= set(names)
    assert {
        "graph.export.plantuml",
        "graph.export.png",
        "graph.export.svg",
        "graph.export.pdf",
    } <= set(names)
    assert {
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
    } <= set(names)
    assert {
        "tasks.registry." + kind
        for kind in ("load", "inspect", "graph", "simulation", "dynamic", "generation", "export")
    } <= set(names)
    assert {
        "tasks.transient.document-validation",
        "tasks.transient.formula-validation",
    } <= set(names)
    assert all(item["artifacts"] for item in report["results"])
    assert all(item["artifact_inventory"] == item["artifacts"] for item in report["results"])
    assert all(isinstance(item["evidence"], dict) for item in report["results"])
    assert all(item["source_revision"] is not None for item in report["results"])
    assert all(item["dependency_fingerprint"] for item in report["results"])
    assert all(item["error_chain"] == [] for item in report["results"])
    assert [item["isolation"]["case_index"] for item in report["results"]] == list(
        range(1, 141)
    )
    assert all(
        item["isolation"]["strategy"] == "fresh-window"
        for item in report["results"]
    )
    assert len(report["artifacts"]) >= len(report["results"])
    artifact_records = {}
    for item in report["artifacts"]:
        identity = (item["size"], item["sha256"])
        assert artifact_records.setdefault(item["path"], identity) == identity
        path = artifact_dir / item["path"]
        data = path.read_bytes()
        assert len(data) == item["size"]
        assert hashlib.sha256(data).hexdigest() == item["sha256"]
    assert report["geometry"]["viewport"] == "1280x720"
    assert report["geometry"]["font_family"] == "Noto Sans CJK SC"
    assert report["geometry"]["font_point_size"] == 10
    workspaces = report["geometry"]["active_workspaces"]
    modifier = "Meta" if platform.system() == "Darwin" else "Ctrl"
    assert [item["shortcut"] for item in workspaces] == [
        "{}+{}".format(modifier, index) for index in range(1, 7)
    ]
    assert all(item["visible_to_window"] for item in workspaces)
    assert all(item["contained_by_window"] for item in workspaces)
    assert all(not item["overlaps"] for item in workspaces)
    assert all(item["current_tab_rect"][2:] > [0, 0] for item in workspaces)
    assert all(item["focus_chain"] for item in workspaces)
    exemptions = report["geometry"]["overlap_exemptions"]
    if platform.system() == "Darwin":
        assert len(exemptions) == 9
        assert {item["parent"] for item in exemptions} == {
            "ordinary_simulation_panel",
            "dynamic_validation_panel",
        }
        assert all(
            item[key] is True
            for item in exemptions
            for key in (
                "text_visible",
                "hit_test_passed",
                "click_passed",
                "focus_passed",
                "accessible_name_passed",
                "business_fact_passed",
                "artifact_fact_passed",
            )
        )
    else:
        assert exemptions == []


def test_acceptance_schema_requires_item_evidence_and_artifacts():
    from app import acceptance_check

    schema_path = (
        acceptance_check.Path(acceptance_check.__file__).resolve().parent
        / "resources"
        / "self_check"
        / "acceptance_check_report.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    item_schema = schema["properties"]["results"]["items"]
    assert set(item_schema["required"]) >= {
        "name",
        "status",
        "duration_ms",
        "detail",
        "source_revision",
        "dependency_fingerprint",
        "error_chain",
        "evidence",
        "artifacts",
        "artifact_inventory",
        "isolation",
    }
    geometry_schema = schema["properties"]["geometry"]
    assert set(geometry_schema["required"]) >= {
        "viewport",
        "font_family",
        "font_point_size",
        "active_workspaces",
        "buttons",
        "overlap_exemptions",
        "focus_chain_exemptions",
    }
    workspace_schema = geometry_schema["properties"]["active_workspaces"]["items"]
    assert set(workspace_schema["required"]) >= {
        "shortcut",
        "page",
        "focus_after",
        "visible_to_window",
        "contained_by_window",
        "rect",
        "focus_rect",
        "hidden_pages_visible",
        "current_tab_rect",
        "focus_chain",
        "scroll_areas",
        "headers",
        "current_items",
        "overlaps",
    }
    exemption_schema = geometry_schema["properties"]["overlap_exemptions"]["items"]
    assert exemption_schema["additionalProperties"] is False
    assert set(exemption_schema["required"]) >= {
        "join_key",
        "platform",
        "qt_platform",
        "style",
        "layout",
        "viewport",
        "scale",
        "acceptance_item",
        "parent",
        "widgets",
        "intersection",
        "reason",
        "screenshot_path",
        "screenshot_sha256",
        "text_visible",
        "hit_test_passed",
        "click_passed",
        "focus_passed",
        "accessible_name_passed",
        "business_fact_passed",
        "artifact_fact_passed",
    }
    for key in (
        "text_visible",
        "hit_test_passed",
        "click_passed",
        "focus_passed",
        "accessible_name_passed",
        "business_fact_passed",
        "artifact_fact_passed",
    ):
        assert exemption_schema["properties"][key] == {"const": True}
