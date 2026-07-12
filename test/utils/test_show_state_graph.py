from pathlib import Path

from app.application.document import DocumentService
from app.utils.show_state_graph import ShowStateGraph


def test_show_state_graph_uses_smetana_service_without_graphviz(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("GRAPHVIZ_DOT", "/definitely/missing/dot")
    source = tmp_path / "model.fcstm"
    source.write_text(
        "state Root { state Idle; state Running; [*] -> Idle; "
        "Idle -> Running :: Start; Running -> [*]; }",
        encoding="utf-8",
    )
    model = DocumentService().load(source).current_valid_snapshot.model
    target = tmp_path / "graph.png"

    result = ShowStateGraph.show_state_graph(None, str(target), model=model)

    assert Path(result.path) == target.resolve()
    assert result.engine == "smetana"
    assert target.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert {"Root", "Idle", "Running", "Start"} <= set(result.semantic_labels)
