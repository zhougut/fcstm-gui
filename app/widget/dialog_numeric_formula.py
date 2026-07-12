from PyQt5 import QtCore, QtWidgets

from app.application.formulas import FormulaKind, FormulaValidationService
from app.widget.formula_editor import FormulaEditor


class DialogNumericFormula(QtWidgets.QDialog):
    """Reusable dialog for editing a numeric FCSTM formula."""

    def __init__(
        self,
        parent=None,
        initial_text="",
        title="编辑数值公式",
        revision_provider=None,
        variable_definitions_provider=None,
        service=None,
        debounce_ms=300,
    ):
        super().__init__(parent)
        self.setObjectName("numeric_formula_dialog")
        self.setWindowTitle(title)
        self.setWindowFlags(
            self.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint
        )
        self._service = service or FormulaValidationService()
        self._revision_provider = revision_provider or (lambda: 0)
        self._variable_definitions_provider = (
            variable_definitions_provider or (lambda: None)
        )

        self.prompt_label = QtWidgets.QLabel("数值公式", self)
        self.prompt_label.setObjectName("numeric_formula_prompt")
        self.prompt_label.setAccessibleName("数值公式标签")

        self.input_field = QtWidgets.QLineEdit(self)
        self.input_field.setObjectName("numeric_formula_input")
        self.input_field.setAccessibleName("数值公式输入框")
        self.input_field.setPlaceholderText("例如：x * 2 + 1")
        self.input_field.setText(initial_text)

        self.formula_editor = FormulaEditor(
            self.input_field,
            FormulaKind.NUMERIC,
            revision_provider=self._revision_provider,
            variable_definitions_provider=self._variable_definitions_provider,
            service=self._service,
            debounce_ms=debounce_ms,
            parent=self,
        )
        self.formula_editor.setObjectName("numeric_formula_editor")
        self.formula_editor.validation_changed.connect(self._on_validation_changed)

        self.button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self,
        )
        self.button_box.setObjectName("numeric_formula_buttons")
        accept_button = self.button_box.button(QtWidgets.QDialogButtonBox.Ok)
        reject_button = self.button_box.button(QtWidgets.QDialogButtonBox.Cancel)
        accept_button.setObjectName("numeric_formula_accept")
        accept_button.setText("确定")
        accept_button.setAccessibleName("确定数值公式")
        accept_button.setToolTip("提交已通过校验的数值公式")
        reject_button.setObjectName("numeric_formula_reject")
        reject_button.setText("取消")
        reject_button.setAccessibleName("取消数值公式编辑")
        reject_button.setToolTip("放弃本次数值公式编辑")
        accept_button.setEnabled(False)
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.prompt_label)
        layout.addWidget(self.formula_editor)
        layout.addWidget(self.button_box)
        self.setLayout(layout)
        self.input_field.setFocus(QtCore.Qt.OtherFocusReason)

    def formula_text(self):
        return self.input_field.text().strip()

    def _on_validation_changed(self, result):
        self.button_box.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(
            bool(result.is_valid)
        )

    def _on_accept(self):
        if not self.formula_editor.validate_now():
            self.button_box.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
            self.input_field.setFocus(QtCore.Qt.OtherFocusReason)
            return
        self.accept()


__all__ = ["DialogNumericFormula"]
