from app.widget.dynamic_validation_workspace import DynamicValidationWorkspace


def test_dynamic_validation_scope_is_visible_and_accessible(qtbot):
    panel = DynamicValidationWorkspace(("case-a",))
    qtbot.addWidget(panel)
    panel.show()

    assert panel.scope_notice.isVisibleTo(panel)
    assert "不是形式化验证" in panel.scope_notice.text()
    assert "expected/actual" in panel.scope_notice.text()
    assert panel.scope_notice.accessibleName()


def test_dynamic_validation_terminal_states_use_localized_user_text(qtbot):
    panel = DynamicValidationWorkspace(("case-a",))
    qtbot.addWidget(panel)

    panel.show_cancelled()
    assert panel.status_label.text() == "已取消，已保留完成的步骤"

    panel.show_error("boom")
    assert panel.status_label.text() == "失败：boom"


def test_dynamic_validation_invalidates_report_when_document_stamp_changes(qtbot):
    panel = DynamicValidationWorkspace(("case-a",))
    qtbot.addWidget(panel)
    panel.set_document_available(True, revision=1, fingerprint="deps-1")
    panel._report = object()
    panel._report_payload = {"status": "passed"}
    panel.result_table.setRowCount(1)
    panel.details_edit.setPlainText("old report")

    panel.set_document_available(True, revision=2, fingerprint="deps-2")

    assert panel.report is None
    assert panel.report_json() is None
    assert panel.result_table.rowCount() == 0
    assert not panel.details_edit.toPlainText()
    assert panel.status_label.text() == "模型版本已变化，请重新运行动态验证"
    assert not panel.export_button.isEnabled()
