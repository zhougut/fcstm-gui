from PyQt5 import QtCore, QtGui, QtWidgets

from app.widget import AppMainWindow
from app.widget import main_window as main_window_module


SOURCE = """def int count = 1;
state Root {
    state Idle;
    [*] -> Idle;
}
"""


def _window(qtbot, tmp_path):
    path = tmp_path / "m7.fcstm"
    path.write_text(SOURCE, encoding="utf-8")
    settings = QtCore.QSettings(
        str(tmp_path / "m7-settings.ini"), QtCore.QSettings.IniFormat
    )
    window = AppMainWindow(settings=settings)
    qtbot.addWidget(window)
    window._set_active_document_session(window.document_service.load(path))
    return window


def test_numeric_formula_menu_edits_selected_source_expression(
    monkeypatch, qtbot, tmp_path
):
    window = _window(qtbot, tmp_path)
    cursor = window.source_editor.document().find("1")
    assert cursor.hasSelection()
    window.source_editor.setTextCursor(cursor)

    class AcceptedNumericDialog(object):
        def __init__(self, *args, **kwargs):
            assert kwargs["initial_text"] == "1"

        def exec_(self):
            return QtWidgets.QDialog.Accepted

        def formula_text(self):
            return "2 + 3"

    monkeypatch.setattr(
        main_window_module, "DialogNumericFormula", AcceptedNumericDialog
    )

    with qtbot.waitSignal(window.document_validation_finished, timeout=3000):
        window.action_edit_numeric_formula.trigger()

    assert "def int count = 2 + 3;" in window.document_session.source_text
    assert window.document_session.current_valid_snapshot is not None
    assert window.document_session.dirty


def test_numeric_formula_menu_explains_missing_numeric_selection(
    monkeypatch, qtbot, tmp_path
):
    window = _window(qtbot, tmp_path)
    cursor = QtGui.QTextCursor(window.source_editor.document())
    cursor.movePosition(QtGui.QTextCursor.End)
    window.source_editor.setTextCursor(cursor)
    messages = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "information",
        lambda *args, **kwargs: messages.append(args),
    )

    assert window._edit_numeric_formula() is False
    assert messages
    assert "选中数值表达式" in messages[0][2]


def test_graph_toolbar_focusable_controls_do_not_overlap(qtbot, tmp_path):
    window = _window(qtbot, tmp_path)
    window.resize(1280, 720)
    window.show()
    window.workspace_tabs.setCurrentWidget(window.graph_workspace)
    qtbot.wait(10)

    controls = [
        window.graph_panel.export_combo,
        window.graph_panel.export_button,
        window.graph_panel.cancel_button,
    ]
    assert all(control.isVisibleTo(window) for control in controls)
    for left, right in zip(controls, controls[1:]):
        intersection = left.geometry().intersected(right.geometry())
        assert intersection.width() <= 1 or intersection.height() <= 1, (
            left.objectName(),
            left.geometry(),
            right.objectName(),
            right.geometry(),
            intersection,
        )


def test_property_inspector_renders_redaction_marker_as_plain_text(qtbot, tmp_path):
    window = _window(qtbot, tmp_path)
    root = window.state_manager.root_state

    window._update_property_inspector(root)

    assert window.property_source_label.textFormat() == QtCore.Qt.PlainText
    assert any(
        marker in window.property_source_label.text()
        for marker in ("<TEMP>", "<HOME>")
    )
    assert str(tmp_path) not in window.property_source_label.text()


def test_graph_stale_state_is_not_presented_as_failure(qtbot, tmp_path):
    window = _window(qtbot, tmp_path)

    window.graph_panel.show_stale("结果已过期，请刷新当前版本")

    assert window.graph_panel.status_label.text().startswith("已失效：")
    assert not window.graph_panel.status_label.text().startswith("失败：")
