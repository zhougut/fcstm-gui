from __future__ import unicode_literals

from pathlib import Path

import pytest
from PyQt5 import QtCore, QtGui

import app.application.graph_render as graph_render
from app.application.document import DocumentService
from app.application.graph_render import (
    GraphRenderError,
    GraphRenderService,
    RendererExecution,
    _source_expectations,
    _validate_binary_output,
    normalize_plantuml_source,
    validate_svg_semantics,
)


SOURCE = """
state Root {
    state Idle;
    state Running;
    [*] -> Idle;
    Idle -> Running :: Start;
    Running -> [*] :: Stop;
}
"""


def _plantuml_source(tmp_path):
    source = tmp_path / "machine.fcstm"
    source.write_text(SOURCE, encoding="utf-8")
    return DocumentService().load(source).current_valid_snapshot.model.to_plantuml()


def test_normalize_plantuml_source_replaces_layout_and_injects_smetana_once():
    source = (
        "@startuml\r\n"
        "!pragma layout elk\r\n"
        "state \"Idle\" as idle\r\n"
        "@enduml\r\n"
    )

    normalized = normalize_plantuml_source(source)
    normalized_again = normalize_plantuml_source(normalized)

    assert normalized == normalized_again
    assert normalized.count("!pragma layout smetana") == 1
    assert "layout elk" not in normalized
    assert normalized.splitlines()[1] == "!pragma layout smetana"


@pytest.mark.parametrize(
    "source",
    (
        None,
        "state Root",
        "@startuml\n@startuml\n@enduml\n",
        "@startuml\nstate Root\n",
    ),
)
def test_normalize_rejects_non_text_or_incomplete_documents(source):
    with pytest.raises((TypeError, GraphRenderError)):
        normalize_plantuml_source(source)


def test_source_oracle_rejects_transition_to_undeclared_alias():
    with pytest.raises(GraphRenderError, match="undeclared state alias"):
        _source_expectations(
            '@startuml\nstate "Root" as root\nroot --> missing\n@enduml\n'
        )


def test_svg_semantic_oracle_rejects_renderer_diagnostics_and_missing_labels():
    diagnostic = b'''<svg xmlns="http://www.w3.org/2000/svg">
      <text>Cannot find Graphviz</text>
    </svg>'''
    with pytest.raises(GraphRenderError, match="renderer diagnostic"):
        validate_svg_semantics(diagnostic, ("Root",))

    incomplete = b'''<svg xmlns="http://www.w3.org/2000/svg">
      <g id="Root"><text>Root</text></g>
    </svg>'''
    with pytest.raises(GraphRenderError, match="Idle"):
        validate_svg_semantics(incomplete, ("Root", "Idle"))

    with pytest.raises(GraphRenderError, match="valid XML"):
        validate_svg_semantics(b"<svg", ())
    with pytest.raises(GraphRenderError, match="no svg root"):
        validate_svg_semantics(b"<html/>", ())


def _png(width, height, color=QtGui.QColor("white")):
    image = QtGui.QImage(width, height, QtGui.QImage.Format_ARGB32)
    image.fill(color)
    data = QtCore.QByteArray()
    buffer = QtCore.QBuffer(data)
    buffer.open(QtCore.QIODevice.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(data)


def test_binary_oracle_rejects_empty_bad_magic_dimensions_and_single_color():
    with pytest.raises(GraphRenderError, match="empty"):
        _validate_binary_output("png", b"")
    with pytest.raises(GraphRenderError, match="PNG.*magic"):
        _validate_binary_output("png", b"not-png")
    with pytest.raises(GraphRenderError, match="dimensions"):
        _validate_binary_output("png", _png(1, 1))
    with pytest.raises(GraphRenderError, match="single-color"):
        _validate_binary_output("png", _png(4, 4))
    with pytest.raises(GraphRenderError, match="PDF.*magic"):
        _validate_binary_output("pdf", b"not-pdf")
    with pytest.raises(GraphRenderError, match="no page dimensions"):
        _validate_binary_output("pdf", b"%PDF-1.5\n")
    with pytest.raises(GraphRenderError, match="invalid dimensions"):
        _validate_binary_output("pdf", b"%PDF-1.5\n/MediaBox [0 0 1 1]")
    with pytest.raises(GraphRenderError, match="unsupported"):
        _validate_binary_output("gif", b"GIF89a")


@pytest.mark.parametrize(
    ("kind", "magic"),
    (("svg", b"<svg"), ("png", b"\x89PNG\r\n\x1a\n"), ("pdf", b"%PDF-")),
)
def test_smetana_renders_real_model_without_graphviz(
    monkeypatch, tmp_path, kind, magic
):
    monkeypatch.setenv("GRAPHVIZ_DOT", "/definitely/missing/dot")
    plantuml = _plantuml_source(tmp_path)
    target = tmp_path / ("machine." + kind)

    result = GraphRenderService().render(
        plantuml,
        target,
        kind,
        plantuml_jar=str(Path("docs/plantuml.jar").resolve()),
    )

    data = target.read_bytes()
    assert magic in data[:4096]
    assert result.engine == "smetana"
    assert result.renderer in {"java-jar-pipe", "java-jar-pipe+cairosvg"}
    assert result.exit_code == 0
    assert result.stderr == ""
    assert result.executions
    assert all(item.exit_code == 0 for item in result.executions)
    assert all(item.engine == "smetana" for item in result.executions)
    assert all(item.stdout_sha256 for item in result.executions)
    assert result.format == kind
    assert result.size == len(data) > 0
    assert result.output_sha256
    assert result.semantic_svg_sha256
    assert result.source_sha256
    assert {"Root", "Idle", "Running", "Start", "Stop"} <= set(
        result.semantic_labels
    )
    assert result.transition_count >= 4
    assert any(
        item.source == "root__idle"
        and item.target == "root__running"
        and item.label == "Idle.Start"
        for item in result.semantic_transitions
    )


def test_java_pipe_uses_utf8_default_jar_and_stops_process_on_cancel(
    monkeypatch, tmp_path
):
    bundle = tmp_path / "bundle"
    jar = bundle / "docs" / "plantuml.jar"
    jar.parent.mkdir(parents=True)
    jar.write_bytes(b"jar")
    monkeypatch.setattr(graph_render.sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(graph_render.shutil, "which", lambda name: "/java")
    processes = []

    class FakeProcess(object):
        def __init__(self, command, **kwargs):
            self.command = command
            self.returncode = None
            self.terminated = False
            processes.append(self)

        def communicate(self, input=None, timeout=None):
            self.returncode = 0
            return b"<svg/>", b""

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(graph_render.subprocess, "Popen", FakeProcess)
    output = tmp_path / "output.svg"

    GraphRenderService._render_java_pipe(
        "@startuml\n@enduml\n", output, "svg", None
    )

    assert output.read_bytes() == b"<svg/>"
    assert "-charset" in processes[0].command
    assert processes[0].command[processes[0].command.index("-charset") + 1] == "UTF-8"
    assert str(jar.resolve()) in processes[0].command

    class CancelledToken(object):
        def raise_if_cancelled(self):
            raise RuntimeError("cancel now")

    with pytest.raises(RuntimeError, match="cancel now"):
        GraphRenderService._render_java_pipe(
            "@startuml\n@enduml\n",
            tmp_path / "cancelled.svg",
            "svg",
            str(jar),
            cancel_token=CancelledToken(),
        )
    assert processes[-1].terminated


def test_diagnostic_svg_is_never_published_over_existing_target(tmp_path):
    target = tmp_path / "machine.png"
    target.write_bytes(b"old-target")

    def diagnostic_renderer(_source, output, kind, _renderer, **_kwargs):
        output = Path(output)
        if kind == "svg":
            output.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg">'
                '<text>Cannot find Graphviz</text></svg>',
                encoding="utf-8",
            )
        else:
            output.write_bytes(b"should-not-run")
        return "local"

    with pytest.raises(GraphRenderError, match="renderer diagnostic"):
        GraphRenderService(renderer=diagnostic_renderer).render(
            "@startuml\nstate Root\n@enduml\n",
            target,
            "png",
            overwrite=True,
        )

    assert target.read_bytes() == b"old-target"


def test_render_rejects_unknown_format_existing_target_and_missing_output(tmp_path):
    service = GraphRenderService(renderer=lambda *args, **kwargs: None)
    with pytest.raises(GraphRenderError, match="unsupported"):
        service.render("@startuml\n@enduml\n", tmp_path / "x.gif", "gif")
    target = tmp_path / "x.svg"
    target.write_text("old", encoding="utf-8")
    with pytest.raises(FileExistsError):
        service.render("@startuml\n@enduml\n", target, "svg")
    target.unlink()
    with pytest.raises(GraphRenderError, match="produced no SVG"):
        service.render("@startuml\n@enduml\n", target, "svg")


def test_injected_renderer_execution_is_preserved(tmp_path):
    execution = RendererExecution(
        renderer="audited-test-renderer",
        engine="smetana",
        command=("renderer",),
        exit_code=0,
        stderr="",
        stdout_sha256="provided-sha",
    )

    def render(_source, output, _kind, _renderer, **_kwargs):
        Path(output).write_text(
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<g id="Root"><text>Root</text></g></svg>',
            encoding="utf-8",
        )
        return execution

    result = GraphRenderService(renderer=render).render(
        '@startuml\nstate "Root" as root\n@enduml\n',
        tmp_path / "x.svg",
        "svg",
    )
    assert result.executions == (execution,)
    assert result.renderer == "audited-test-renderer"


def test_java_pipe_reports_missing_runtime_jar_and_nonzero_exit(monkeypatch, tmp_path):
    monkeypatch.setattr(graph_render.shutil, "which", lambda _name: None)
    with pytest.raises(GraphRenderError, match="java executable"):
        GraphRenderService._render_java_pipe(
            "@startuml\n@enduml\n", tmp_path / "x.svg", "svg", "missing.jar"
        )

    monkeypatch.setattr(graph_render.shutil, "which", lambda _name: "/java")
    with pytest.raises(GraphRenderError, match="JAR is unavailable"):
        GraphRenderService._render_java_pipe(
            "@startuml\n@enduml\n", tmp_path / "x.svg", "svg", "missing.jar"
        )

    jar = tmp_path / "plantuml.jar"
    jar.write_bytes(b"jar")

    class CompletedProcess(object):
        def __init__(self, returncode, stdout, stderr):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

        def communicate(self, input=None, timeout=None):
            return self.stdout, self.stderr

        def poll(self):
            return self.returncode

    def process(returncode, stdout, stderr):
        return lambda *args, **kwargs: CompletedProcess(
            returncode, stdout, stderr
        )

    monkeypatch.setattr(
        graph_render.subprocess,
        "Popen",
        process(2, b"", b"render failed"),
    )
    with pytest.raises(GraphRenderError, match="exited 2: render failed"):
        GraphRenderService._render_java_pipe(
            "@startuml\n@enduml\n", tmp_path / "x.svg", "svg", str(jar)
        )

    monkeypatch.setattr(
        graph_render.subprocess,
        "Popen",
        process(0, b"<svg/>", b"renderer warning"),
    )
    with pytest.raises(GraphRenderError, match="renderer stderr"):
        GraphRenderService._render_java_pipe(
            "@startuml\n@enduml\n", tmp_path / "x.svg", "svg", str(jar)
        )


def test_renderer_stderr_allows_only_known_macos_software_gl_warning():
    graph_render._reject_unexpected_stderr(
        "WARNING: GL pipe is running in software mode (Renderer ID=0x1020400)"
    )

    with pytest.raises(GraphRenderError, match="renderer stderr"):
        graph_render._reject_unexpected_stderr("Cannot find Graphviz")
