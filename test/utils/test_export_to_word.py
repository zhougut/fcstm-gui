from docx import Document

from app.model import State, StateManager
from app.utils.export_to_word import export_statechart_to_word


def test_export_to_word_uses_structured_state_data(tmp_path):
    root = State(
        "TrafficLight",
        transitions=[
            {"source": "[*]", "target": "Idle", "event": "", "condition": "", "action": ""},
            {"source": "! *", "target": "Idle", "event": "", "condition": "a > 10", "action": ""},
        ],
    )
    idle = State(
        "Idle",
        lifecycle=[{
            "type": "enter",
            "name": "",
            "action": "a = 1",
            "is_abstract": False,
            "comment": "",
        }],
    )
    manager = StateManager(root)
    manager.add_state(root, idle)
    manager.variable_definitions = "def int a = 0;"
    output_path = tmp_path / "traffic-light.docx"

    export_statechart_to_word(manager, str(output_path))

    document = Document(str(output_path))
    summary = document.tables[0]
    assert summary.cell(2, 1).text == "2"
    assert summary.cell(3, 1).text == "2"

    state_tables = {
        table.cell(0, 1).text: table
        for table in document.tables[1:]
    }
    assert state_tables["TrafficLight"].cell(1, 1).text == "无"
    assert state_tables["Idle"].cell(1, 1).text == "TrafficLight"
    transitions = state_tables["TrafficLight"].cell(7, 1).text
    assert "[*] -> Idle;" in transitions
    assert "! * -> Idle : if [a > 10];" in transitions
