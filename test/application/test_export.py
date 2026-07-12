from __future__ import unicode_literals

import json
from pathlib import Path

import pytest

from app.application.document import DocumentService
from app.application.export import (
    ExportService,
    _json_ready,
    _plantuml_jar_path,
    _raise_if_cancelled,
    _validate_output,
)
from app.utils.dsl_to_ui import convert_state_machine_to_state_manager, extract_variable_definitions


SOURCE = """
def int count = 0;
state Root {
    state A;
    state B;
    [*] -> A;
    A -> B :: Go effect { count = count + 1; }
    B -> [*];
}
"""


@pytest.fixture
def export_context(tmp_path):
    source = tmp_path / "model.fcstm"
    source.write_text(SOURCE, encoding="utf-8")
    session = DocumentService().load(source)
    snapshot = session.current_valid_snapshot
    manager = convert_state_machine_to_state_manager(
        snapshot.model,
        extract_variable_definitions(session.source_text),
        source_index=snapshot.source_index,
    )
    return session, snapshot, manager


@pytest.mark.parametrize(
    ("kind", "suffix", "magic"),
    [
        ("fcstm", ".fcstm", b"def int"),
        ("plantuml", ".puml", b"@startuml"),
        ("docx", ".docx", b"PK\x03\x04"),
        ("xlsx", ".xlsx", b"PK\x03\x04"),
    ],
)
def test_model_and_office_exports_are_nonempty_and_valid(
    tmp_path, export_context, kind, suffix, magic
):
    session, snapshot, manager = export_context
    target = tmp_path / ("artifact" + suffix)
    result = ExportService().export(
        kind,
        str(target),
        session.source_text,
        snapshot.model,
        state_manager=manager,
        inspect_report=snapshot.inspect_report,
    )
    assert result.size == target.stat().st_size > 0
    assert magic in target.read_bytes()[:4096]


def test_json_exports_have_versioned_object_schema(tmp_path, export_context):
    session, snapshot, manager = export_context
    inspect_target = tmp_path / "inspect.json"
    ExportService().export(
        "inspect-json",
        str(inspect_target),
        session.source_text,
        snapshot.model,
        state_manager=manager,
        inspect_report=snapshot.inspect_report,
    )
    inspect_payload = json.loads(inspect_target.read_text(encoding="utf-8"))
    assert isinstance(inspect_payload, dict)

    dynamic_target = tmp_path / "dynamic.json"
    dynamic_payload = {
        "schema": "fcstm-gui.dynamic-validation-report.case",
        "version": 1,
        "status": "passed",
    }
    ExportService().export(
        "dynamic-json",
        str(dynamic_target),
        session.source_text,
        snapshot.model,
        dynamic_report_json=json.dumps(dynamic_payload),
    )
    assert json.loads(dynamic_target.read_text(encoding="utf-8")) == dynamic_payload


def test_local_plantuml_exports_png_svg_pdf_with_real_java(tmp_path, export_context):
    session, snapshot, _manager = export_context
    expected = {
        "png": b"\x89PNG\r\n\x1a\n",
        "svg": b"<svg",
        "pdf": b"%PDF-",
    }
    for kind, marker in expected.items():
        target = tmp_path / ("graph." + kind)
        result = ExportService().export(
            kind,
            str(target),
            session.source_text,
            snapshot.model,
            plantuml_jar=str(Path("docs/plantuml.jar").resolve()),
        )
        data = target.read_bytes()
        assert result.size == len(data) > 0
        assert marker in data[:4096]
        assert result.graph is not None
        assert result.graph.engine == "smetana"
        assert result.graph.path == str(target.resolve())
        assert result.graph.output_sha256
        assert result.graph.semantic_svg_sha256


def test_plantuml_export_is_normalized_to_smetana(tmp_path, export_context):
    session, snapshot, _manager = export_context
    target = tmp_path / "graph.puml"

    ExportService().export(
        "plantuml", str(target), session.source_text, snapshot.model
    )

    content = target.read_text(encoding="utf-8")
    assert content.count("!pragma layout smetana") == 1
    assert content.splitlines()[1] == "!pragma layout smetana"


class CancelAfterWrite(object):
    def __init__(self):
        self.calls = 0

    def raise_if_cancelled(self):
        self.calls += 1
        if self.calls >= 2:
            raise RuntimeError("cancelled before publish")


def test_export_refuses_overwrite_and_cancel_preserves_existing_file(
    tmp_path, export_context
):
    session, snapshot, _manager = export_context
    target = tmp_path / "model.fcstm"
    target.write_text("old", encoding="utf-8")
    with pytest.raises(FileExistsError):
        ExportService().export(
            "fcstm", str(target), session.source_text, snapshot.model
        )
    with pytest.raises(RuntimeError, match="before publish"):
        ExportService().export(
            "fcstm",
            str(target),
            session.source_text,
            snapshot.model,
            overwrite=True,
            cancel_token=CancelAfterWrite(),
        )
    assert target.read_text(encoding="utf-8") == "old"


def test_export_rejects_unknown_kind_and_invalid_dynamic_schema(
    tmp_path, export_context
):
    session, snapshot, _manager = export_context
    with pytest.raises(ValueError, match="unsupported"):
        ExportService().export("other", str(tmp_path / "x"), session.source_text, snapshot.model)
    with pytest.raises(ValueError, match="schema"):
        ExportService().export(
            "dynamic-json",
            str(tmp_path / "bad.json"),
            session.source_text,
            snapshot.model,
            dynamic_report_json='{"schema": "wrong"}',
        )


@pytest.mark.parametrize(
    ("kind", "kwargs", "message"),
    [
        ("docx", {}, "UI projection"),
        ("xlsx", {}, "UI projection"),
        ("inspect-json", {}, "inspect report"),
        ("dynamic-json", {}, "completed report"),
    ],
)
def test_export_requires_kind_specific_inputs(
    tmp_path, export_context, kind, kwargs, message
):
    session, snapshot, _manager = export_context
    with pytest.raises(ValueError, match=message):
        ExportService().export(
            kind,
            str(tmp_path / (kind + ".out")),
            session.source_text,
            snapshot.model,
            **kwargs
        )


@pytest.mark.parametrize(
    ("kind", "content", "message"),
    [
        ("png", b"wrong", "PNG"),
        ("pdf", b"wrong", "PDF"),
        ("docx", b"wrong", "Office"),
        ("xlsx", b"wrong", "Office"),
        ("svg", b"wrong", "SVG"),
        ("plantuml", b"@startuml", "incomplete"),
        ("inspect-json", b"[]", "object"),
    ],
)
def test_output_validator_rejects_empty_and_bad_magic(tmp_path, kind, content, message):
    path = tmp_path / "bad"
    path.write_bytes(content)
    with pytest.raises(ValueError, match=message):
        _validate_output(kind, path)
    path.write_bytes(b"")
    with pytest.raises(ValueError, match="empty"):
        _validate_output(kind, path)


def test_json_ready_resource_path_and_cancel_fallback(monkeypatch, tmp_path):
    import app.application.export as export

    class JsonValue(object):
        def to_json_dict(self):
            return {"values": ({"x": 1},)}

    class PlainValue(object):
        def __init__(self):
            self.value = {1, 2}

    assert _json_ready(JsonValue()) == {"values": [{"x": 1}]}
    assert sorted(_json_ready(PlainValue())["value"]) == [1, 2]
    assert _json_ready(object()).startswith("<object object")

    monkeypatch.setattr(export.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert _plantuml_jar_path() == str(tmp_path / "docs" / "plantuml.jar")
    monkeypatch.delattr(export.sys, "_MEIPASS", raising=False)
    assert Path(_plantuml_jar_path()).is_file()
    with pytest.raises(RuntimeError, match="cancelled"):
        _raise_if_cancelled(type("Token", (), {"cancelled": True})())
