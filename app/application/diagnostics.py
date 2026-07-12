"""Application DTOs for pyfcstm's three independent diagnostic sources."""

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Optional, Tuple

from pyfcstm.diagnostics.codes import CODE_REGISTRY
from pyfcstm.dsl.error import GrammarParseError, SyntaxFailError
from pyfcstm.utils.validate import ModelValidationError


class DiagnosticSourceKind(str, Enum):
    SYNTAX = "syntax"
    MODEL = "model"
    INSPECT = "inspect"


@dataclass(frozen=True)
class DiagnosticSpan:
    """Native line/column values; no coordinate conversion is performed."""

    line: int
    column: int
    end_line: Optional[int] = None
    end_column: Optional[int] = None


@dataclass(frozen=True)
class SuggestedFix:
    kind: str
    target: str
    anchor_ref: str
    text_template: str
    rationale: str


@dataclass(frozen=True)
class DiagnosticItem:
    source_kind: DiagnosticSourceKind
    source_uri: str
    code: Optional[str]
    severity: Optional[str]
    message: str
    span: Optional[DiagnosticSpan]
    refs: Optional[Mapping[str, Any]]
    suggested_fix: Optional[SuggestedFix]
    source_revision: int
    dependency_fingerprint: Optional[str]
    provenance: str
    raw_message: Optional[str] = None
    offending_symbol_text: Optional[str] = None

    def matches(
        self,
        source_revision: int,
        dependency_fingerprint: Optional[str],
    ) -> bool:
        return (
            self.source_revision == source_revision
            and self.dependency_fingerprint == dependency_fingerprint
        )


@dataclass(frozen=True)
class DiagnosticQuery:
    severities: Tuple[str, ...] = ()
    source_kinds: Tuple[DiagnosticSourceKind, ...] = ()
    search: str = ""


@dataclass(frozen=True)
class DiagnosticReport:
    source_revision: int
    dependency_fingerprint: Optional[str]
    items: Tuple[DiagnosticItem, ...]

    def __post_init__(self) -> None:
        if any(
            not item.matches(
                self.source_revision,
                self.dependency_fingerprint,
            )
            for item in self.items
        ):
            raise ValueError("diagnostic item stamp does not match its report")

    def matches(
        self,
        source_revision: int,
        dependency_fingerprint: Optional[str],
    ) -> bool:
        return (
            self.source_revision == source_revision
            and self.dependency_fingerprint == dependency_fingerprint
        )

    def select(self, query: DiagnosticQuery) -> Tuple[DiagnosticItem, ...]:
        severities = frozenset(query.severities)
        source_kinds = frozenset(query.source_kinds)
        needle = query.search.strip().casefold()
        selected = []
        for item in self.items:
            if severities and item.severity not in severities:
                continue
            if source_kinds and item.source_kind not in source_kinds:
                continue
            if needle and needle not in _search_text(item):
                continue
            selected.append(item)
        return tuple(selected)


class DiagnosticService:
    """Adapt pyfcstm diagnostics while retaining their native provenance."""

    def from_syntax_error(
        self,
        error: BaseException,
        source_uri: str,
        source_revision: int,
        dependency_fingerprint: Optional[str],
    ) -> DiagnosticReport:
        if isinstance(error, GrammarParseError):
            native_items = tuple(error.errors)
        elif isinstance(error, SyntaxFailError):
            native_items = (error,)
        else:
            raise TypeError("syntax diagnostics require a pyfcstm syntax error")
        items = tuple(
            self._syntax_item(
                native,
                source_uri,
                source_revision,
                dependency_fingerprint,
            )
            for native in native_items
        )
        return DiagnosticReport(
            source_revision,
            dependency_fingerprint,
            items,
        )

    def from_model_error(
        self,
        error: ModelValidationError,
        source_uri: str,
        source_revision: int,
        dependency_fingerprint: Optional[str],
    ) -> DiagnosticReport:
        if not isinstance(error, ModelValidationError):
            raise TypeError("model diagnostics require ModelValidationError")
        items = []
        for diagnostic in error.diagnostics:
            items.append(
                self._model_item(
                    diagnostic,
                    DiagnosticSourceKind.MODEL,
                    source_uri,
                    source_revision,
                    dependency_fingerprint,
                )
            )
        for legacy_error in error.errors:
            items.append(
                self._plain_item(
                    legacy_error,
                    DiagnosticSourceKind.MODEL,
                    source_uri,
                    source_revision,
                    dependency_fingerprint,
                )
            )
        if not items:
            items.append(
                self._plain_item(
                    error,
                    DiagnosticSourceKind.MODEL,
                    source_uri,
                    source_revision,
                    dependency_fingerprint,
                )
            )
        return DiagnosticReport(
            source_revision,
            dependency_fingerprint,
            tuple(items),
        )

    def from_inspect_report(
        self,
        report: Any,
        source_uri: str,
        source_revision: int,
        dependency_fingerprint: Optional[str],
    ) -> DiagnosticReport:
        if isinstance(report, Mapping):
            diagnostics = report.get("diagnostics", ())
        else:
            diagnostics = getattr(report, "diagnostics", None)
            if diagnostics is None:
                raise TypeError("inspect report does not expose diagnostics")
        items = tuple(
            self._model_item(
                diagnostic,
                DiagnosticSourceKind.INSPECT,
                source_uri,
                source_revision,
                dependency_fingerprint,
            )
            for diagnostic in diagnostics
        )
        return DiagnosticReport(
            source_revision,
            dependency_fingerprint,
            items,
        )

    def from_native_items(
        self,
        diagnostics: Iterable[Any],
        source_kind: DiagnosticSourceKind,
        source_uri: str,
        source_revision: int,
        dependency_fingerprint: Optional[str],
    ) -> DiagnosticReport:
        source_kind = DiagnosticSourceKind(source_kind)
        items = []
        for native in diagnostics:
            if source_kind is DiagnosticSourceKind.SYNTAX:
                items.append(
                    self._syntax_item(
                        native,
                        source_uri,
                        source_revision,
                        dependency_fingerprint,
                    )
                )
            elif _field(native, "message") is not None:
                items.append(
                    self._model_item(
                        native,
                        source_kind,
                        source_uri,
                        source_revision,
                        dependency_fingerprint,
                    )
                )
            else:
                items.append(
                    self._plain_item(
                        native,
                        source_kind,
                        source_uri,
                        source_revision,
                        dependency_fingerprint,
                    )
                )
        return DiagnosticReport(
            source_revision,
            dependency_fingerprint,
            tuple(items),
        )

    @staticmethod
    def _syntax_item(
        native: BaseException,
        source_uri: str,
        source_revision: int,
        dependency_fingerprint: Optional[str],
    ) -> DiagnosticItem:
        positioned = isinstance(native, SyntaxFailError)
        span = (
            DiagnosticSpan(native.line, native.column)
            if positioned
            else None
        )
        return DiagnosticItem(
            source_kind=DiagnosticSourceKind.SYNTAX,
            source_uri=source_uri,
            code=None,
            severity=None,
            message=str(native.msg) if positioned else str(native),
            span=span,
            refs=None,
            suggested_fix=None,
            source_revision=source_revision,
            dependency_fingerprint=dependency_fingerprint,
            provenance=_type_name(native),
            raw_message=str(native.raw_msg) if positioned else None,
            offending_symbol_text=(
                native.offending_symbol_text if positioned else None
            ),
        )

    @staticmethod
    def _model_item(
        native: Any,
        source_kind: DiagnosticSourceKind,
        source_uri: str,
        source_revision: int,
        dependency_fingerprint: Optional[str],
    ) -> DiagnosticItem:
        code = _field(native, "code")
        severity = _field(native, "severity")
        message = _field(native, "message")
        if message is None:
            raise ValueError("model diagnostic does not contain message")
        refs = _field(native, "refs")
        if refs is not None:
            if not isinstance(refs, Mapping):
                raise TypeError("model diagnostic refs must be a mapping")
            refs = MappingProxyType(dict(refs))
        return DiagnosticItem(
            source_kind=source_kind,
            source_uri=source_uri,
            code=str(code) if code is not None else None,
            severity=str(severity) if severity is not None else None,
            message=str(message),
            span=_span(_field(native, "span")),
            refs=refs,
            suggested_fix=_suggested_fix(code, refs),
            source_revision=source_revision,
            dependency_fingerprint=dependency_fingerprint,
            provenance=(
                "pyfcstm.diagnostics.ModelDiagnostic(json)"
                if isinstance(native, Mapping)
                else _type_name(native)
            ),
        )

    @staticmethod
    def _plain_item(
        native: BaseException,
        source_kind: DiagnosticSourceKind,
        source_uri: str,
        source_revision: int,
        dependency_fingerprint: Optional[str],
    ) -> DiagnosticItem:
        return DiagnosticItem(
            source_kind=source_kind,
            source_uri=source_uri,
            code=None,
            severity=None,
            message=str(native),
            span=None,
            refs=None,
            suggested_fix=None,
            source_revision=source_revision,
            dependency_fingerprint=dependency_fingerprint,
            provenance=_type_name(native),
        )


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _span(value: Any) -> Optional[DiagnosticSpan]:
    if value is None:
        return None
    line = _field(value, "line")
    column = _field(value, "column")
    if line is None or column is None:
        return None
    return DiagnosticSpan(
        line=int(line),
        column=int(column),
        end_line=_optional_int(_field(value, "end_line")),
        end_column=_optional_int(_field(value, "end_column")),
    )


def _optional_int(value: Any) -> Optional[int]:
    return int(value) if value is not None else None


def _suggested_fix(
    code: Any, refs: Optional[Mapping[str, Any]] = None
) -> Optional[SuggestedFix]:
    if code is None:
        return None
    actual = refs.get("suggested_fix") if refs is not None else None
    if isinstance(actual, Mapping):
        anchor = actual.get("anchor")
        anchor_ref = (
            anchor.get("ref") if isinstance(anchor, Mapping) else None
        )
        if all(
            isinstance(actual.get(field), str)
            for field in ("kind", "target", "text", "rationale")
        ) and isinstance(anchor_ref, str):
            return SuggestedFix(
                kind=actual["kind"],
                target=actual["target"],
                anchor_ref=anchor_ref,
                text_template=actual["text"],
                rationale=actual["rationale"],
            )
    spec = CODE_REGISTRY.get(str(code))
    native = spec.suggested_fix if spec is not None else None
    if native is None:
        return None
    return SuggestedFix(
        kind=native.kind,
        target=native.target,
        anchor_ref=native.anchor_ref,
        text_template=native.text_template,
        rationale=native.rationale,
    )


def _type_name(value: Any) -> str:
    cls = type(value)
    return "{}.{}".format(cls.__module__, cls.__name__)


def _search_text(item: DiagnosticItem) -> str:
    parts = [
        item.source_kind.value,
        item.source_uri,
        item.code or "",
        item.severity or "",
        item.message,
        item.raw_message or "",
        item.offending_symbol_text or "",
        item.provenance,
    ]
    parts.extend(_flatten_text(item.refs))
    return "\n".join(parts).casefold()


def _flatten_text(value: Any) -> Iterable[str]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        result = []
        for key, item in value.items():
            result.append(str(key))
            result.extend(_flatten_text(item))
        return tuple(result)
    if isinstance(value, (tuple, list, set, frozenset)):
        result = []
        for item in value:
            result.extend(_flatten_text(item))
        return tuple(result)
    return (str(value),)


__all__ = [
    "DiagnosticItem",
    "DiagnosticQuery",
    "DiagnosticReport",
    "DiagnosticService",
    "DiagnosticSourceKind",
    "DiagnosticSpan",
    "SuggestedFix",
]
