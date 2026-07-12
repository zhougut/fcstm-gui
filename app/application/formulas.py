from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from pyfcstm.model import load_state_machine_from_text, parse_expr_from_string


class FormulaKind(str, Enum):
    LOGICAL = "logical"
    NUMERIC = "numeric"
    EFFECT = "effect"
    LIFECYCLE = "lifecycle"


class FormulaValidationStatus(str, Enum):
    VALID = "valid"
    INVALID = "invalid"


@dataclass(frozen=True)
class FormulaLocation:
    line: int
    column: int
    offset: int


@dataclass(frozen=True)
class FormulaValidationRequest:
    kind: FormulaKind
    text: str
    source_revision: int
    request_token: str
    variable_definitions: Optional[str] = None

    def __post_init__(self) -> None:
        try:
            kind = FormulaKind(self.kind)
        except (TypeError, ValueError):
            raise ValueError("unknown formula kind: {!r}".format(self.kind))
        if not isinstance(self.text, str):
            raise TypeError("text must be a string")
        if not isinstance(self.source_revision, int):
            raise TypeError("source_revision must be an integer")
        if not isinstance(self.request_token, str):
            raise TypeError("request_token must be a string")
        if self.variable_definitions is not None and not isinstance(
            self.variable_definitions, str
        ):
            raise TypeError("variable_definitions must be a string or None")
        object.__setattr__(self, "kind", kind)


@dataclass(frozen=True)
class FormulaValidationResult:
    kind: FormulaKind
    status: FormulaValidationStatus
    message: str
    location: Optional[FormulaLocation]
    source_revision: int
    request_token: str

    @property
    def is_valid(self) -> bool:
        return self.status is FormulaValidationStatus.VALID


@dataclass(frozen=True)
class _ActionSource:
    text: str
    formula_start_line: int


class FormulaValidationService:
    """Validate formula fields with the same parsers used by production models."""

    def validate(self, request: FormulaValidationRequest) -> FormulaValidationResult:
        if not isinstance(request, FormulaValidationRequest):
            raise TypeError("request must be a FormulaValidationRequest")
        try:
            if request.kind in (FormulaKind.LOGICAL, FormulaKind.NUMERIC):
                parse_expr_from_string(request.text, mode=request.kind.value)
            else:
                action_source = self._action_source(
                    request.kind,
                    request.text,
                    request.variable_definitions,
                )
                load_state_machine_from_text(action_source.text)
        except Exception as error:
            location = self._error_location(error, request.text)
            if request.kind in (FormulaKind.EFFECT, FormulaKind.LIFECYCLE):
                location = self._action_error_location(
                    error,
                    request.text,
                    action_source.formula_start_line,
                )
            return FormulaValidationResult(
                kind=request.kind,
                status=FormulaValidationStatus.INVALID,
                message=self._error_message(error),
                location=location,
                source_revision=request.source_revision,
                request_token=request.request_token,
            )

        action_kind = request.kind in (FormulaKind.EFFECT, FormulaKind.LIFECYCLE)
        return FormulaValidationResult(
            kind=request.kind,
            status=FormulaValidationStatus.VALID,
            message="动作有效" if action_kind else "公式有效",
            location=None,
            source_revision=request.source_revision,
            request_token=request.request_token,
        )

    @staticmethod
    def _action_source(
        kind: FormulaKind,
        text: str,
        variable_definitions: Optional[str] = None,
    ) -> _ActionSource:
        if variable_definitions is None:
            declarations = "def int x = 0;\n"
        else:
            declarations = variable_definitions.strip()
            if declarations:
                declarations += "\n"
        if kind is FormulaKind.EFFECT:
            prefix = (
                declarations + "state Root {\n"
                "state A;\n"
                "state B;\n"
                "[*] -> A;\n"
                "A -> B effect {\n"
            )
            suffix = "\n}\nB -> [*];\n}\n"
        elif kind is FormulaKind.LIFECYCLE:
            prefix = declarations + "state Root {\nenter {\n"
            suffix = "\n}\nstate A;\n[*] -> A;\nA -> [*];\n}\n"
        else:  # pragma: no cover - request validation prevents this branch
            raise ValueError("action source requested for {!r}".format(kind))
        return _ActionSource(
            text=prefix + text + suffix,
            formula_start_line=prefix.count("\n") + 1,
        )

    @classmethod
    def _action_error_location(
        cls,
        error: BaseException,
        text: str,
        formula_start_line: int,
    ) -> Optional[FormulaLocation]:
        raw = cls._raw_error_position(error)
        if raw is None:
            return None
        wrapped_line, wrapped_column, wrapped_offset = raw
        if wrapped_line is None:
            return cls._location_from_offset(text, wrapped_offset)
        relative_line = wrapped_line - formula_start_line + 1
        if relative_line < 1:
            return FormulaLocation(line=1, column=0, offset=0)
        line_count = max(1, len(text.splitlines()) + int(text.endswith(("\n", "\r"))))
        if relative_line > line_count:
            return cls._location_from_offset(text, len(text))
        return cls._location_from_line_column(text, relative_line, wrapped_column)

    @classmethod
    def _error_location(
        cls, error: BaseException, text: str
    ) -> Optional[FormulaLocation]:
        raw = cls._raw_error_position(error)
        if raw is None:
            return None
        line, column, offset = raw
        if line is None:
            return cls._location_from_offset(text, offset)
        return cls._location_from_line_column(text, line, column)

    @staticmethod
    def _raw_error_position(
        error: BaseException,
    ) -> Optional[Tuple[Optional[int], int, int]]:
        nested = getattr(error, "errors", None) or getattr(error, "diagnostics", None)
        candidates = tuple(nested) if nested else (error,)
        for item in candidates:
            line = getattr(item, "line", None)
            column = getattr(item, "column", None)
            if isinstance(line, int) and isinstance(column, int):
                return line, max(0, column), 0
            position = getattr(item, "position", None)
            if not isinstance(position, int):
                position = getattr(item, "offset", None)
            if not isinstance(position, int):
                # pyfcstm's UnfinishedParsingError calls its character position
                # ``lineno`` even though it is not a source line.
                position = getattr(item, "lineno", None)
            if isinstance(position, int):
                return None, 0, max(0, position)
        return None

    @staticmethod
    def _location_from_line_column(
        text: str, line: int, column: int
    ) -> FormulaLocation:
        line = max(1, line)
        column = max(0, column)
        lines = text.splitlines(True)
        if not lines:
            return FormulaLocation(line=1, column=0, offset=0)
        if line > len(lines):
            return FormulaValidationService._location_from_offset(text, len(text))
        line_text = lines[line - 1]
        content_length = len(line_text.rstrip("\r\n"))
        column = min(column, content_length)
        offset = sum(len(item) for item in lines[:line - 1]) + column
        return FormulaLocation(line=line, column=column, offset=offset)

    @staticmethod
    def _location_from_offset(text: str, offset: int) -> FormulaLocation:
        offset = max(0, min(offset, len(text)))
        prefix = text[:offset]
        line = prefix.count("\n") + 1
        last_newline = prefix.rfind("\n")
        column = offset if last_newline < 0 else offset - last_newline - 1
        return FormulaLocation(line=line, column=column, offset=offset)

    @staticmethod
    def _error_message(error: BaseException) -> str:
        nested = getattr(error, "errors", None) or getattr(error, "diagnostics", None)
        if nested:
            first = next(iter(nested), None)
            if first is not None and str(first).strip():
                return str(first).strip()
        message = str(error).strip()
        return message or error.__class__.__name__


__all__ = [
    "FormulaKind",
    "FormulaLocation",
    "FormulaValidationRequest",
    "FormulaValidationResult",
    "FormulaValidationService",
    "FormulaValidationStatus",
]
