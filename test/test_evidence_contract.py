import hashlib
import json

import pytest

from app import self_check
from app.acceptance_check import AcceptanceDriver
from scripts.verify_evidence_contract import (
    ACCEPTANCE_NAMES,
    SELF_CHECK_BEHAVIOR,
    SELF_CHECK_MODULE_CLOSURE,
    SELF_CHECK_NAMES_SHA256,
    SELF_CHECK_TOTAL,
    ContractError,
    _verify_overlap_exemptions,
    verify_visual_review_attestation,
)


def test_fresh_evidence_verifier_matches_production_acceptance_catalog(
    qtbot, tmp_path
):
    driver = AcceptanceDriver(str(tmp_path / "artifacts"), (1280, 720))
    names = []
    driver.run_item = lambda name, function, with_document=True: names.append(name)
    try:
        driver.run()
    finally:
        driver.close()

    assert tuple(names) == ACCEPTANCE_NAMES


def test_fresh_evidence_verifier_locks_complete_self_check_inventory():
    names = [name for name, _check in self_check._checks()]
    module_count = sum(name.startswith("import ") for name in names)

    assert len(names) == SELF_CHECK_TOTAL
    assert module_count == SELF_CHECK_MODULE_CLOSURE
    assert len(names) - module_count == SELF_CHECK_BEHAVIOR
    assert hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest() == (
        SELF_CHECK_NAMES_SHA256
    )


def test_overlap_exemption_verifier_requires_exact_cocoa_functional_record(tmp_path):
    screenshot = tmp_path / "geometry.png"
    screenshot.write_bytes(b"real screenshot bytes")
    digest = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    report = {
        "platform": {"system": "Darwin", "qt_platform": "cocoa"},
        "viewport": "1280x720",
        "qt_scale_factor": "1",
        "geometry": {
            "overlap_exemptions": [
                {
                    "join_key": (
                        "Darwin|onefile|1280x720|1|geometry.active-workspaces|"
                        "simulation_cycle_button|simulation_initialize_button"
                    ),
                    "platform": "Darwin",
                    "qt_platform": "cocoa",
                    "style": "macintosh",
                    "layout": "onefile",
                    "viewport": "1280x720",
                    "scale": "1",
                    "acceptance_item": "geometry.active-workspaces",
                    "parent": "ordinary_simulation_panel",
                    "widgets": [
                        "simulation_cycle_button",
                        "simulation_initialize_button",
                    ],
                    "intersection": [96, 93, 4, 32],
                    "reason": "native geometry only",
                    "screenshot_path": screenshot.name,
                    "screenshot_sha256": digest,
                    "text_visible": True,
                    "hit_test_passed": True,
                    "click_passed": True,
                    "focus_passed": True,
                    "accessible_name_passed": True,
                    "business_fact_passed": True,
                    "artifact_fact_passed": True,
                }
            ]
        },
    }

    _verify_overlap_exemptions(report, tmp_path)

    exemption = report["geometry"]["overlap_exemptions"][0]
    exemption["join_key"] = (
        "Darwin|onefile|1280x720|1|geometry.active-workspaces|"
        "dynamic_run_case_button|dynamic_run_user_button"
    )
    exemption["parent"] = "dynamic_validation_panel"
    exemption["widgets"] = [
        "dynamic_run_case_button",
        "dynamic_run_user_button",
    ]
    _verify_overlap_exemptions(report, tmp_path)

    report["geometry"]["overlap_exemptions"][0]["click_passed"] = False
    with pytest.raises(ContractError, match="functional verdict"):
        _verify_overlap_exemptions(report, tmp_path)

    report["geometry"]["overlap_exemptions"][0]["click_passed"] = True
    report["geometry"]["overlap_exemptions"][0]["widgets"][1] = "unknown_button"
    with pytest.raises(ContractError, match="not preapproved"):
        _verify_overlap_exemptions(report, tmp_path)


def test_visual_review_verifier_locks_six_products_and_54_functional_samples(
    tmp_path,
):
    platforms = {
        "Linux": ("xcb", "linux-x86_64"),
        "Windows": ("windows", "windows-x86_64"),
        "Darwin": ("cocoa", "macos-x86_64"),
    }
    items = []
    for platform_system, (qt_platform, platform_label) in platforms.items():
        for layout in ("onedir", "onefile"):
            artifact = "fcstm-gui-{}{}".format(
                platform_label,
                "-onefile" if layout == "onefile" else "",
            )
            product = tmp_path / "products" / artifact
            product.parent.mkdir(exist_ok=True)
            product.write_bytes(artifact.encode("ascii"))
            product_digest = hashlib.sha256(product.read_bytes()).hexdigest()
            report_artifacts = []
            item_inputs = []
            for index in range(9):
                image = tmp_path / "images" / artifact / "geometry-{}.png".format(index)
                image.parent.mkdir(parents=True, exist_ok=True)
                image.write_bytes(b"\x89PNG\r\n\x1a\n" + artifact.encode("ascii") + bytes([index]))
                digest = hashlib.sha256(image.read_bytes()).hexdigest()
                report_artifacts.append(
                    {
                        "path": "geometry-{}.png".format(index),
                        "size": image.stat().st_size,
                        "sha256": digest,
                    }
                )
                item_inputs.append((image, digest))
            # The real reports also retain the item-140 alias for the final
            # geometry screenshot.  It must not be mistaken for a second
            # canonical geometry record by the visual verifier.
            report_artifacts.append(
                dict(
                    report_artifacts[-1],
                    path="item-140-geometry-active-workspaces.png",
                )
            )
            report = {
                "status": "passed",
                "viewport": "1280x720",
                "qt_scale_factor": "1",
                "platform": {
                    "system": platform_system,
                    "qt_platform": qt_platform,
                },
                "results": [
                    {"name": "geometry.active-workspaces", "status": "passed"}
                ],
                "artifacts": report_artifacts,
                "geometry": {"overlap_exemptions": []},
            }
            report_path = tmp_path / "reports" / "{}.json".format(artifact)
            report_path.parent.mkdir(exist_ok=True)
            report_path.write_text(json.dumps(report), encoding="utf-8")
            report_digest = hashlib.sha256(report_path.read_bytes()).hexdigest()
            for image, image_digest in item_inputs:
                image_relative = image.relative_to(tmp_path).as_posix()
                join_key = "|".join(
                    (
                        platform_system,
                        layout,
                        "1280x720",
                        "1",
                        "geometry.active-workspaces",
                        image_relative,
                    )
                )
                item = {
                    "join_key": join_key,
                    "platform": platform_system,
                    "qt_platform": qt_platform,
                    "layout": layout,
                    "artifact": artifact,
                    "product": product.relative_to(tmp_path).as_posix(),
                    "product_sha256": product_digest,
                    "acceptance_report_path": report_path.relative_to(tmp_path).as_posix(),
                    "acceptance_report_sha256": report_digest,
                    "image_path": image_relative,
                    "image_sha256": image_digest,
                    "viewport": "1280x720",
                    "scale": "1",
                    "acceptance_item": "geometry.active-workspaces",
                    "overlap_exemption_join_keys": [],
                    "status": "passed",
                    "notes": "reviewed",
                }
                item.update(
                    {
                        key: True
                        for key in (
                            "text_visible",
                            "hit_test_passed",
                            "click_passed",
                            "focus_passed",
                            "accessible_name_passed",
                            "business_fact_passed",
                            "artifact_fact_passed",
                        )
                    }
                )
                items.append(item)
    attestation = {
        "schema": "fcstm-gui.visual-review",
        "version": 1,
        "reviewer": "independent-reviewer",
        "reviewed_at": "2026-07-13T00:00:00Z",
        "commit": "1" * 40,
        "run_id": "123456",
        "samples_expected": 54,
        "samples_reviewed": 54,
        "status": "passed",
        "items": items,
        "blocking_findings": [],
        "non_blocking_findings": [],
    }
    attestation_path = tmp_path / "visual-review.json"
    attestation_path.write_text(json.dumps(attestation), encoding="utf-8")

    assert verify_visual_review_attestation(attestation_path, tmp_path)

    attestation["items"][0]["click_passed"] = False
    attestation_path.write_text(json.dumps(attestation), encoding="utf-8")
    with pytest.raises(ContractError, match="functional verdict"):
        verify_visual_review_attestation(attestation_path, tmp_path)
