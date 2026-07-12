from __future__ import unicode_literals

import json
import time

import pytest
from PyQt5 import QtCore, QtWidgets

from app.application.tasks import TaskStatus as HistoryTaskStatus
from app.widget import AppMainWindow


SOURCE = """
def int x = 2;
def int y = 0;
state Root {
    state A { during { x = x + 1; } }
    state B { during { y = y + 10; } }
    [*] -> A;
    A -> B :: Go effect { x = x + 5; }
    B -> [*] :: Stop;
}
"""


@pytest.fixture
def simulation_window(qtbot, tmp_path):
    source = tmp_path / "simulation.fcstm"
    source.write_text(SOURCE, encoding="utf-8")
    settings = QtCore.QSettings(
        str(tmp_path / "settings.ini"), QtCore.QSettings.IniFormat
    )
    window = AppMainWindow(settings=settings)
    qtbot.addWidget(window)
    window._set_active_document_session(window.document_service.load(source))
    return window


def test_ordinary_simulation_real_initialize_cycle_reset_and_task_history(
    qtbot, simulation_window
):
    window = simulation_window
    panel = window.simulation_panel
    assert panel.initialize_button.isEnabled()
    assert panel.transcript_table.columnCount() == 7
    assert all(
        panel.transcript_table.horizontalHeaderItem(column).text()
        for column in range(panel.transcript_table.columnCount())
    )

    with qtbot.waitSignal(window.simulation_task_finished, timeout=3000):
        panel.initialize_button.click()
    runtime = window._simulation_session.runtime
    assert panel.status_label.text() == "就绪"
    assert "版本 0" in panel.stamp_label.text()
    assert panel.transcript_table.rowCount() == 1
    assert panel.transcript_table.item(0, 1).text() == "Root.A"
    assert json.loads(panel.transcript_table.item(0, 5).text()) == {"x": 3, "y": 0}

    with qtbot.waitSignal(window.simulation_task_finished, timeout=3000):
        panel.cycle_button.click()
    assert panel.transcript_table.rowCount() == 2
    assert panel.transcript_table.item(1, 1).text() == "Root.A"
    assert json.loads(panel.transcript_table.item(1, 5).text()) == {"x": 4, "y": 0}

    panel.event_edit.setText("Go, Root.B.Stop")
    with qtbot.waitSignal(window.simulation_task_finished, timeout=3000):
        panel.cycle_button.click()
    assert panel.transcript_table.item(2, 3).text() == "Root.A.Go"
    assert panel.transcript_table.item(2, 4).text() == "Root.B.Stop"
    assert panel.transcript_table.item(2, 1).text() == "Root.B"
    assert json.loads(panel.transcript_table.item(2, 5).text()) == {"x": 9, "y": 10}

    with qtbot.waitSignal(window.simulation_task_finished, timeout=3000):
        panel.reset_button.click()
    assert window._simulation_session.runtime is not runtime
    assert "cycle: 1" in panel.snapshot_label.text()
    records = [
        item for item in window.task_center.records if item.kind == "ordinary-simulation"
    ]
    assert len(records) == 4
    assert all(item.status is HistoryTaskStatus.SUCCESS for item in records)


def test_simulation_is_invalidated_immediately_when_source_revision_changes(
    qtbot, simulation_window
):
    window = simulation_window
    with qtbot.waitSignal(window.simulation_task_finished, timeout=3000):
        window.simulation_panel.initialize_button.click()

    window.source_editor.insertPlainText("\n")

    assert window._simulation_session is None
    assert "已失效" in window.simulation_panel.status_label.text()
    assert not window.simulation_panel.cycle_button.isEnabled()


def test_continuous_simulation_pauses_at_boundary_and_continues_same_runtime(
    monkeypatch, qtbot, simulation_window
):
    window = simulation_window
    panel = window.simulation_panel
    with qtbot.waitSignal(window.simulation_task_finished, timeout=3000):
        panel.initialize_button.click()
    runtime = window._simulation_session.runtime
    original_cycle = window.simulation_service.cycle

    def slow_cycle(*args, **kwargs):
        result = original_cycle(*args, **kwargs)
        time.sleep(0.01)
        return result

    monkeypatch.setattr(window.simulation_service, "cycle", slow_cycle)
    panel.cycle_count.setValue(100)
    handle = window._run_simulation(
        {"max_cycles": panel.cycle_count.value(), "events": ()}
    )
    assert handle is not None
    qtbot.waitUntil(lambda: runtime.cycle_count >= 3, timeout=3000)
    with qtbot.waitSignal(window.simulation_task_finished, timeout=3000):
        panel.pause_button.click()

    paused_cycle = runtime.cycle_count
    assert panel.status_label.text() == "已暂停"
    assert panel.run_button.text() == "继续运行"
    assert window._simulation_session.runtime is runtime
    paused_record = [
        item
        for item in window.task_center.records
        if item.kind == "ordinary-simulation"
    ][-1]
    assert paused_record.status is HistoryTaskStatus.SUCCESS
    assert "已暂停" in paused_record.summary

    panel.cycle_count.setValue(2)
    with qtbot.waitSignal(window.simulation_task_finished, timeout=3000):
        panel.run_button.click()

    assert window._simulation_session.runtime is runtime
    assert runtime.cycle_count == paused_cycle + 2
    assert panel.status_label.text() == "就绪"


def test_dynamic_validation_runs_frozen_suite_and_exports_versioned_report(
    monkeypatch, qtbot, simulation_window, tmp_path
):
    window = simulation_window
    panel = window.dynamic_validation_panel
    assert panel.case_combo.count() == 4
    assert panel.run_suite_button.isEnabled()

    with qtbot.waitSignal(window.dynamic_validation_finished, timeout=10000):
        panel.run_suite_button.click()

    assert panel.status_label.text() == "通过"
    assert panel.result_table.rowCount() >= 4
    statuses = {
        panel.result_table.item(row, 2).text()
        for row in range(panel.result_table.rowCount())
    }
    assert statuses <= {"通过", "预期异常通过"}
    payload = json.loads(panel.report_json())
    assert payload["schema"] == "fcstm-gui.dynamic-validation-result-bundle"
    assert payload["provenance"]["status"] == "passed"
    assert len(payload["provenance"]["resources"]) == 8
    assert payload["report"]["status"] == "passed"
    assert len(payload["report"]["cases"]) == 4

    target = tmp_path / "reports" / "dynamic.json"
    target.parent.mkdir()
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(target), "JSON 报告 (*.json)"),
    )
    with qtbot.waitSignal(window.dynamic_validation_finished, timeout=3000):
        panel.export_button.click()

    assert json.loads(target.read_text(encoding="utf-8")) == payload
    export_record = [
        item
        for item in window.task_center.records
        if item.kind == "dynamic-validation" and item.artifacts
    ][-1]
    assert export_record.status is HistoryTaskStatus.SUCCESS
    assert export_record.artifacts[0].path == str(target)


def test_dynamic_user_scenario_uses_real_model_and_expected_actual_diff(
    qtbot, simulation_window, tmp_path
):
    window = simulation_window
    model = tmp_path / "user.fcstm"
    model.write_text(SOURCE, encoding="utf-8")
    scenario = tmp_path / "user.json"
    scenario.write_text(
        json.dumps(
            {
                "schema": "fcstm-gui.dynamic-validation-scenario",
                "version": 1,
                "case_id": "gui_user_case",
                "model_file": model.name,
                "initial": {"state": None, "variables": {}},
                "steps": [
                    {
                        "events": [],
                        "commands": [],
                        "expected": {"state": "Root.Wrong", "variables": {"x": 3}},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    panel = window.dynamic_validation_panel
    panel.scenario_edit.setText(str(scenario))
    panel._update_actions()

    with qtbot.waitSignal(window.dynamic_validation_finished, timeout=3000):
        panel.run_user_button.click()

    assert panel.status_label.text() == "不匹配"
    assert panel.result_table.item(0, 0).text() == "gui_user_case"
    assert json.loads(panel.result_table.item(0, 6).text()) == [
        {"actual": "Root.A", "expected": "Root.Wrong", "path": "state"}
    ]
    record = [
        item for item in window.task_center.records if item.kind == "dynamic-validation"
    ][-1]
    assert record.status is HistoryTaskStatus.FAILED
    assert record.messages[0]["step"] == 0


def test_simulation_and_dynamic_controls_have_accessible_names(simulation_window):
    window = simulation_window
    for panel in (window.simulation_panel, window.dynamic_validation_panel):
        for button in panel.findChildren(QtWidgets.QPushButton):
            assert button.accessibleName()
            assert button.toolTip()
        for table in panel.findChildren(QtWidgets.QTableWidget):
            assert all(
                table.horizontalHeaderItem(column).text()
                for column in range(table.columnCount())
            )
