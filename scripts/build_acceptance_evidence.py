from __future__ import unicode_literals

import argparse
import datetime as _datetime
import hashlib
import json
import os
import zipfile
from pathlib import Path

SCHEMA = "fcstm-gui.acceptance-evidence"
PRODUCT_SCHEMA = "fcstm-gui.product-manifest"
VERSION = 1
DEFAULT_EXCLUDES = ("manifest-input",)


class EvidenceError(ValueError):
    pass


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _relative(path, root):
    path = Path(path).resolve()
    root = Path(root).resolve()
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _file_record(path, root):
    path = Path(path)
    return {
        "path": _relative(path, root),
        "size": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _require_object(value, label):
    if not isinstance(value, dict):
        raise EvidenceError(label + " must be a JSON object")
    return value


def _require_string(value, label):
    if not isinstance(value, str) or not value:
        raise EvidenceError(label + " must be a non-empty string")
    return value


def _load_report(path, root):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as error:
        raise EvidenceError("invalid JSON report {}: {}".format(path, error))
    _require_object(payload, "report")
    schema = _require_string(payload.get("schema"), "report.schema")
    version = payload.get("version")
    if not isinstance(version, int):
        raise EvidenceError("report.version must be an integer")
    status = _require_string(payload.get("status"), "report.status")
    record = _file_record(path, root)
    record.update({"schema": schema, "version": version, "status": status})
    counts = payload.get("counts")
    if counts is not None:
        _require_object(counts, "report.counts")
        record["counts"] = counts
    return record


def _is_excluded(path, root, excludes):
    relative_parts = Path(path).resolve().relative_to(Path(root).resolve()).parts
    return any(part in excludes for part in relative_parts)


def _collect_files(root, suffixes=None, excludes=DEFAULT_EXCLUDES):
    root = Path(root)
    if not root.exists() or not root.is_dir():
        raise EvidenceError("directory does not exist: {}".format(root))
    paths = []
    excludes = tuple(excludes or ())
    for path in root.rglob("*"):
        if not path.is_file() or _is_excluded(path, root, excludes):
            continue
        if suffixes is not None and path.suffix.lower() not in suffixes:
            continue
        paths.append(path)
    return sorted(paths, key=lambda item: item.as_posix())


def _zip_entries(path):
    entries = []
    with zipfile.ZipFile(str(path), "r") as archive:
        for info in sorted(archive.infolist(), key=lambda item: item.filename):
            if info.is_dir():
                continue
            data = archive.read(info.filename)
            entries.append(
                {
                    "path": info.filename,
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
    return entries


def build_product_manifest(product_paths, base_dir=None, generated_at=None):
    raw_paths = [Path(item) for item in product_paths]
    if base_dir is not None:
        base = Path(base_dir).resolve()
    elif raw_paths:
        base = Path(os.path.commonpath([str(path.resolve().parent) for path in raw_paths]))
    else:
        base = Path.cwd().resolve()
    products = []
    for item in product_paths:
        path = Path(item)
        if not path.exists() or not path.is_file():
            raise EvidenceError("product does not exist: {}".format(path))
        record = _file_record(path, base)
        record["name"] = path.name
        if path.suffix.lower() == ".zip":
            record["entries"] = _zip_entries(path)
        products.append(record)
    payload = {
        "schema": PRODUCT_SCHEMA,
        "version": VERSION,
        "generated_at": generated_at
        or _datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "products": products,
        "counts": {"products": len(products)},
    }
    validate_product_manifest(payload)
    return payload


def validate_product_manifest(payload):
    _require_object(payload, "product_manifest")
    if payload.get("schema") != PRODUCT_SCHEMA:
        raise EvidenceError("product_manifest.schema must be " + PRODUCT_SCHEMA)
    if payload.get("version") != VERSION:
        raise EvidenceError("product_manifest.version must be 1")
    products = payload.get("products")
    if not isinstance(products, list):
        raise EvidenceError("product_manifest.products must be an array")
    for index, product in enumerate(products):
        _validate_file_item(product, "products[{}]".format(index))
        _require_string(product.get("name"), "products[].name")
        if "entries" in product:
            if not isinstance(product["entries"], list):
                raise EvidenceError("products[].entries must be an array")
            for entry_index, entry in enumerate(product["entries"]):
                _validate_file_item(
                    entry,
                    "products[{}].entries[{}]".format(index, entry_index),
                )
    counts = _require_object(payload.get("counts"), "product_manifest.counts")
    if counts.get("products") != len(products):
        raise EvidenceError("product_manifest.counts.products mismatch")
    return True


def compare_product_manifests(actual, expected):
    validate_product_manifest(actual)
    validate_product_manifest(expected)
    actual_by_name = {item["name"]: item for item in actual["products"]}
    expected_by_name = {item["name"]: item for item in expected["products"]}
    if set(actual_by_name) != set(expected_by_name):
        raise EvidenceError("product manifest names differ")
    for name, actual_item in actual_by_name.items():
        expected_item = expected_by_name[name]
        for key in ("size", "sha256"):
            if actual_item[key] != expected_item[key]:
                raise EvidenceError("product {} {} mismatch".format(name, key))
        if actual_item.get("entries", []) != expected_item.get("entries", []):
            raise EvidenceError("product {} entries mismatch".format(name))
    return True


def build_evidence(
    reports_dir,
    artifacts_dir,
    screenshots_dir,
    commit,
    run_id,
    generated_at=None,
    product_manifest_path=None,
):
    reports_dir = Path(reports_dir)
    artifacts_dir = Path(artifacts_dir)
    screenshots_dir = Path(screenshots_dir)
    reports = [
        _load_report(path, reports_dir)
        for path in _collect_files(reports_dir, {".json"}, excludes=())
    ]
    artifacts = [
        _file_record(path, artifacts_dir)
        for path in _collect_files(artifacts_dir, excludes=DEFAULT_EXCLUDES)
    ]
    screenshots = [
        _file_record(path, screenshots_dir)
        for path in _collect_files(screenshots_dir, {".png"}, excludes=())
    ]
    product_manifests = []
    if product_manifest_path is not None:
        product_manifests.append(_file_record(product_manifest_path, artifacts_dir))
    payload = {
        "schema": SCHEMA,
        "version": VERSION,
        "generated_at": generated_at
        or _datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "run": {
            "commit": _require_string(commit, "run.commit"),
            "run_id": _require_string(run_id, "run.run_id"),
        },
        "inputs": {
            "reports_dir": str(reports_dir),
            "artifacts_dir": str(artifacts_dir),
            "screenshots_dir": str(screenshots_dir),
        },
        "reports": reports,
        "artifacts": artifacts,
        "screenshots": screenshots,
        "product_manifests": product_manifests,
        "counts": {
            "reports": len(reports),
            "artifacts": len(artifacts),
            "screenshots": len(screenshots),
            "product_manifests": len(product_manifests),
        },
    }
    validate_evidence(payload)
    return payload


def _validate_file_item(item, label):
    _require_object(item, label)
    _require_string(item.get("path"), label + ".path")
    if not isinstance(item.get("size"), int) or item["size"] < 0:
        raise EvidenceError(label + ".size must be a non-negative integer")
    digest = _require_string(item.get("sha256"), label + ".sha256")
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise EvidenceError(label + ".sha256 must be lowercase SHA256 hex")


def validate_evidence(payload):
    _require_object(payload, "evidence")
    if payload.get("schema") != SCHEMA:
        raise EvidenceError("evidence.schema must be " + SCHEMA)
    if payload.get("version") != VERSION:
        raise EvidenceError("evidence.version must be 1")
    _require_string(payload.get("generated_at"), "evidence.generated_at")
    run = _require_object(payload.get("run"), "evidence.run")
    _require_string(run.get("commit"), "evidence.run.commit")
    _require_string(run.get("run_id"), "evidence.run.run_id")
    for section in ("reports", "artifacts", "screenshots", "product_manifests"):
        items = payload.get(section)
        if not isinstance(items, list):
            raise EvidenceError(section + " must be an array")
        for index, item in enumerate(items):
            _validate_file_item(item, section + "[{}]".format(index))
            if section == "reports":
                _require_string(item.get("schema"), "reports[].schema")
                if not isinstance(item.get("version"), int):
                    raise EvidenceError("reports[].version must be an integer")
                _require_string(item.get("status"), "reports[].status")
    counts = _require_object(payload.get("counts"), "evidence.counts")
    for section in ("reports", "artifacts", "screenshots", "product_manifests"):
        if counts.get(section) != len(payload[section]):
            raise EvidenceError(
                "counts.{} does not match {} length".format(section, section)
            )
    return True


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def write_evidence(path, payload):
    validate_evidence(payload)
    write_json(path, payload)


def _load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as error:
        raise EvidenceError("invalid JSON {}: {}".format(path, error))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build fcstm-gui acceptance evidence manifest"
    )
    parser.add_argument("--reports", required=True, help="directory containing JSON reports")
    parser.add_argument("--artifacts", required=True, help="directory containing runtime artifacts")
    parser.add_argument("--screenshots", required=True, help="directory containing PNG screenshots")
    parser.add_argument("--commit", default=os.environ.get("GITHUB_SHA", "local"))
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", "local"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--product", action="append", default=[])
    parser.add_argument("--product-manifest")
    parser.add_argument("--expected-product-manifest")
    args = parser.parse_args(argv)
    try:
        product_manifest_path = args.product_manifest
        if args.product:
            if not product_manifest_path:
                raise EvidenceError("--product requires --product-manifest")
            product_manifest = build_product_manifest(args.product)
            if args.expected_product_manifest:
                compare_product_manifests(
                    product_manifest,
                    _load_json(args.expected_product_manifest),
                )
            write_json(product_manifest_path, product_manifest)
        payload = build_evidence(
            args.reports,
            args.artifacts,
            args.screenshots,
            args.commit,
            args.run_id,
            product_manifest_path=product_manifest_path,
        )
        write_evidence(args.output, payload)
    except EvidenceError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
