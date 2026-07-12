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
