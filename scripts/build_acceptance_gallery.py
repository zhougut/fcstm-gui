#!/usr/bin/env python3
"""Materialize the 140-item GUI acceptance run as a reviewable image gallery.

The input report is produced by ``main.py --acceptance-check``.  This keeps the
checked-in documentation useful without pretending that source screenshots are
fresh release evidence.
"""

from __future__ import unicode_literals

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_evidence_contract import ACCEPTANCE_NAMES


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _current_commit():
    try:
        return subprocess.check_output(
            ("git", "rev-parse", "HEAD"), cwd=str(ROOT), universal_newlines=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def build(report_path, output_dir, artifacts_dir=None, source_commit=None, copy_images=True):
    report_path = Path(report_path).resolve()
    source_root = Path(artifacts_dir).resolve() if artifacts_dir else report_path.parent / "artifacts"
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    results = report.get("results") or []
    if tuple(item.get("name") for item in results) != ACCEPTANCE_NAMES:
        raise ValueError("acceptance report item order does not match the frozen contract")
    if report.get("status") != "passed" or report.get("counts") != {
        "failed": 0,
        "passed": len(ACCEPTANCE_NAMES),
        "total": len(ACCEPTANCE_NAMES),
    }:
        raise ValueError("acceptance report is not a complete passed run")

    entries = []
    for order, result in enumerate(results, 1):
        candidates = [
            item.get("path")
            for item in result.get("artifact_inventory", [])
            if str(item.get("path", "")).startswith("item-")
            and str(item.get("path", "")).lower().endswith(".png")
        ]
        if not candidates:
            raise ValueError("{} has no item screenshot".format(result["name"]))
        source_image = source_root / candidates[0]
        if not source_image.is_file():
            raise FileNotFoundError(str(source_image))
        target_name = "{:03d}-{}.png".format(order, result["name"].replace("/", "-"))
        target = output_dir / target_name
        if copy_images:
            shutil.copyfile(str(source_image), str(target))
        elif not target.is_file():
            raise FileNotFoundError(str(target))
        data_size = target.stat().st_size
        image_sha256 = _sha256(target)
        if data_size < 1000:
            raise ValueError("{} is too small to be a screenshot".format(target))
        entries.append(
            {
                "order": order,
                "acceptance_id": result["name"],
                "status": result["status"],
                "duration_ms": result.get("duration_ms"),
                "source_revision": result.get("source_revision"),
                "dependency_fingerprint": result.get("dependency_fingerprint"),
                "detail": result.get("detail", ""),
                "image": target_name,
                "image_size": data_size,
                "image_sha256": image_sha256,
            }
        )

    manifest = {
        "schema": "fcstm-gui.acceptance-gallery",
        "version": 1,
        "evidence_kind": "source-acceptance",
        "fresh_release_evidence": False,
        "statement": (
            "一次 Linux xcb 源码态 GUI acceptance 实操运行的逐项截图；"
            "不能替代 Windows/macOS fresh release 证据。"
        ),
        "source": {"commit": source_commit or _current_commit()},
        "report": {
            "path": report_path.name,
            "artifacts_root": source_root.name,
            "schema": report.get("schema"),
            "version": report.get("version"),
            "status": report.get("status"),
            "counts": report.get("counts"),
            "viewport": report.get("viewport"),
            "platform": report.get("platform"),
            "qt_scale_factor": report.get("qt_scale_factor"),
        },
        "items": entries,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown = [
        "# 140 项 GUI Acceptance 截图索引",
        "",
        "本目录来自一次真实 Linux xcb 源码态 GUI acceptance 运行。140 项均独立执行、",
        "均为 `passed`，每项有单独截图、耗时、revision/fingerprint 和 SHA-256。",
        "这些图用于逐项操作说明和人工复核，**不是** Windows/macOS fresh release 证据。",
        "",
        "运行摘要：`{}`，viewport `{}`，平台 `{}`，结果 `{}`。".format(
            report_path.name,
            report.get("viewport"),
            report.get("platform"),
            report.get("counts"),
        ),
        "",
        "| # | 稳定 acceptance ID | 状态 | 截图 | SHA-256 |",
        "| ---: | --- | :---: | --- | --- |",
    ]
    for entry in entries:
        markdown.append(
            "| {order} | `{acceptance_id}` | `{status}` | "
            "[打开]({image}) | `{image_sha256}` |".format(**entry)
        )
    (output_dir / "README.md").write_text(
        "\n".join(markdown) + "\n", encoding="utf-8"
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, help="acceptance report.json")
    parser.add_argument(
        "--artifacts",
        help="directory containing the report's screenshot/artifact paths; defaults to report/../artifacts",
    )
    parser.add_argument("--source-commit", help="commit that produced the GUI report")
    parser.add_argument("--output", required=True, help="gallery output directory")
    parser.add_argument(
        "--no-copy-images",
        action="store_true",
        help="only rebuild metadata and require existing target images",
    )
    args = parser.parse_args()
    manifest = build(
        args.report,
        args.output,
        artifacts_dir=args.artifacts,
        source_commit=args.source_commit,
        copy_images=not args.no_copy_images,
    )
    print("acceptance gallery: {} items".format(len(manifest["items"])))


if __name__ == "__main__":
    main()
