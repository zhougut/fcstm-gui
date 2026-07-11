from PyQt5.Qt import QDialog
from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt
import os
import tempfile

from ..ui import UIDialogCodeGen
from ..model import StateManager
from app.utils.ui_to_dsl import state_manager_to_dsl
from pyfcstm.dsl import parse_with_grammar_entry
from pyfcstm.model import parse_dsl_node_to_state_machine
from pyfcstm.render import StateMachineCodeRenderer

class DialogCodeGen(QDialog, UIDialogCodeGen):
    def __init__(self, parent, state_manager: StateManager, model=None):
        QDialog.__init__(self, parent)
        self.setupUi(self)
        self.setFixedSize(self.width(), self.height())

        self.state_manager = state_manager
        self.model = model

        self._init()

    def _init(self):
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._init_ui()
        self._init_button_template_dir()
        self._init_button_output_dir()
        self._init_button_accept()
        self._init_button_reject()

    def _init_ui(self):
        self.setWindowTitle("代码生成")

    def _init_button_accept(self):
        self.button_accept.clicked.connect(self._on_accept)

    def _init_button_reject(self):
        self.button_cancle.clicked.connect(self.reject)

    def _init_button_template_dir(self):
        self.button_template_dir.clicked.connect(self._on_template_dir)

    def _init_button_output_dir(self):
        self.button_output_dir.clicked.connect(self._on_output_dir)

    def _on_accept(self):
        try:
            # 获取用户输入
            template_dir = self.edit_template_dir.text().strip()
            output_dir = self.edit_ouput_dir.text().strip()
            is_clear_before = False
            if self.combo_clear_before.currentText() == '是':
                is_clear_before = True
            else:
                is_clear_before = False

            # 验证输入
            if not template_dir or not output_dir:
                QtWidgets.QMessageBox.warning(self, "错误", "模板目录或输出目录不能为空！")
                return

            if not os.path.exists(template_dir):
                QtWidgets.QMessageBox.warning(self, "错误", "模板目录不存在！")
                return

            # 创建输出目录（如果不存在）
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)

            # 获取state_manager的dsl表示
            model = self.model
            if model is None:
                dsl_code = state_manager_to_dsl(self.state_manager)
                ast_node = parse_with_grammar_entry(
                    dsl_code, entry_name='state_machine_dsl'
                )
                model = parse_dsl_node_to_state_machine(ast_node)

            renderer = StateMachineCodeRenderer(
                template_dir=template_dir,
            )
            renderer.render(
                model,
                output_dir=output_dir,
                clear_previous_directory=is_clear_before
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "生成失败",
                f"生成代码时发生错误：\n{str(e)}",
                QtWidgets.QMessageBox.Ok
            )
            return

        self.accept()

    def _on_template_dir(self):
        """选择模板目录"""
        template_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "选择模板目录",
            "",
            QtWidgets.QFileDialog.ShowDirsOnly | QtWidgets.QFileDialog.DontResolveSymlinks
        )
        if template_dir:
            self.edit_template_dir.setText(template_dir)

    def _on_output_dir(self):
        """选择输出目录"""
        output_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "选择输出目录",
            "",
            QtWidgets.QFileDialog.ShowDirsOnly | QtWidgets.QFileDialog.DontResolveSymlinks
        )
        if output_dir:
            self.edit_ouput_dir.setText(output_dir)
