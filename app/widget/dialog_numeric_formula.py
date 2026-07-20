from PyQt5 import QtWidgets

from app.application.formulas import FormulaKind
from app.widget.dialog_formula import DialogFormulaEditor


class DialogNumericFormula(DialogFormulaEditor):
    """Backward-compatible numeric specialization of the full formula editor."""

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
        super().__init__(
            parent=parent,
            initial_text=initial_text,
            kind=FormulaKind.NUMERIC,
            title=title,
            revision_provider=revision_provider,
            variable_definitions_provider=variable_definitions_provider,
            service=service,
            debounce_ms=debounce_ms,
        )
        self.setObjectName("numeric_formula_dialog")
        self.prompt_label.setObjectName("numeric_formula_prompt")
        self.prompt_label.setAccessibleName("数值公式标签")
        self.input_field.setObjectName("numeric_formula_input")
        self.input_field.setAccessibleName("数值公式输入框")
        self.formula_editor.setObjectName("numeric_formula_editor")
        self.button_box.setObjectName("numeric_formula_buttons")
        accept_button = self.button_box.button(QtWidgets.QDialogButtonBox.Ok)
        reject_button = self.button_box.button(QtWidgets.QDialogButtonBox.Cancel)
        accept_button.setObjectName("numeric_formula_accept")
        accept_button.setAccessibleName("确定数值公式")
        reject_button.setObjectName("numeric_formula_reject")
        reject_button.setAccessibleName("取消数值公式编辑")


__all__ = ["DialogNumericFormula"]
