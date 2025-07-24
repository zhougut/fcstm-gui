from PyQt5.Qt import QDialog
from PyQt5 import QtWidgets

from ..ui import UIDialogEditState
from typing import Optional
from ..model import State, StateManager

class DialogEditState(QDialog, UIDialogEditState):
    def __init__(self, parent, state_manager: StateManager,
                 is_edit=False, initial_data: Optional[State] = None):
        QDialog.__init__(self, parent)
        self.setupUi(self)
        self.setFixedSize(self.width(), self.height())

        self.is_edit = is_edit
        self.initial_data = initial_data
        self.state_manager = state_manager

        self._init()

    def _init(self):
        self._init_ui()
        self._init_button_accept()
        self._init_button_reject()

    def _init_ui(self):
        if self.is_edit:
            self.setWindowTitle("修改状态名称")
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
        if (self.state_manager.get_state(state_name) and
                (self.initial_data is None or self.initial_data.name != state_name)):
            QtWidgets.QMessageBox.warning(self, "错误", "状态名已经存在！")
            return
        self.accept()

    def _init_button_reject(self):
        self.button_cancle.clicked.connect(self.reject)

    def get_state_name(self) -> str:
        name = self.edit_state_name.text()
        return name