import uuid
from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Any, Optional, Tuple

from app.source import SourceIndex, canonical_path


class ValidationState(Enum):
    PENDING = "pending"
    VALID = "valid"
    VALID_WITH_WARNINGS = "valid_with_warnings"
    INVALID_SYNTAX = "invalid_syntax"
    INVALID_MODEL = "invalid_model"
    STALE_DEPENDENCY = "stale_dependency"


class ValidSnapshotRequiredError(RuntimeError):
    pass


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class ValidSnapshot:
    source_revision: int
    model: Any
    inspect_report: Any
    source_index: SourceIndex
    dependency_fingerprint: str
    dependency_manifest: Tuple[Tuple[str, str], ...]
    ui_projection: Any = None

    def __post_init__(self) -> None:
        if self.source_index.root_document.revision != self.source_revision:
            raise ValueError("source index revision does not match the snapshot")
        if self.dependency_manifest != self.source_index.dependency_manifest:
            raise ValueError("dependency manifest does not match the source index")
        if self.dependency_fingerprint != self.source_index.dependency_fingerprint:
            raise ValueError("dependency fingerprint does not match the source index")
        object.__setattr__(self, "inspect_report", _freeze(self.inspect_report))


@dataclass(frozen=True)
class DocumentSession:
    session_id: str
    path: str
    encoding: str
    source_text: str
    source_revision: int
    saved_revision: int
    validation_state: ValidationState
    validated_revision: Optional[int] = None
    last_valid_snapshot: Optional[ValidSnapshot] = None
    current_diagnostics: Tuple[Any, ...] = ()
    diagnostic_source_kind: Optional[str] = None
    task_ids: Tuple[str, ...] = ()
    encoding_hints: Tuple[Tuple[str, str], ...] = ()
    document_version: int = 0

    def __post_init__(self) -> None:
        valid = self.validation_state in {
            ValidationState.VALID,
            ValidationState.VALID_WITH_WARNINGS,
        }
        snapshot = self.last_valid_snapshot
        current_snapshot = snapshot is not None and (
            self.validated_revision == self.source_revision
            and snapshot.source_revision == self.source_revision
            and snapshot.source_index.root_document.text == self.source_text
            and snapshot.source_index.root_document.path
            == str(canonical_path(self.path))
            and snapshot.source_index.root_document.encoding == self.encoding
        )
        if valid and not current_snapshot:
            raise ValueError(
                "validation state and current valid snapshot are inconsistent"
            )
        if not valid and self.validated_revision is not None:
            raise ValueError(
                "non-valid document session cannot have a validated revision"
            )

    @classmethod
    def new(
        cls,
        path: str,
        encoding: str,
        source_text: str,
        encoding_hints: Tuple[Tuple[str, str], ...] = (),
    ) -> "DocumentSession":
        return cls(
            session_id=uuid.uuid4().hex,
            path=path,
            encoding=encoding,
            source_text=source_text,
            source_revision=0,
            saved_revision=0,
            validation_state=ValidationState.PENDING,
            encoding_hints=tuple(encoding_hints),
        )

    @property
    def id(self) -> str:
        return self.session_id

    @property
    def dirty(self) -> bool:
        return self.source_revision != self.saved_revision

    @property
    def current_valid_snapshot(self) -> Optional[ValidSnapshot]:
        snapshot = self.last_valid_snapshot
        if (
            self.validation_state
            not in {ValidationState.VALID, ValidationState.VALID_WITH_WARNINGS}
            or snapshot is None
            or self.validated_revision != self.source_revision
            or snapshot.source_revision != self.source_revision
        ):
            return None
        return snapshot

    def with_source_text(
        self,
        source_text: str,
        validation_state: ValidationState = ValidationState.PENDING,
        diagnostics: Tuple[Any, ...] = (),
    ) -> "DocumentSession":
        next_document_version = (
            self.document_version if self.dirty else self.document_version + 1
        )
        return replace(
            self,
            source_text=source_text,
            source_revision=self.source_revision + 1,
            document_version=next_document_version,
            validation_state=validation_state,
            validated_revision=None,
            current_diagnostics=tuple(diagnostics),
            diagnostic_source_kind=None,
        )

    def with_validation(
        self,
        state: ValidationState,
        diagnostics: Tuple[Any, ...],
        snapshot: Optional[ValidSnapshot],
        diagnostic_source_kind: Optional[str] = None,
    ) -> "DocumentSession":
        is_valid = state in {
            ValidationState.VALID,
            ValidationState.VALID_WITH_WARNINGS,
        }
        if is_valid and snapshot is None:
            raise ValueError("valid validation state requires a snapshot")
        if not is_valid and snapshot is not None:
            raise ValueError("invalid validation state cannot accept a new snapshot")
        return replace(
            self,
            validation_state=state,
            validated_revision=self.source_revision if is_valid else None,
            last_valid_snapshot=snapshot if is_valid else self.last_valid_snapshot,
            current_diagnostics=tuple(diagnostics),
            diagnostic_source_kind=diagnostic_source_kind,
        )

    def mark_saved(self) -> "DocumentSession":
        return replace(self, saved_revision=self.source_revision)

    def require_current_valid_snapshot(self) -> ValidSnapshot:
        snapshot = self.current_valid_snapshot
        if snapshot is None or (
            snapshot.source_index.root_document.text != self.source_text
            or snapshot.source_index.root_document.path
            != str(canonical_path(self.path))
            or snapshot.source_index.root_document.encoding != self.encoding
        ):
            raise ValidSnapshotRequiredError(
                "current revision does not have a valid snapshot"
            )
        return snapshot

    def mark_stale_dependency(self, diagnostic) -> "DocumentSession":
        return replace(
            self,
            validation_state=ValidationState.STALE_DEPENDENCY,
            validated_revision=None,
            current_diagnostics=(diagnostic,),
            diagnostic_source_kind="model",
        )
