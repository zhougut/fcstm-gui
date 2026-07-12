"""Graphviz-free PlantUML rendering with semantic publication guards."""

from __future__ import unicode_literals

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

import cairosvg
from PyQt5.QtGui import QImage


GRAPH_ENGINE = "smetana"
_LAYOUT_RE = re.compile(r"^\s*!pragma\s+layout\s+\S+\s*$", re.IGNORECASE)
_STATE_RE = re.compile(
    r'^\s*state\s+"([^"]+)"\s+as\s+([A-Za-z_][A-Za-z0-9_]*)',
    re.IGNORECASE,
)
_TRANSITION_RE = re.compile(
    r"^\s*(\[\*\]|[A-Za-z_][A-Za-z0-9_]*)\s+[-.]+>\s+"
    r"(\[\*\]|[A-Za-z_][A-Za-z0-9_]*)(?:\s*:\s*(.+?))?\s*$"
)
_DIAGNOSTIC_PHRASES = (
    "cannot find graphviz",
    "cannot find dot",
    "dot executable",
    "graphviz executable",
    "failed to execute dot",
    "java.lang.exception",
)


class GraphRenderError(ValueError):
    pass


@dataclass(frozen=True)
class GraphTransition:
    source: str
    target: str
    label: str


@dataclass(frozen=True)
class RendererExecution:
    renderer: str
    engine: str
    command: Tuple[str, ...]
    exit_code: int
    stderr: str
    stdout_sha256: str


@dataclass(frozen=True)
class GraphRenderResult:
    path: str
    format: str
    engine: str
    renderer: str
    exit_code: int
    stderr: str
    executions: Tuple[RendererExecution, ...]
    size: int
    input_sha256: str
    source_sha256: str
    semantic_svg_sha256: str
    output_sha256: str
    semantic_labels: Tuple[str, ...]
    semantic_transitions: Tuple[GraphTransition, ...]
    transition_count: int


def normalize_plantuml_source(source: str) -> str:
    if not isinstance(source, str):
        raise TypeError("PlantUML source must be text")
    lines = source.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    start_indexes = [
        index for index, line in enumerate(lines) if line.strip().lower() == "@startuml"
    ]
    if len(start_indexes) != 1 or not any(
        line.strip().lower() == "@enduml" for line in lines
    ):
        raise GraphRenderError("PlantUML source must contain one @startuml and @enduml")
    lines = [line for line in lines if not _LAYOUT_RE.match(line)]
    start = next(
        index for index, line in enumerate(lines) if line.strip().lower() == "@startuml"
    )
    lines.insert(start + 1, "!pragma layout " + GRAPH_ENGINE)
    return "\n".join(lines) + "\n"


def _source_expectations(
    source: str,
) -> Tuple[Tuple[str, ...], Tuple[GraphTransition, ...]]:
    labels = []
    aliases = set()
    transitions = []
    for line in source.splitlines():
        state = _STATE_RE.match(line)
        if state:
            labels.append(state.group(1))
            aliases.add(state.group(2))
        transition = _TRANSITION_RE.match(line)
        if transition:
            label = (transition.group(3) or "").strip()
            if label:
                labels.append(label)
            transitions.append(
                GraphTransition(
                    source=transition.group(1),
                    target=transition.group(2),
                    label=label,
                )
            )
    for transition in transitions:
        for endpoint in (transition.source, transition.target):
            if endpoint != "[*]" and endpoint not in aliases:
                raise GraphRenderError(
                    "PlantUML transition references undeclared state alias: "
                    + endpoint
                )
    return tuple(dict.fromkeys(labels)), tuple(transitions)


def validate_svg_semantics(
    data: bytes,
    expected_labels: Tuple[str, ...],
) -> Tuple[str, ...]:
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, ValueError) as error:
        raise GraphRenderError("SVG output is not valid XML: {}".format(error))
    if not root.tag.lower().endswith("svg"):
        raise GraphRenderError("SVG output has no svg root")
    text_values = []
    for element in root.iter():
        if element.tag.lower().endswith("text"):
            value = "".join(element.itertext()).strip()
            if value:
                text_values.append(value)
    searchable = "\n".join(text_values).casefold()
    for phrase in _DIAGNOSTIC_PHRASES:
        if phrase in searchable:
            raise GraphRenderError("SVG contains renderer diagnostic: " + phrase)
    for label in expected_labels:
        if label.casefold() not in searchable:
            raise GraphRenderError("SVG omitted expected semantic label: " + label)
    labels = list(dict.fromkeys(text_values))
    for value in tuple(labels):
        suffix = value.rsplit(".", 1)[-1]
        if suffix != value and suffix not in labels:
            labels.append(suffix)
    return tuple(labels)


def _validate_binary_output(kind: str, data: bytes) -> None:
    if not data:
        raise GraphRenderError(kind.upper() + " graph output is empty")
    if kind == "png":
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise GraphRenderError("PNG graph output has invalid magic")
        image = QImage.fromData(data, "PNG")
        if image.isNull() or image.width() < 2 or image.height() < 2:
            raise GraphRenderError("PNG graph output has invalid dimensions")
        sample = image.scaled(32, 32)
        colors = {
            sample.pixel(x, y)
            for x in range(sample.width())
            for y in range(sample.height())
        }
        if len(colors) < 2:
            raise GraphRenderError("PNG graph output is single-color")
    elif kind == "pdf":
        if not data.startswith(b"%PDF-"):
            raise GraphRenderError("PDF graph output has invalid magic")
        media_box = re.search(
            rb"/MediaBox\s*\[\s*[-+0-9.]+\s+[-+0-9.]+\s+"
            rb"([-+0-9.]+)\s+([-+0-9.]+)\s*\]",
            data,
        )
        if media_box is None:
            raise GraphRenderError("PDF graph output has no page dimensions")
        if float(media_box.group(1)) <= 1 or float(media_box.group(2)) <= 1:
            raise GraphRenderError("PDF graph output has invalid dimensions")
    elif kind != "svg":
        raise GraphRenderError("unsupported graph format: " + str(kind))


class GraphRenderService(object):
    def __init__(self, renderer: Optional[Callable] = None):
        self._renderer = renderer

    def render(
        self,
        source: str,
        target_path,
        format_name: str,
        plantuml_jar: Optional[str] = None,
        overwrite: bool = False,
        cancel_token: Optional[object] = None,
    ) -> GraphRenderResult:
        format_name = str(format_name).lower()
        if format_name not in {"svg", "png", "pdf"}:
            raise GraphRenderError("unsupported graph format: " + format_name)
        target = Path(target_path).resolve()
        if target.exists() and not overwrite:
            raise FileExistsError("graph target already exists: " + str(target))
        target.parent.mkdir(parents=True, exist_ok=True)
        normalized = normalize_plantuml_source(source)
        expected_labels, semantic_transitions = _source_expectations(normalized)
        staging_dir = Path(
            tempfile.mkdtemp(prefix="." + target.name + ".", dir=str(target.parent))
        )
        semantic_path = staging_dir / "semantic.svg"
        output_path = staging_dir / ("output." + format_name)
        try:
            executions = [
                self._render(
                    normalized,
                    semantic_path,
                    "svg",
                    plantuml_jar,
                    cancel_token,
                )
            ]
            semantic_data = semantic_path.read_bytes()
            semantic_labels = validate_svg_semantics(
                semantic_data, expected_labels
            )
            if format_name == "svg":
                shutil.copyfile(str(semantic_path), str(output_path))
            elif format_name == "pdf" and self._renderer is None:
                _raise_if_cancelled(cancel_token)
                pdf_data = cairosvg.svg2pdf(bytestring=semantic_data)
                _raise_if_cancelled(cancel_token)
                output_path.write_bytes(pdf_data)
                executions.append(
                    RendererExecution(
                        renderer="cairosvg",
                        engine=GRAPH_ENGINE,
                        command=("cairosvg.svg2pdf",),
                        exit_code=0,
                        stderr="",
                        stdout_sha256=_sha256(pdf_data),
                    )
                )
            else:
                executions.append(
                    self._render(
                        normalized,
                        output_path,
                        format_name,
                        plantuml_jar,
                        cancel_token,
                    )
                )
            output_data = output_path.read_bytes()
            _validate_binary_output(format_name, output_data)
            _raise_if_cancelled(cancel_token)
            os.replace(str(output_path), str(target))
            renderer_names = tuple(
                dict.fromkeys(item.renderer for item in executions)
            )
            return GraphRenderResult(
                path=str(target),
                format=format_name,
                engine=GRAPH_ENGINE,
                renderer="+".join(renderer_names),
                exit_code=max(item.exit_code for item in executions),
                stderr="\n".join(
                    item.stderr for item in executions if item.stderr
                ),
                executions=tuple(executions),
                size=target.stat().st_size,
                input_sha256=_sha256(source.encode("utf-8")),
                source_sha256=_sha256(normalized.encode("utf-8")),
                semantic_svg_sha256=_sha256(semantic_data),
                output_sha256=_sha256(target.read_bytes()),
                semantic_labels=semantic_labels,
                semantic_transitions=semantic_transitions,
                transition_count=len(semantic_transitions),
            )
        finally:
            shutil.rmtree(str(staging_dir), ignore_errors=True)

    def _render(self, source, path, format_name, plantuml_jar, cancel_token):
        _raise_if_cancelled(cancel_token)
        if self._renderer is None:
            execution = self._render_java_pipe(
                source, path, format_name, plantuml_jar, cancel_token
            )
        else:
            returned = self._renderer(
                source,
                path,
                format_name,
                "local",
                plantuml_jar=plantuml_jar,
            )
            execution = (
                returned
                if isinstance(returned, RendererExecution)
                else RendererExecution(
                    renderer="injected-renderer",
                    engine=GRAPH_ENGINE,
                    command=(),
                    exit_code=0,
                    stderr="",
                    stdout_sha256=(
                        _sha256(path.read_bytes()) if path.is_file() else ""
                    ),
                )
            )
        _raise_if_cancelled(cancel_token)
        if not path.is_file():
            raise GraphRenderError(
                "renderer produced no {} output".format(format_name.upper())
            )
        return execution

    @staticmethod
    def _render_java_pipe(
        source, path, format_name, plantuml_jar, cancel_token=None
    ):
        java = shutil.which("java")
        jar = Path(plantuml_jar or _default_plantuml_jar_path())
        if not java:
            raise GraphRenderError("java executable is unavailable")
        if not jar.is_file():
            raise GraphRenderError("PlantUML JAR is unavailable: " + str(jar))
        command = (
            java,
            "-jar",
            str(jar.resolve()),
            "-charset",
            "UTF-8",
            "-pipe",
            "-t" + format_name,
        )
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        input_data = source.encode("utf-8")
        started = True
        deadline = time.monotonic() + 60
        while True:
            try:
                _raise_if_cancelled(cancel_token)
            except BaseException:
                _stop_process(process)
                raise
            try:
                stdout, stderr_data = process.communicate(
                    input=input_data if started else None,
                    timeout=0.1,
                )
                break
            except subprocess.TimeoutExpired:
                started = False
                if time.monotonic() >= deadline:
                    _stop_process(process)
                    raise GraphRenderError("PlantUML renderer timed out after 60s")
        stderr = stderr_data.decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            raise GraphRenderError(
                "PlantUML renderer exited {}: {}".format(
                    process.returncode, stderr or "no stderr"
                )
            )
        if stderr:
            raise GraphRenderError("PlantUML renderer stderr: " + stderr)
        path.write_bytes(stdout)
        return RendererExecution(
            renderer="java-jar-pipe",
            engine=GRAPH_ENGINE,
            command=command,
            exit_code=process.returncode,
            stderr=stderr,
            stdout_sha256=_sha256(stdout),
        )


def _default_plantuml_jar_path():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return str(root / "docs" / "plantuml.jar")


def _raise_if_cancelled(cancel_token):
    if cancel_token is None:
        return
    raiser = getattr(cancel_token, "raise_if_cancelled", None)
    if callable(raiser):
        raiser()
        return
    if bool(getattr(cancel_token, "cancelled", False)):
        raise RuntimeError("graph render cancelled")


def _stop_process(process):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


__all__ = [
    "GRAPH_ENGINE",
    "GraphRenderError",
    "GraphRenderResult",
    "GraphRenderService",
    "GraphTransition",
    "RendererExecution",
    "normalize_plantuml_source",
    "validate_svg_semantics",
]
