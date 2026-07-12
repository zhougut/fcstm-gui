from types import SimpleNamespace

from app.widget.simulation_workspace import SimulationWorkspace


def _snapshot(cycle=0):
    return SimpleNamespace(
        state_path=("Root", "Idle"),
        cycle=cycle,
        ended=False,
        vars={"count": cycle},
    )


def test_pause_button_only_appears_for_pausable_run_and_emits(qtbot):
    panel = SimulationWorkspace()
    qtbot.addWidget(panel)
    panel.set_document_available(True, revision=3, fingerprint="abc")
    panel.set_initialized(_snapshot())

    panel.set_busy(True, "运行中", pausable=True)

    assert panel.pause_button.isEnabled()
    assert not panel.run_button.isEnabled()
    with qtbot.waitSignal(panel.pause_requested):
        panel.pause_button.click()
    panel.show_pause_requested()
    assert panel.status_label.text() == "正在暂停"
    assert not panel.pause_button.isEnabled()


def test_paused_state_offers_continue_and_cancel_uses_consistent_wording(qtbot):
    panel = SimulationWorkspace()
    qtbot.addWidget(panel)
    panel.set_document_available(True, revision=3, fingerprint="abc")
    panel.set_initialized(_snapshot())

    panel.show_paused()

    assert panel.status_label.text() == "已暂停"
    assert panel.run_button.text() == "继续运行"
    assert panel.run_button.isEnabled()

    panel.set_busy(True, "运行中", pausable=True)
    assert panel.run_button.text() == "连续运行"
    panel.show_cancelled()
    assert panel.status_label.text() == "已取消，已保留完成的周期"
    assert panel.run_button.text() == "连续运行"

    panel.show_error("boom")
    assert panel.status_label.text() == "失败：boom"


def test_initialize_cycle_and_reset_are_not_pausable(qtbot):
    panel = SimulationWorkspace()
    qtbot.addWidget(panel)
    panel.set_document_available(True, revision=3, fingerprint="abc")
    panel.set_initialized(_snapshot())

    panel.set_busy(True, "正在单步")

    assert not panel.pause_button.isEnabled()
    assert panel.cancel_button.isEnabled()


def test_simulation_controls_do_not_overlap(qtbot):
    panel = SimulationWorkspace()
    qtbot.addWidget(panel)
    panel.resize(1280, 720)
    panel.show()
    qtbot.wait(10)

    controls = (
        panel.initialize_button,
        panel.cycle_button,
        panel.run_button,
        panel.pause_button,
        panel.reset_button,
        panel.cancel_button,
    )
    for left, right in zip(controls, controls[1:]):
        intersection = left.geometry().intersected(right.geometry())
        assert intersection.width() <= 1 or intersection.height() <= 1, (
            left.objectName(),
            left.geometry(),
            right.objectName(),
            right.geometry(),
            intersection,
        )
