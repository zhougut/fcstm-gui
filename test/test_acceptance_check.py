from __future__ import unicode_literals

import json

from app.acceptance_check import _parse_viewport, run_acceptance_check


def test_parse_viewport_rejects_malformed_or_too_small_values():
    assert _parse_viewport("1280x720") == (1280, 720)
    for value in ("1280", "wide", "639x480", "1280x479"):
        try:
            _parse_viewport(value)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid viewport accepted: " + value)


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
    assert report["counts"] == {"total": 11, "passed": 11, "failed": 0}
    assert len(report["artifacts"]) >= 8
    assert report["geometry"]["viewport"] == "1280x720"
    assert report["geometry"]["font_family"] == "Noto Sans CJK SC"
    assert report["geometry"]["font_point_size"] == 10
