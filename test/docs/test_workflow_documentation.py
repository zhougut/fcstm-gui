import hashlib
import json
import re
import struct
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs" / "完整操作验收手册.md"
BUILD_WORKFLOW = ROOT / ".github" / "workflows" / "build.yml"
IMAGE_ROOT = ROOT / "docs" / "images" / "workflows"
MANIFEST = IMAGE_ROOT / "manifest.json"
SCHEMA = ROOT / "docs" / "workflow-images.schema.json"
VISUAL_REVIEW_SCHEMA = ROOT / "docs" / "visual-review.schema.json"
WORKFLOWS = (
    "01-open-document",
    "02-diagnostics-navigation",
    "03-real-state-graph",
    "04-ordinary-simulation",
    "05-dynamic-validation",
    "06-five-template-generation",
    "07-unified-export",
    "08-task-results",
    "09-model-crud",
    "10-formulas",
    "11-cross-cutting",
)
UNLINKED_SOURCE_REFERENCE_IDS = {"tasks.clear-completed"}


@pytest.fixture(scope="module")
def manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _validate_schema(value, schema, location="$"):
    if "const" in schema:
        assert value == schema["const"], location
    if "enum" in schema:
        assert value in schema["enum"], location
    type_names = schema.get("type")
    if type_names:
        if isinstance(type_names, str):
            type_names = [type_names]
        matches = {
            "object": lambda item: isinstance(item, dict),
            "array": lambda item: isinstance(item, list),
            "string": lambda item: isinstance(item, str),
            "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
            "boolean": lambda item: isinstance(item, bool),
            "null": lambda item: item is None,
        }
        assert any(matches[name](value) for name in type_names), location
    if isinstance(value, str):
        assert len(value) >= schema.get("minLength", 0), location
        if "pattern" in schema:
            assert re.search(schema["pattern"], value), location
    if isinstance(value, int) and not isinstance(value, bool):
        assert value >= schema.get("minimum", value), location
    if isinstance(value, list):
        assert len(value) >= schema.get("minItems", 0), location
        assert len(value) <= schema.get("maxItems", len(value)), location
        if "items" in schema:
            for index, item in enumerate(value):
                _validate_schema(item, schema["items"], "{}[{}]".format(location, index))
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            assert key in value, "{}.{}".format(location, key)
        if schema.get("additionalProperties") is False:
            assert set(value) <= set(properties), location
        for key, item in value.items():
            if key in properties:
                _validate_schema(item, properties[key], "{}.{}".format(location, key))


def _fenced_block(document, marker, language):
    tail = document.split(marker, 1)[1]
    opening = "```{}\n".format(language)
    body = tail.split(opening, 1)[1]
    return body.split("\n```", 1)[0] + "\n"


def test_manifest_conforms_to_checked_in_strict_schema(manifest):
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    _validate_schema(manifest, schema)


def test_final_visual_review_schema_is_strict_and_function_blocking():
    schema = json.loads(VISUAL_REVIEW_SCHEMA.read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    assert schema["properties"]["samples_expected"]["const"] == 54
    assert schema["properties"]["samples_reviewed"]["const"] == 54
    items = schema["properties"]["items"]
    assert items["minItems"] == items["maxItems"] == 54
    assert items["items"]["additionalProperties"] is False
    assert schema["properties"]["blocking_findings"]["maxItems"] == 0
    required = set(items["items"]["required"])
    assert {
        "join_key",
        "platform",
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
        "overlap_exemption_join_keys",
    } <= required
    for verdict in (
        "text_visible",
        "hit_test_passed",
        "click_passed",
        "focus_passed",
        "accessible_name_passed",
        "business_fact_passed",
        "artifact_fact_passed",
    ):
        assert items["items"]["properties"][verdict]["const"] is True

    acceptance_schema = json.loads(
        (
            ROOT
            / "app"
            / "resources"
            / "self_check"
            / "acceptance_check_report.schema.json"
        ).read_text(encoding="utf-8")
    )
    exemption = acceptance_schema["properties"]["geometry"]["properties"][
        "overlap_exemptions"
    ]["items"]
    assert set(exemption["properties"]["parent"]["enum"]) == {
        "ordinary_simulation_panel",
        "dynamic_validation_panel",
    }


def test_build_workflow_keeps_fresh_products_independent_of_host_toolchains():
    workflow = BUILD_WORKFLOW.read_text(encoding="utf-8")
    verify = workflow.split("  verify:\n", 1)[1]
    assert "needs: build\n    if: ${{ always() }}" in verify
    assert workflow.count("FCSTM_GUI_PRODUCT_LAYOUT:") == 5
    assert "FCSTM_GUI_PRODUCT_LAYOUT: source" in workflow
    assert workflow.count("FCSTM_GUI_PRODUCT_LAYOUT: onedir") == 2
    assert workflow.count("FCSTM_GUI_PRODUCT_LAYOUT: onefile") == 2
    shadow_loop = "for tool in python python3 cc c++ gcc g++ clang clang++ dot; do"
    assert verify.count(shadow_loop) == 4
    assert verify.count('test "$status" -eq 127') == 2
    assert "purpose=evidence-control-plane-only" in verify
    assert "project_imports=forbidden" in verify
    assert "product_execution=forbidden" in verify


def test_workflow_manifest_is_source_only_and_manually_reviewed(manifest):
    assert manifest["schema"] == "fcstm-gui.workflow-images"
    assert manifest["version"] == 1
    assert manifest["evidence_kind"] == "source-reference"
    assert manifest["fresh_release_evidence"] is False
    assert manifest["manual_review"]["status"] == "passed-source-reference"
    assert manifest["manual_review"]["reviewer"]
    assert manifest["source"]["commit"]
    assert manifest["source"]["tree_sha"]
    assert len(manifest["source"]["source_content_sha256"]) == 64
    assert manifest["capture"]["viewport"] == "1280x720"
    assert manifest["capture"]["scale"] == "1"
    assert manifest["capture"]["font_family"] == "Noto Sans CJK SC"


def test_all_manifest_images_exist_match_sha_and_are_real_png(manifest):
    listed = set()
    for item in manifest["images"]:
        path = IMAGE_ROOT / item["path"]
        data = path.read_bytes()
        listed.add(item["path"])
        assert item["platform"] == manifest["capture"]["platform"]
        assert item["viewport"] == manifest["capture"]["viewport"]
        assert item["scale"] == manifest["capture"]["scale"]
        assert item["font_family"] == manifest["capture"]["font_family"]
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", data[16:24])
        assert width == item["width"]
        assert height == item["height"]
        assert len(data) == item["size"]
        assert hashlib.sha256(data).hexdigest() == item["sha256"]
        assert len(data) > 1000
    actual = {
        path.relative_to(IMAGE_ROOT).as_posix()
        for path in IMAGE_ROOT.rglob("*.png")
    }
    assert listed == actual
    assert len(listed) >= 30


def test_eight_core_workflows_have_applicable_stages_and_guide_links(manifest):
    guide = GUIDE.read_text(encoding="utf-8")
    by_workflow = {name: [] for name in WORKFLOWS}
    for item in manifest["images"]:
        by_workflow[item["workflow"]].append(item)
        image_link = "images/workflows/{}".format(item["path"])
        assert (
            image_link in guide
            or "`{}`".format(item["acceptance_id"]) in guide
            or item["acceptance_id"] in UNLINKED_SOURCE_REFERENCE_IDS
        )
    for workflow, items in by_workflow.items():
        assert items, workflow
        stages = {item["stage"] for item in items}
        assert "00" in stages
        assert "03" in stages
    assert {item["stage"] for item in by_workflow["02-diagnostics-navigation"]} >= {
        "00",
        "01",
        "03",
        "04",
    }
    assert {item["stage"] for item in by_workflow["07-unified-export"]} >= {
        "00",
        "01",
        "03",
        "04",
    }
    generation_items = by_workflow["06-five-template-generation"]
    assert {
        item["acceptance_id"]
        for item in generation_items
        if item["stage"] == "03"
    } == {
        "generation.python",
        "generation.c",
        "generation.c-poll",
        "generation.cpp",
        "generation.cpp-poll",
    }
    simulation_items = {
        (item["acceptance_id"], Path(item["path"]).name)
        for item in by_workflow["04-ordinary-simulation"]
    }
    assert ("simulation.pause", "04-simulation-paused.png") in simulation_items
    assert (
        "simulation.continue",
        "05-simulation-continued.png",
    ) in simulation_items


def test_guide_covers_every_acceptance_family_and_iteration_gate():
    guide = GUIDE.read_text(encoding="utf-8")
    required = (
        "文档打开/最近/失败保持",
        "dirty 三分支",
        "源码编辑/保存/重载",
        "七类模型表单 CRUD",
        "imported/generated",
        "简单/复合/Unicode 重命名",
        "三来源诊断与修复",
        "四类公式",
        "图形交互",
        "四类图形导出",
        "普通仿真",
        "动态验证",
        "术语边界",
        "五内置+自定义生成",
        "九类统一导出",
        "任务中心",
        "显式/瞬时任务注册",
        "五类 stale",
        "六类取消",
        "十二键盘 item",
        "几何/可达性",
        "视觉",
        "盲操作复现检查表",
        "每轮截图与文档审阅记录",
        "当前缺口与 READY 门禁",
    )
    for text in required:
        assert text in guide
    assert "不得替代 fresh onedir/onefile" in guide
    assert "NOT READY" in guide


def test_guide_supplies_reproducible_fixtures_and_failure_oracles():
    guide = GUIDE.read_text(encoding="utf-8")
    required = (
        "### 1.4 可复现 fixture 包",
        "assembly.fcstm",
        "root-import.fcstm",
        "rename-crlf.fcstm",
        "dynamic-mismatch.json",
        "custom-template/config.yaml",
        "W_DEADLOCK_LEAF",
        "dynamic.mutation",
        "root=Root",
        "TaskStatus=`cancelled`",
        "TaskStatus=`stale`",
        "graph.export.plantuml",
        "export.dynamic-json",
        "simulation.stop",
        "simulation.reset",
        "tasks.clear-filtered",
        "tasks.clear-completed",
        "tasks.clear-all",
    )
    for text in required:
        assert text in guide
    assert "parent directory" in guide
    assert "basename" in guide
    assert "AcceptRole" in guide
    assert "N/A（同步完成，无可观察 running 态）" in guide
    assert "不妨碍使用" in guide
    assert "hit-test" in guide
    assert "business_fact_passed" in guide


def test_coverage_matrix_expands_stable_ids_without_family_wildcards():
    from scripts.verify_evidence_contract import ACCEPTANCE_NAMES

    guide = GUIDE.read_text(encoding="utf-8")
    matrix = guide.split("## 6. Acceptance-family 覆盖矩阵", 1)[1].split(
        "## 7. 盲操作复现检查表", 1
    )[0]
    assert ".*" not in matrix
    assert ".{" not in matrix
    required_ids = (
        "document.failed-load-preserves-session",
        "dirty.save",
        "source.fresh-reload",
        "model.lifecycle.delete",
        "rename.unicode-crlf",
        "diagnostics.conflict-warning",
        "formula.lifecycle.invalid",
        "graph.selection",
        "simulation.stop",
        "dynamic.case.pseudo_self_loop_step_limit_raises_dfs_error",
        "generation.custom",
        "export.dynamic-json",
        "tasks.transient.formula-validation",
        "stale.export",
        "cancel.load",
        "keyboard.formula.numeric",
        "visual.windows",
    )
    for item_id in required_ids:
        assert "`{}`".format(item_id) in matrix
    for item_id in ACCEPTANCE_NAMES:
        assert "`{}`".format(item_id) in guide


def test_blind_review_and_geometry_templates_are_complete_but_unclaimed():
    guide = GUIDE.read_text(encoding="utf-8")
    for field in (
        "reviewer",
        "date UTC",
        "commit/run",
        "environment",
        "covered item IDs",
        "failed step/observation",
        "documentation/product modification",
        "evidence path/SHA",
        "verdict",
        "focus_before",
        "focus_after",
        "accessible names",
        "screenshot SHA",
    ):
        assert field in guide
    assert "blind-review-1 |" in guide
    assert "final-fresh | 待独立 reviewer 填写" in guide


def test_manual_fixture_blocks_execute_production_paths(tmp_path):
    from app.application.dynamic_validation import DynamicValidationService
    from app.application.generation import GenerationService
    from pyfcstm.model import load_state_machine_from_file, load_state_machine_from_text

    guide = GUIDE.read_text(encoding="utf-8")
    acceptance = _fenced_block(guide, "核心流程使用以下", "fcstm")
    rename = _fenced_block(guide, "`rename-crlf.fcstm` 内容：", "fcstm")
    dynamic_model = _fenced_block(
        guide, "`dynamic-model.fcstm` 完整内容：", "fcstm"
    )
    dynamic_pass = json.loads(
        _fenced_block(guide, "`dynamic-pass.json` 完整内容", "json")
    )

    assert load_state_machine_from_text(acceptance).root_state.name == "Root"
    assert load_state_machine_from_text(rename).root_state.name == "Root"

    (tmp_path / "leaf.fcstm").write_text("state Leaf;", encoding="utf-8")
    (tmp_path / "child.fcstm").write_text(
        'state Child { import "./leaf.fcstm" as Nested; [*] -> Nested; }',
        encoding="utf-8",
    )
    root = tmp_path / "root-import.fcstm"
    root.write_text(
        'state Root { import "./child.fcstm" as Imported; [*] -> Imported; }',
        encoding="utf-8",
    )
    assert load_state_machine_from_file(str(root)).root_state.name == "Root"

    (tmp_path / "dynamic-model.fcstm").write_text(
        dynamic_model, encoding="utf-8"
    )
    pass_path = tmp_path / "dynamic-pass.json"
    pass_path.write_text(json.dumps(dynamic_pass), encoding="utf-8")
    service = DynamicValidationService()
    assert service.run_scenario(pass_path).status == "passed"
    dynamic_pass["case_id"] = "manual_mutation"
    dynamic_pass["steps"][-1]["expected"]["state"] = "Root.Mutated"
    mismatch_path = tmp_path / "dynamic-mismatch.json"
    mismatch_path.write_text(json.dumps(dynamic_pass), encoding="utf-8")
    assert service.run_scenario(mismatch_path).status == "mismatch"

    template = tmp_path / "custom-template"
    template.mkdir()
    (template / "config.yaml").write_text("{}\n", encoding="utf-8")
    (template / "hello.txt.j2").write_text(
        "root={{ model.root_state.name }}", encoding="utf-8"
    )
    generated = GenerationService().generate(
        load_state_machine_from_text(acceptance),
        str(tmp_path / "generated-custom"),
        custom_template_dir=str(template),
    )
    assert [item.relative_path for item in generated.files] == ["hello.txt"]
    assert (tmp_path / "generated-custom" / "hello.txt").read_text() == "root=Root"
    (template / "config.yaml").unlink()
    invalid_target = tmp_path / "generated-custom-invalid"
    with pytest.raises(FileNotFoundError):
        GenerationService().generate(
            load_state_machine_from_text(acceptance),
            str(invalid_target),
            custom_template_dir=str(template),
        )
    assert not invalid_target.exists()
