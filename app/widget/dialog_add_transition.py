from PyQt5.Qt import QDialog
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt

from ..ui import UIDialogAddTransition
from ..model import StateManager, State
from .formula_editor import FormulaEditor
from ..application.formulas import FormulaKind
from app.utils.dsl_to_ui import extract_variable_definitions
from .state_selector import (
    populate_state_combo,
    select_transition_token,
    transition_token,
)

class DialogAddTransition(QDialog, UIDialogAddTransition):
    def __init__(self, parent, state_manager: StateManager, current_state: State,
                 is_edit: bool = False, transition_data: dict = None,
                 transition_index: int = -1, mutate_model: bool = True):
        QDialog.__init__(self, parent)
        self.setupUi(self)
        self.setMinimumSize(self.size())

        self.state_manager = state_manager
        self.current_state = current_state
        self.is_edit = is_edit
        self.transition_data = transition_data or {}
        self.transition_index = transition_index
        self.mutate_model = mutate_model

        self._init()

    def _init(self):
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._init_ui()
        self._init_button_accept()
        self._init_button_reject()

    def _init_ui(self):
        populate_state_combo(
            self.edit_source_state,
            self.state_manager,
            placeholder="请选择源状态",
            special_options=(("初始状态 [*]", "[*]"), ("任意状态 *", "*")),
        )
        populate_state_combo(
            self.edit_target_state,
            self.state_manager,
            placeholder="请选择目标状态",
            special_options=(("结束状态 [*]", "[*]"),),
        )
        self.check_force_transition = QtWidgets.QCheckBox("强制迁移", self.frame)
        self.check_force_transition.setObjectName("check_force_transition")
        self.check_force_transition.setToolTip("以 ! 标记强制迁移；初始状态不能使用此选项")
        self.gridLayout.addWidget(self.check_force_transition, 0, 2)
        self.edit_source_state.currentIndexChanged.connect(
            self._update_force_transition_state
        )
        self.condition_formula_editor = self._wrap_formula_field(
            self.edit_condition, FormulaKind.LOGICAL, 3, allow_empty=True
        )
        self.effect_formula_editor = self._wrap_formula_field(
            self.edit_op, FormulaKind.EFFECT, 4, allow_empty=True
        )
        # 为事件输入框添加占位符提示
        self.edit_event.setPlaceholderText("例如：Start、:: Start 或 : A.Start")
        self.edit_event.setToolTip(
            "事件示例：Start（当前作用域）、:: Start（状态机作用域）、: A.Start（指定状态）"
        )
        
        if self.is_edit:
            self.setWindowTitle("修改转移")
            self._populate_edit_data()
        else:
            self.setWindowTitle("添加转移")
        self._update_force_transition_state()

    def _update_force_transition_state(self):
        token = transition_token(self.edit_source_state)
        enabled = bool(token and token != "[*]")
        self.check_force_transition.setEnabled(enabled)
        if not enabled:
            self.check_force_transition.setChecked(False)

    def _wrap_formula_field(self, field, kind, row, allow_empty):
        self.gridLayout.removeWidget(field)
        editor = FormulaEditor(
            field,
            kind,
            revision_provider=self._source_revision,
            variable_definitions_provider=self._variable_definitions,
            allow_empty=allow_empty,
            enable_dialog=True,
            parent=self.frame,
        )
        self.gridLayout.addWidget(editor, row, 1)
        return editor

    def _source_revision(self):
        session = getattr(self.parent(), "document_session", None)
        return session.source_revision if session is not None else 0

    def _variable_definitions(self):
        session = getattr(self.parent(), "document_session", None)
        return (
            extract_variable_definitions(session.source_text)
            if session is not None
            else None
        )

    def _populate_edit_data(self):
        """填充编辑数据到界面控件"""
        if not self.transition_data:
            return
        
        # 设置源状态
        source_state = self.transition_data.get("source", "")
        forced = source_state.startswith("!")
        source_token = source_state.lstrip("!").strip() if forced else source_state
        select_transition_token(self.edit_source_state, source_token)
        self.check_force_transition.setChecked(forced)
        
        # 设置目标状态
        target_state = self.transition_data.get("target", "")
        select_transition_token(self.edit_target_state, target_state)
        
        # 设置事件
        event = self.transition_data.get("event", "")
        self.edit_event.setText(event)
        
        # 设置条件
        condition = self.transition_data.get("condition", "")
        self.edit_condition.setText(condition)
        
        # 设置操作
        action = self.transition_data.get("action", "")
        self.edit_op.setPlainText(action)

    def _init_button_accept(self):
        self.button_accept.clicked.connect(self._on_accept)

    def _init_button_reject(self):
        self.button_cancle.clicked.connect(self.reject)

    def _on_accept(self):
        try:
            if not self.condition_formula_editor.validate_now():
                QtWidgets.QMessageBox.warning(self, "条件无效", "请修正条件公式后再提交。")
                self.edit_condition.setFocus()
                return
            if not self.effect_formula_editor.validate_now():
                QtWidgets.QMessageBox.warning(self, "操作无效", "请修正迁移动作后再提交。")
                self.edit_op.setFocus()
                return
            # 获取用户输入
            source_state = self._source_state_token()
            target_state = transition_token(self.edit_target_state)
            event = self.edit_event.text().strip()
            condition = self.edit_condition.text().strip()
            action = self.edit_op.toPlainText().strip()

            # 验证输入
            if not source_state:
                QtWidgets.QMessageBox.warning(self, "错误", "源状态不能为空！")
                return

            if not target_state:
                QtWidgets.QMessageBox.warning(self, "错误", "目标状态不能为空！")
                return

            # 创建转移字典
            transition_item = {
                "source": source_state,
                "target": target_state,
                "event": event,
                "condition": condition,
                "action": action
            }

            if not self.mutate_model:
                self.accept()
                return
            if self.is_edit:
                # 编辑模式：更新现有的转移项
                if hasattr(self, 'transition_index') and 0 <= self.transition_index < len(self.current_state.transitions):
                    self.current_state.transitions[self.transition_index] = transition_item
                    QtWidgets.QMessageBox.information(self, "成功", "转移修改成功！")
                else:
                    QtWidgets.QMessageBox.warning(self, "错误", "无法找到要修改的转移！")
                    return
            else:
                # 添加模式：添加新的转移项
                if self.current_state.transitions is None:
                    self.current_state.transitions = []
                
                self.current_state.transitions.append(transition_item)
                QtWidgets.QMessageBox.information(self, "成功", "转移添加成功！")
            
            self.accept()

        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "添加失败",
                f"添加转移时发生错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )
            return

    def get_transition_data(self):
        """
        获取转移数据，供外部调用
        """
        return {
            "source": self._source_state_token(),
            "target": transition_token(self.edit_target_state),
            "event": self.edit_event.text().strip(),
            "condition": self.edit_condition.text().strip(),
            "action": self.edit_op.toPlainText().strip()
        }

    def _source_state_token(self):
        token = transition_token(self.edit_source_state)
        if token and token != "[*]" and self.check_force_transition.isChecked():
            return "! " + token
        return token
