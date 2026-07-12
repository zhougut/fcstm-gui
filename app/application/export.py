"""Atomic unified artifact export and output validation."""

from __future__ import unicode_literals

import json
import os
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Optional

from pyfcstm.model import load_state_machine_from_text

from app.application.graph_render import (
    GraphRenderResult,
    GraphRenderService,
    normalize_plantuml_source,
)
from app.utils.export_to_excel import export_statechart_to_excel
from app.utils.export_to_word import export_statechart_to_word


EXPORT_KINDS = (
    "fcstm",
    "docx",
    "xlsx",
    "plantuml",
    "png",
    "svg",
    "pdf",
    "inspect-json",
    "dynamic-json",
)


@dataclass(frozen=True)
class ExportResult:
    kind: str
    path: str
    size: int
    graph: Optional[GraphRenderResult] = None


class ExportService(object):
    def export(
        self,
        kind: str,
        target_path: str,
        source_text: str,
        model: Any,
        state_manager: Optional[Any] = None,
        inspect_report: Optional[Any] = None,
        dynamic_report_json: Optional[str] = None,
        overwrite: bool = False,
        cancel_token: Optional[Any] = None,
        plantuml_jar: Optional[str] = None,
    ) -> ExportResult:
        if kind not in EXPORT_KINDS:
            raise ValueError("unsupported export kind: " + str(kind))
        target = Path(target_path).resolve()
        if target.exists() and not overwrite:
            raise FileExistsError("export target already exists: " + str(target))
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix="." + target.name + ".", suffix=".tmp", dir=str(target.parent)
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            _raise_if_cancelled(cancel_token)
            graph_result = self._write(
                kind,
                temporary,
                source_text,
                model,
                state_manager,
                inspect_report,
                dynamic_report_json,
                plantuml_jar,
                cancel_token,
            )
            _validate_output(kind, temporary)
            _raise_if_cancelled(cancel_token)
            os.replace(str(temporary), str(target))
            if graph_result is not None:
                graph_result = replace(graph_result, path=str(target))
            return ExportResult(
                kind=kind,
                path=str(target),
                size=target.stat().st_size,
                graph=graph_result,
            )
        finally:
            try:
                temporary.unlink()
            except OSError:
                pass

    @staticmethod
    def _write(
        kind,
        temporary,
        source_text,
        model,
        state_manager,
        inspect_report,
        dynamic_report_json,
        plantuml_jar,
        cancel_token,
    ):
        if kind == "fcstm":
            temporary.write_text(source_text, encoding="utf-8")
        elif kind == "plantuml":
            temporary.write_text(
                normalize_plantuml_source(model.to_plantuml()), encoding="utf-8"
            )
        elif kind in ("png", "svg", "pdf"):
            return GraphRenderService().render(
                model.to_plantuml(),
                temporary,
                kind,
                plantuml_jar=plantuml_jar or _plantuml_jar_path(),
                overwrite=True,
                cancel_token=cancel_token,
            )
        elif kind == "docx":
            if state_manager is None:
                raise ValueError("Word export requires the current UI projection")
            export_statechart_to_word(state_manager, str(temporary))
        elif kind == "xlsx":
            if state_manager is None:
                raise ValueError("Excel export requires the current UI projection")
            export_statechart_to_excel(state_manager, str(temporary))
        elif kind == "inspect-json":
            if inspect_report is None:
                raise ValueError("inspect JSON export requires an inspect report")
            temporary.write_text(
                json.dumps(
                    _json_ready(inspect_report),
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        elif kind == "dynamic-json":
            if dynamic_report_json is None:
                raise ValueError("dynamic JSON export requires a completed report")
            json.loads(dynamic_report_json)
            temporary.write_text(dynamic_report_json, encoding="utf-8")
        return None


def _plantuml_jar_path():
    root = Path(
        getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])
    )
    candidate = root / "docs" / "plantuml.jar"
    return str(candidate)


def _validate_output(kind, path):
    data = path.read_bytes()
    if not data:
        raise ValueError("export output is empty")
    if kind == "png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("PNG export has invalid magic")
    if kind == "pdf" and not data.startswith(b"%PDF-"):
        raise ValueError("PDF export has invalid magic")
    if kind in ("docx", "xlsx") and not data.startswith(b"PK\x03\x04"):
        raise ValueError("Office export has invalid ZIP magic")
    if kind == "svg" and b"<svg" not in data[:4096].lower():
        raise ValueError("SVG export has invalid content")
    if kind == "plantuml":
        text = data.decode("utf-8")
        if "@startuml" not in text or "@enduml" not in text:
            raise ValueError("PlantUML export is incomplete")
    if kind == "fcstm":
        load_state_machine_from_text(data.decode("utf-8"))
    if kind.endswith("json"):
        payload = json.loads(data.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON export root must be an object")
        if kind == "dynamic-json" and not str(payload.get("schema", "")).startswith(
            "fcstm-gui.dynamic-validation"
        ):
            raise ValueError("dynamic report schema is invalid")


def _json_ready(value):
    if isinstance(value, (dict, MappingProxyType)):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_ready(item) for item in value]
    if hasattr(value, "to_json_dict"):
        return _json_ready(value.to_json_dict())
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "__dict__"):
        return _json_ready(vars(value))
    return str(value)


def _raise_if_cancelled(cancel_token):
    if cancel_token is None:
        return
    raiser = getattr(cancel_token, "raise_if_cancelled", None)
    if callable(raiser):
        raiser()
        return
    if bool(getattr(cancel_token, "cancelled", False)):
        raise RuntimeError("export cancelled")
