from PyQt5.Qt import QDialog
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt

from ..ui import UIDialogAddLifecycle
from ..model import StateManager, State
from .formula_editor import FormulaEditor
from ..application.formulas import FormulaKind
from app.utils.dsl_to_ui import extract_variable_definitions
from .state_selector import populate_state_combo, selected_state

class DialogAddLifecycle(QDialog, UIDialogAddLifecycle):
    def __init__(self, parent, state_manager: StateManager, current_state: State,
                 is_edit: bool = False, lifecycle_data: dict = None,
                 lifecycle_index: int = -1, mutate_model: bool = True):
        QDialog.__init__(self, parent)
        self.setupUi(self)
        self.setMinimumSize(self.size())

        self.state_manager = state_manager
        self.current_state = current_state
        self.is_edit = is_edit
        self.lifecycle_data = lifecycle_data or {}
        self.lifecycle_index = lifecycle_index
        self.mutate_model = mutate_model

        self._init()

    def _init(self):
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._init_ui()
        self._init_button_accept()
        self._init_button_reject()
        self._init_abstract_logic()

    def _init_ui(self):
        populate_state_combo(
            self.combo_owner_state,
            self.state_manager,
            selected_state=self.current_state,
        )
        if self.is_edit:
            self.combo_owner_state.setEnabled(False)
            self.combo_owner_state.setToolTip("修改操作时保持所属状态不变")
        self.lifecycle_formula_editor = self._wrap_formula_field(self.edit_op)
        if self.is_edit:
            self.setWindowTitle("修改生命周期操作")
            self._populate_edit_data()
        else:
            self.setWindowTitle("添加生命周期操作")

    def _wrap_formula_field(self, field):
        self.gridLayout.removeWidget(field)
        editor = FormulaEditor(
            field,
            FormulaKind.LIFECYCLE,
            revision_provider=self._source_revision,
            variable_definitions_provider=self._variable_definitions,
            enable_dialog=True,
            parent=self.frame,
        )
        self.gridLayout.addWidget(editor, 4, 1)
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
        if not self.lifecycle_data:
            return
        
        # 设置类型
        lifecycle_type = self.lifecycle_data.get("type", "")
        index = self.combo_type.findText(lifecycle_type)
        if index >= 0:
            self.combo_type.setCurrentIndex(index)
        
        # 设置名称
        lifecycle_name = self.lifecycle_data.get("name", "")
        self.edit_name.setText(lifecycle_name)
        
        # 设置是否抽象
        is_abstract = self.lifecycle_data.get("is_abstract", False)
        abstract_text = "是" if is_abstract else "否"
        index = self.combo_abstract.findText(abstract_text)
        if index >= 0:
            self.combo_abstract.setCurrentIndex(index)
        
        # 设置操作内容
        action = self.lifecycle_data.get("action", "")
        self.edit_op.setPlainText(action)
        
        # 设置注释
        comment = self.lifecycle_data.get("comment", "")
        self.edit_annotation.setPlainText(comment)

    def _init_button_accept(self):
        self.button_accept.clicked.connect(self._on_accept)

    def _init_button_reject(self):
        self.button_cancle.clicked.connect(self.reject)

    def _init_abstract_logic(self):
        """初始化抽象/非抽象的互斥逻辑"""
        # 连接抽象选择变化信号
        self.combo_abstract.currentTextChanged.connect(self._on_abstract_changed)
        # 初始化时根据默认选择设置控件状态
        self._on_abstract_changed(self.combo_abstract.currentText())

    def _on_abstract_changed(self, text):
        """当抽象选择改变时，控制操作和注释输入框的可用性"""
        is_abstract = (text == "是")
        
        if is_abstract:
            # 选择"是"（抽象）时：禁用操作输入框，启用注释输入框
            self.lifecycle_formula_editor.setEnabled(False)
            self.edit_op.clear()  # 清空操作内容
            self.edit_annotation.setEnabled(True)
            # 设置提示文本
            self.edit_op.setPlaceholderText("抽象操作无需具体实现")
            self.edit_annotation.setPlaceholderText("请输入抽象操作的注释说明")
        else:
            # 选择"否"（非抽象）时：启用操作输入框，禁用注释输入框
            self.lifecycle_formula_editor.setEnabled(True)
            self.edit_annotation.setEnabled(False)
            self.edit_annotation.clear()  # 清空注释内容
            # 设置提示文本
            self.edit_op.setPlaceholderText("请输入具体的操作内容")
            self.edit_annotation.setPlaceholderText("非抽象操作无需注释")

    def _on_accept(self):
        try:
            # 获取用户输入
            lifecycle_type = self.combo_type.currentText().strip()
            lifecycle_name = self.edit_name.text().strip()
            is_abstract_text = self.combo_abstract.currentText().strip()
            is_abstract = is_abstract_text == "是"
            operation = self.edit_op.toPlainText().strip()
            comment = self.edit_annotation.toPlainText().strip()

            if not is_abstract and not self.lifecycle_formula_editor.validate_now():
                QtWidgets.QMessageBox.warning(self, "操作无效", "请修正生命周期动作后再提交。")
                self.edit_op.setFocus()
                return

            # 验证输入
            if not lifecycle_type:
                QtWidgets.QMessageBox.warning(self, "错误", "类型不能为空！")
                return

            if is_abstract:
                # 抽象操作验证：必须有注释，不能有操作内容
                if not comment.strip():
                    QtWidgets.QMessageBox.warning(self, "错误", "抽象的生命周期操作必须有注释说明！")
                    return
                if operation.strip():  # 由于界面已经禁用，这个检查是为了安全
                    QtWidgets.QMessageBox.warning(self, "错误", "抽象的生命周期操作不能有具体操作内容！")
                    return
            else:
                # 非抽象操作验证：必须有操作内容，不能有注释
                if not operation.strip():
                    QtWidgets.QMessageBox.warning(self, "错误", "非抽象的生命周期操作必须有具体操作内容！")
                    return
                if comment.strip():  # 由于界面已经禁用，这个检查是为了安全
                    QtWidgets.QMessageBox.warning(self, "错误", "非抽象的生命周期操作不能有注释！")
                    return

            # 创建生命周期操作字典
            lifecycle_item = {
                "type": lifecycle_type,
                "name": lifecycle_name,
                "is_abstract": is_abstract,
                "action": operation,  # 使用 "action" 字段名以保持与DSL转换的一致性
                "comment": comment
            }

            if not self.mutate_model:
                self.accept()
                return
            if self.is_edit:
                # 编辑模式：更新现有的生命周期项
                # 这里需要外部传入要编辑的生命周期项的索引
                # 将通过 self.lifecycle_index 获取
                if hasattr(self, 'lifecycle_index') and 0 <= self.lifecycle_index < len(self.current_state.lifecycle):
                    self.current_state.lifecycle[self.lifecycle_index] = lifecycle_item
                    QtWidgets.QMessageBox.information(self, "成功", "生命周期操作修改成功！")
                else:
                    QtWidgets.QMessageBox.warning(self, "错误", "无法找到要修改的生命周期操作！")
                    return
            else:
                # 添加模式：添加新的生命周期项
                owner_state = self.get_owner_state()
                if owner_state is None:
                    QtWidgets.QMessageBox.warning(self, "错误", "请选择所属状态！")
                    return
                if owner_state.lifecycle is None:
                    owner_state.lifecycle = []
                
                owner_state.lifecycle.append(lifecycle_item)
                QtWidgets.QMessageBox.information(self, "成功", "生命周期操作添加成功！")
            
            self.accept()

        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "添加失败",
                f"添加生命周期操作时发生错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )
            return

    def get_lifecycle_data(self):
        """
        获取生命周期数据，供外部调用
        """
        return {
            "type": self.combo_type.currentText().strip(),
            "name": self.edit_name.text().strip(),
            "is_abstract": self.combo_abstract.currentText().strip() == "是",
            "action": self.edit_op.toPlainText().strip(),  # 使用 "action" 字段名以保持与DSL转换的一致性
            "comment": self.edit_annotation.toPlainText().strip()
        }

    def get_owner_state(self):
        if self.is_edit:
            return self.current_state
        return selected_state(self.combo_owner_state)
