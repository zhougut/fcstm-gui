from PyQt5 import QtCore, QtWidgets

from app.application.formulas import (
    FormulaKind,
    FormulaValidationRequest,
    FormulaValidationService,
    FormulaValidationStatus,
)


class FormulaEditor(QtWidgets.QWidget):
    validation_changed = QtCore.pyqtSignal(object)

    def __init__(
        self,
        field,
        kind,
        revision_provider=None,
        variable_definitions_provider=None,
        service=None,
        debounce_ms=300,
        allow_empty=False,
        parent=None,
    ):
        super().__init__(parent or field.parentWidget())
        self.field = field
        self.kind = FormulaKind(kind)
        self._revision_provider = revision_provider or (lambda: 0)
        self._variable_definitions_provider = (
            variable_definitions_provider or (lambda: None)
        )
        self._service = service or FormulaValidationService()
        self._allow_empty = bool(allow_empty)
        self._request_sequence = 0
        self.pending_request = None
        self.last_result = None

        self.setObjectName("{}_formula_editor".format(self.kind.value))
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addWidget(field)
        self.status_label = QtWidgets.QLabel(self)
        self.status_label.setObjectName("formula_validation_status")
        self.status_label.setAccessibleName("公式校验状态")
        self.status_label.setWordWrap(False)
        self.status_label.setFixedHeight(20)
        layout.addWidget(self.status_label)

        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(int(debounce_ms))
        self._timer.timeout.connect(self._validate_pending)
        if isinstance(field, QtWidgets.QLineEdit):
            field.textChanged.connect(self._schedule_validation)
        else:
            field.textChanged.connect(self._schedule_validation)
        self._schedule_validation()

    @property
    def is_valid(self):
        return (
            self.last_result is not None
            and self.last_result.status is FormulaValidationStatus.VALID
        )

    def text(self):
        if isinstance(self.field, QtWidgets.QLineEdit):
            return self.field.text()
        return self.field.toPlainText()

    def _schedule_validation(self, *unused):
        self._request_sequence += 1
        self.pending_request = FormulaValidationRequest(
            kind=self.kind,
            text=self.text().strip(),
            source_revision=int(self._revision_provider()),
            request_token="{}-{}".format(self.kind.value, self._request_sequence),
            variable_definitions=self._variable_definitions_provider(),
        )
        self.last_result = None
        self.status_label.setText("等待校验")
        self.status_label.setStyleSheet("color: #6b7280;")
        self._timer.start()

    def validate_now(self):
        self._timer.stop()
        if (
            self.pending_request is None
            or self.pending_request.source_revision
            != int(self._revision_provider())
        ):
            self._schedule_validation()
            self._timer.stop()
        self._validate_pending()
        return self.is_valid

    def _validate_pending(self):
        request = self.pending_request
        if request is None:
            return
        if self._allow_empty and not request.text:
            result = self._service.validate(
                FormulaValidationRequest(
                    request.kind,
                    "true" if request.kind is FormulaKind.LOGICAL else "0"
                    if request.kind is FormulaKind.NUMERIC
                    else "x = x;",
                    request.source_revision,
                    request.request_token,
                    request.variable_definitions,
                )
            )
        else:
            result = self._service.validate(request)
        self.apply_result(result)

    def apply_result(self, result):
        request = self.pending_request
        if (
            request is None
            or result.request_token != request.request_token
            or result.source_revision != request.source_revision
            or result.source_revision != int(self._revision_provider())
        ):
            return False
        self.last_result = result
        if result.is_valid:
            self.status_label.setText(result.message)
            self.status_label.setToolTip(result.message)
            self.status_label.setStyleSheet("color: #18794e;")
        else:
            location = result.location
            prefix = (
                "{}:{} ".format(location.line, location.column + 1)
                if location is not None
                else ""
            )
            summary = " ".join(result.message.split())
            marker = summary.find("Invalid syntax")
            if marker >= 0:
                summary = summary[marker:]
            if len(summary) > 38:
                summary = summary[:35] + "..."
            self.status_label.setText(prefix + "无效：" + summary)
            self.status_label.setToolTip(result.message)
            self.status_label.setStyleSheet("color: #b42318;")
            if location is not None:
                self._move_to_offset(location.offset)
        self.validation_changed.emit(result)
        return True

    def _move_to_offset(self, offset):
        offset = max(0, min(int(offset), len(self.text())))
        if isinstance(self.field, QtWidgets.QLineEdit):
            self.field.setCursorPosition(offset)
            return
        cursor = self.field.textCursor()
        cursor.setPosition(offset)
        self.field.setTextCursor(cursor)


__all__ = ["FormulaEditor"]
