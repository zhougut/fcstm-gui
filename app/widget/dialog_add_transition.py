from PyQt5.Qt import QDialog
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt

from ..ui import UIDialogAddTransition
from ..model import StateManager, State
from .formula_editor import FormulaEditor
from ..application.formulas import FormulaKind
from app.utils.dsl_to_ui import extract_variable_definitions

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
        self.condition_formula_editor = self._wrap_formula_field(
            self.edit_condition, FormulaKind.LOGICAL, 3, allow_empty=True
        )
        self.effect_formula_editor = self._wrap_formula_field(
            self.edit_op, FormulaKind.EFFECT, 4, allow_empty=True
        )
        # 为事件输入框添加占位符提示
        self.edit_event.setPlaceholderText("例如: event_name 或 :: event_name 或 : A.event_name")
        
        if self.is_edit:
            self.setWindowTitle("修改转移")
            self._populate_edit_data()
        else:
            self.setWindowTitle("添加转移")

    def _wrap_formula_field(self, field, kind, row, allow_empty):
        self.gridLayout.removeWidget(field)
        editor = FormulaEditor(
            field,
            kind,
            revision_provider=self._source_revision,
            variable_definitions_provider=self._variable_definitions,
            allow_empty=allow_empty,
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
        self.edit_source_state.setText(source_state)
        
        # 设置目标状态
        target_state = self.transition_data.get("target", "")
        self.edit_target_state.setText(target_state)
        
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
            source_state = self.edit_source_state.text().strip()
            target_state = self.edit_target_state.text().strip()
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

            # 验证源状态是否存在（如果不是特殊标记）
            # 处理强制转移：去掉!和空格进行验证
            source_state_for_check = source_state.lstrip('!').strip()
            if source_state_for_check != "[*]" and source_state_for_check != "*":
                # 构建完整路径：当前状态路径 + 输入的状态名称
                if self.current_state:
                    source_full_path = f"{self.current_state.get_full_path()}.{source_state_for_check}"
                else:
                    source_full_path = source_state_for_check
                
                if not self.state_manager.get_state_by_path(source_full_path):
                    reply = QtWidgets.QMessageBox.question(
                        self, 
                        "状态不存在", 
                        f"源状态 '{source_state_for_check}' 不存在，是否继续添加？",
                        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
                    )
                    if reply != QtWidgets.QMessageBox.Yes:
                        return

            # 验证目标状态是否存在（如果不是特殊标记）
            if target_state != "[*]" and target_state != "*":
                # 构建完整路径：当前状态路径 + 输入的状态名称
                if self.current_state:
                    target_full_path = f"{self.current_state.get_full_path()}.{target_state}"
                else:
                    target_full_path = target_state
                
                if not self.state_manager.get_state_by_path(target_full_path):
                    reply = QtWidgets.QMessageBox.question(
                        self, 
                        "状态不存在", 
                        f"目标状态 '{target_state}' 不存在，是否继续添加？",
                        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
                    )
                    if reply != QtWidgets.QMessageBox.Yes:
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
            "source": self.edit_source_state.text().strip(),
            "target": self.edit_target_state.text().strip(),
            "event": self.edit_event.text().strip(),
            "condition": self.edit_condition.text().strip(),
            "action": self.edit_op.toPlainText().strip()
        }
