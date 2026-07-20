from PyQt5.Qt import QDialog
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt

from ..ui import UIDialogEditState
from typing import Optional
from ..model import State, StateManager
from .state_selector import populate_state_combo, selected_state

class DialogEditState(QDialog, UIDialogEditState):
    def __init__(self, parent, state_manager: StateManager,
                 is_edit=False, initial_data: Optional[State] = None, 
                 parent_state: Optional[State] = None):
        QDialog.__init__(self, parent)
        self.setupUi(self)
        self.setMinimumSize(self.size())

        self.is_edit = is_edit
        self.initial_data = initial_data
        self.state_manager = state_manager
        self.parent_state = parent_state  # 新增：父状态上下文

        self._init()

    def _init(self):
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._init_ui()
        self._init_button_accept()
        self._init_button_reject()

    def _init_ui(self):
        populate_state_combo(
            self.combo_parent_state,
            self.state_manager,
            selected_state=(
                self.initial_data.parent
                if self.is_edit and self.initial_data is not None
                else self.parent_state
            ),
            include_root_choice=self.state_manager.root_state is None,
        )
        if self.is_edit:
            self.setWindowTitle("修改状态名称")
            self.combo_parent_state.setEnabled(False)
            self.combo_parent_state.setToolTip("修改状态名称时不移动所属层级")
            if self.initial_data:
                # 预填充内容
                self.edit_state_name.setText(self.initial_data.name)
        else:
            self.setWindowTitle("添加状态")

    def _init_button_accept(self):
        self.button_accept.clicked.connect(self._on_accept)

    def _on_accept(self):
        state_name = self.edit_state_name.text().strip()
        if not state_name or state_name == '':
            QtWidgets.QMessageBox.warning(self, "错误", "状态名不能为空！")
            return
        
        chosen_parent = self.get_parent_state()

        # 检查同一父状态下是否有重复名称
        if self.is_edit:
            # 编辑状态：检查同一父状态下是否有其他同名状态
            if self.initial_data and self.initial_data.parent:
                existing_sibling = self.initial_data.parent.find_child_by_name(state_name)
                if existing_sibling and existing_sibling != self.initial_data:
                    QtWidgets.QMessageBox.warning(self, "错误", f"父状态 '{self.initial_data.parent.name}' 下已存在名为 '{state_name}' 的子状态！")
                    return
        else:
            # 添加状态：检查指定父状态下是否已有同名子状态
            if chosen_parent:
                if chosen_parent.find_child_by_name(state_name):
                    QtWidgets.QMessageBox.warning(self, "错误", f"父状态 '{chosen_parent.name}' 下已存在名为 '{state_name}' 的子状态！")
                    return
            else:
                # 添加根状态：检查是否已有根状态
                if self.state_manager.root_state is not None:
                    QtWidgets.QMessageBox.warning(self, "错误", "状态机中只能有一个根状态！")
                    return
        
        self.accept()

    def _init_button_reject(self):
        self.button_cancle.clicked.connect(self.reject)

    def get_state_name(self) -> str:
        name = self.edit_state_name.text()
        return name

    def get_parent_state(self) -> Optional[State]:
        if self.is_edit and self.initial_data is not None:
            return self.initial_data.parent
        return selected_state(self.combo_parent_state)
