from html import escape

from PyQt5 import QtCore, QtGui, QtWidgets

from app.application.formula_render import (
    FormulaRenderService,
    formula_kind_description,
)
from app.application.formulas import FormulaKind, FormulaValidationService
from app.widget.formula_editor import FormulaEditor


class FormulaSourceEdit(QtWidgets.QPlainTextEdit):
    """Multiline editor with QLineEdit-compatible text helpers."""

    def setText(self, text):
        self.setPlainText(text)

    def text(self):
        return self.toPlainText()


class DialogFormulaEditor(QtWidgets.QDialog):
    """Edit, validate, and visually preview one FCSTM formula or action."""

    def __init__(
        self,
        parent=None,
        initial_text="",
        kind=FormulaKind.NUMERIC,
        title=None,
        revision_provider=None,
        variable_definitions_provider=None,
        service=None,
        render_service=None,
        debounce_ms=300,
        allow_empty=False,
    ):
        super().__init__(parent)
        self.kind = FormulaKind(kind)
        self.description = formula_kind_description(self.kind)
        self._service = service or FormulaValidationService()
        self._render_service = render_service or FormulaRenderService()
        self._revision_provider = revision_provider or (lambda: 0)
        self._variable_definitions_provider = (
            variable_definitions_provider or (lambda: None)
        )
        self._allow_empty = bool(allow_empty)

        self.setObjectName("formula_editor_dialog")
        self.setWindowTitle(title or self.description.title)
        self.setWindowFlags(
            self.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint
        )
        self.setMinimumSize(640, 520)
        self.resize(760, 620)

        self.prompt_label = QtWidgets.QLabel(self.description.source_label, self)
        self.prompt_label.setObjectName("formula_source_label")
        self.prompt_label.setAccessibleName("公式源码标签")

        self.input_field = FormulaSourceEdit(self)
        self.input_field.setObjectName("formula_source_input")
        self.input_field.setAccessibleName("公式源码输入框")
        self.input_field.setPlaceholderText(self.description.placeholder)
        self.input_field.setMinimumHeight(126)
        metrics = QtGui.QFontMetricsF(self.input_field.font())
        self.input_field.setTabStopDistance(metrics.horizontalAdvance(" ") * 4)
        self.input_field.setPlainText(initial_text)

        self.formula_editor = FormulaEditor(
            self.input_field,
            self.kind,
            revision_provider=self._revision_provider,
            variable_definitions_provider=self._variable_definitions_provider,
            service=self._service,
            debounce_ms=debounce_ms,
            allow_empty=self._allow_empty,
            parent=self,
        )
        self.formula_editor.setObjectName("formula_validation_editor")
        self.formula_editor.validation_changed.connect(self._on_validation_changed)

        self.example_label = QtWidgets.QLabel("插入示例", self)
        self.example_combo = QtWidgets.QComboBox(self)
        self.example_combo.setObjectName("formula_example_combo")
        self.example_combo.setAccessibleName("公式示例列表")
        for example in self.description.examples:
            display = " ".join(example.split())
            if len(display) > 58:
                display = display[:55] + "..."
            self.example_combo.addItem(display, example)
        self.example_button = QtWidgets.QPushButton("使用示例", self)
        self.example_button.setObjectName("formula_insert_example")
        self.example_button.setAccessibleName("插入所选公式示例")
        self.example_button.clicked.connect(self._insert_example)

        example_layout = QtWidgets.QHBoxLayout()
        example_layout.setContentsMargins(0, 0, 0, 0)
        example_layout.addWidget(self.example_label)
        example_layout.addWidget(self.example_combo, 1)
        example_layout.addWidget(self.example_button)

        self.preview_label = QtWidgets.QLabel(self.description.preview_label, self)
        self.preview_label.setObjectName("formula_preview_label")
        self.preview_label.setAccessibleName("公式渲染结果标签")
        self.preview = QtWidgets.QTextBrowser(self)
        self.preview.setObjectName("formula_rendered_preview")
        self.preview.setAccessibleName("渲染后的公式")
        self.preview.setOpenExternalLinks(False)
        self.preview.setMinimumHeight(150)
        self.preview.setStyleSheet(
            "QTextBrowser { background: #f7f9fc; border: 1px solid #cdd6e4; "
            "border-radius: 5px; padding: 6px; }"
        )

        self.syntax_help = QtWidgets.QLabel(self)
        self.syntax_help.setObjectName("formula_syntax_help")
        self.syntax_help.setAccessibleName("FCSTM 公式语法说明")
        self.syntax_help.setTextFormat(QtCore.Qt.RichText)
        self.syntax_help.setWordWrap(True)
        self.syntax_help.setText(
            "<b>支持的语法：</b>" + self.description.syntax_summary
        )
        self.syntax_help.setStyleSheet(
            "QLabel { color: #475467; background: #f2f4f7; border-radius: 4px; "
            "padding: 7px; }"
        )

        self.button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self,
        )
        self.button_box.setObjectName("formula_editor_buttons")
        accept_button = self.button_box.button(QtWidgets.QDialogButtonBox.Ok)
        reject_button = self.button_box.button(QtWidgets.QDialogButtonBox.Cancel)
        accept_button.setObjectName("formula_editor_accept")
        accept_button.setText("确定")
        accept_button.setAccessibleName("确定公式编辑")
        accept_button.setToolTip("提交已通过 FCSTM 校验的内容")
        accept_button.setEnabled(False)
        reject_button.setObjectName("formula_editor_reject")
        reject_button.setText("取消")
        reject_button.setAccessibleName("取消公式编辑")
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        layout.addWidget(self.prompt_label)
        layout.addLayout(example_layout)
        layout.addWidget(self.formula_editor, 2)
        layout.addWidget(self.preview_label)
        layout.addWidget(self.preview, 2)
        layout.addWidget(self.syntax_help)
        layout.addWidget(self.button_box)
        self.setLayout(layout)

        self.preview.setHtml(
            "<div style='color:#687386; padding:10px;'>等待 FCSTM 语法校验…</div>"
        )
        self.input_field.setFocus(QtCore.Qt.OtherFocusReason)

    def formula_text(self):
        return self.input_field.toPlainText().strip()

    def _insert_example(self):
        example = self.example_combo.currentData()
        if not isinstance(example, str):
            return
        self.input_field.setPlainText(example)
        cursor = self.input_field.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.input_field.setTextCursor(cursor)
        self.input_field.setFocus(QtCore.Qt.OtherFocusReason)

    def _on_validation_changed(self, result):
        accepted = bool(result.is_valid)
        self.button_box.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(accepted)
        source = self.formula_text()
        if accepted and not source and self._allow_empty:
            self.preview.setHtml(
                "<div style='color:#687386; padding:10px;'>（此字段允许留空）</div>"
            )
            return
        if accepted:
            try:
                rendered = self._render_service.render(self.kind, source)
            except Exception as error:  # parser validation is authoritative
                self.preview.setHtml(
                    "<div style='color:#b42318; padding:10px;'>预览生成失败：{}</div>".format(
                        escape(str(error))
                    )
                )
            else:
                self.preview.setHtml(rendered.html)
            return
        self.preview.setHtml(
            "<div style='color:#b42318; padding:10px;'><b>无法渲染</b><br>"
            "请先修正上方 FCSTM 语法错误。</div>"
        )

    def _on_accept(self):
        if not self.formula_editor.validate_now():
            self.button_box.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
            self.input_field.setFocus(QtCore.Qt.OtherFocusReason)
            return
        self.accept()


__all__ = ["DialogFormulaEditor", "FormulaSourceEdit"]
