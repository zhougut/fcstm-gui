import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Tuple

from pyfcstm.diagnostics import inspect_model
from pyfcstm.dsl.error import GrammarParseError, SyntaxFailError
from pyfcstm.model import load_state_machine_from_text
from pyfcstm.utils.validate import ModelValidationError

from app.model.session import (
    DocumentSession,
    ValidationState,
    ValidSnapshot,
    ValidSnapshotRequiredError,
)
from app.source import (
    InsertionAnchor,
    SourceDocument,
    SourceIndex,
    SourceIndexError,
    SourceRef,
    StaleSourceRefError,
    canonical_path,
    load_text_with_source_index,
)


class DocumentError(RuntimeError):
    pass


class StaleTextEditError(DocumentError):
    pass


class OverlappingTextEditError(DocumentError):
    pass


class InvalidDocumentSaveError(DocumentError):
    pass


class DocumentDependencyStaleError(DocumentError):
    def __init__(self, session: DocumentSession):
        super().__init__(
            "source dependency fingerprint changed; revalidation is required"
        )
        self.session = session


class DocumentValidationError(DocumentError):
    def __init__(self, candidate: DocumentSession):
        super().__init__(
            "candidate source is not valid: {}".format(
                candidate.validation_state.value
            )
        )
        self.candidate = candidate


@dataclass(frozen=True)
class TextEdit:
    base_source_revision: int
    start_offset: int
    end_offset: int
    replacement_text: str
    intent: str = "edit"
    source_ref: Optional[SourceRef] = None
    insertion_anchor: Optional[InsertionAnchor] = None

    @classmethod
    def for_ref(
        cls,
        base_source_revision: int,
        source_ref: SourceRef,
        replacement_text: str,
        intent: str = "edit",
    ) -> "TextEdit":
        return cls(
            base_source_revision=base_source_revision,
            start_offset=source_ref.span.start_offset,
            end_offset=source_ref.span.end_offset,
            replacement_text=replacement_text,
            intent=intent,
            source_ref=source_ref,
        )

    @classmethod
    def for_anchor(
        cls,
        base_source_revision: int,
        insertion_anchor: InsertionAnchor,
        replacement_text: str,
        intent: str = "insert",
    ) -> "TextEdit":
        return cls(
            base_source_revision=base_source_revision,
            start_offset=insertion_anchor.offset,
            end_offset=insertion_anchor.offset,
            replacement_text=replacement_text,
            intent=intent,
            insertion_anchor=insertion_anchor,
        )


@dataclass(frozen=True)
class AppliedTextEdit:
    start_offset: int
    end_offset: int
    replacement_text: str


@dataclass(frozen=True)
class TextTransaction:
    base_source_revision: int
    target_source_revision: int
    before_text: str
    after_text: str
    forward_edits: Tuple[TextEdit, ...]
    inverse_edits: Tuple[AppliedTextEdit, ...]

    def apply_inverse(self, text: str) -> str:
        if text != self.after_text:
            raise StaleTextEditError("inverse transaction input is stale")
        result = text
        for edit in sorted(
            self.inverse_edits, key=lambda item: item.start_offset, reverse=True
        ):
            result = (
                result[:edit.start_offset]
                + edit.replacement_text
                + result[edit.end_offset:]
            )
        return result


def _diagnostics_for_exception(error: BaseException) -> Tuple[Any, ...]:
    diagnostics = getattr(error, "diagnostics", None)
    if diagnostics:
        return tuple(diagnostics)
    errors = getattr(error, "errors", None)
    if errors:
        return tuple(errors)
    return (error,)


class DocumentService:
    def load(
        self,
        path,
        encoding: Optional[str] = None,
        encoding_hints: Tuple[Tuple[str, str], ...] = (),
    ) -> DocumentSession:
        document = SourceDocument.from_file(path, revision=0, encoding=encoding)
        session = DocumentSession.new(
            path=document.path,
            encoding=document.encoding,
            source_text=document.text,
            encoding_hints=tuple(
                (str(canonical_path(item_path)), item_encoding)
                for item_path, item_encoding in encoding_hints
            ),
        )
        return self._validate(session)

    def replace_source_text(
        self, session: DocumentSession, source_text: str
    ) -> DocumentSession:
        if source_text == session.source_text:
            return session
        return self.validate(self.prepare_source_text(session, source_text))

    def prepare_source_text(
        self, session: DocumentSession, source_text: str
    ) -> DocumentSession:
        if source_text == session.source_text:
            return session
        return session.with_source_text(source_text)

    def validate(self, session: DocumentSession) -> DocumentSession:
        return self._validate(session)

    def preview_edits(
        self, session: DocumentSession, edits: Iterable[TextEdit]
    ) -> TextTransaction:
        ordered = tuple(sorted(tuple(edits), key=lambda item: item.start_offset))
        if not ordered:
            raise ValueError("at least one text edit is required")
        if any(
            edit.base_source_revision != session.source_revision for edit in ordered
        ):
            raise StaleTextEditError("text edit revision is stale")
        snapshot = session.require_current_valid_snapshot()
        index = snapshot.source_index
        previous = None
        for edit in ordered:
            self._validate_edit(session, index, edit)
            if previous is not None and (
                edit.start_offset < previous.end_offset
                or edit.start_offset == previous.start_offset
            ):
                raise OverlappingTextEditError("text edit ranges overlap")
            previous = edit

        after = session.source_text
        for edit in reversed(ordered):
            after = (
                after[:edit.start_offset]
                + edit.replacement_text
                + after[edit.end_offset:]
            )

        inverse = []
        delta = 0
        for edit in ordered:
            start = edit.start_offset + delta
            inverse.append(
                AppliedTextEdit(
                    start_offset=start,
                    end_offset=start + len(edit.replacement_text),
                    replacement_text=session.source_text[
                        edit.start_offset:edit.end_offset
                    ],
                )
            )
            delta += len(edit.replacement_text) - (
                edit.end_offset - edit.start_offset
            )
        return TextTransaction(
            base_source_revision=session.source_revision,
            target_source_revision=session.source_revision + 1,
            before_text=session.source_text,
            after_text=after,
            forward_edits=ordered,
            inverse_edits=tuple(inverse),
        )

    def apply_edits(
        self, session: DocumentSession, edits: Iterable[TextEdit]
    ) -> DocumentSession:
        transaction = self.preview_edits(session, edits)
        candidate = self._validate(
            session.with_source_text(transaction.after_text)
        )
        if candidate.validation_state not in {
            ValidationState.VALID,
            ValidationState.VALID_WITH_WARNINGS,
        }:
            raise DocumentValidationError(candidate)
        return candidate

    def require_current_valid_snapshot(
        self, session: DocumentSession
    ) -> ValidSnapshot:
        try:
            snapshot = session.require_current_valid_snapshot()
        except ValidSnapshotRequiredError as error:
            raise DocumentValidationError(session) from error
        if not snapshot.source_index.matches_dependencies_on_disk():
            raise DocumentDependencyStaleError(
                session.mark_stale_dependency(
                    "source dependency fingerprint changed"
                )
            )
        return snapshot

    def save(
        self, session: DocumentSession, allow_invalid: bool = False
    ) -> DocumentSession:
        checked = self._validate(session)
        valid = checked.validation_state in {
            ValidationState.VALID,
            ValidationState.VALID_WITH_WARNINGS,
        }
        if not valid and not allow_invalid:
            raise InvalidDocumentSaveError(
                "invalid or stale source requires explicit confirmation"
            )
        raw = checked.source_text.encode(checked.encoding)
        target = Path(checked.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        original_mode = None
        if target.exists():
            original_mode = stat.S_IMODE(target.stat().st_mode)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".{}-".format(target.name),
            suffix=".tmp",
            dir=str(target.parent),
        )
        try:
            with os.fdopen(descriptor, "wb") as file:
                file.write(raw)
                file.flush()
                os.fsync(file.fileno())
            if original_mode is not None:
                os.chmod(temporary, original_mode)
            os.replace(temporary, str(target))
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        return checked.mark_saved()

    def _validate_edit(
        self, session: DocumentSession, index: SourceIndex, edit: TextEdit
    ) -> None:
        if edit.base_source_revision != session.source_revision:
            raise StaleTextEditError("text edit revision is stale")
        if (edit.source_ref is None) == (edit.insertion_anchor is None):
            raise StaleTextEditError(
                "text edit requires exactly one source ref or insertion anchor"
            )
        try:
            if edit.source_ref is not None:
                index.text_for_ref(edit.source_ref)
                if (
                    edit.start_offset != edit.source_ref.span.start_offset
                    or edit.end_offset != edit.source_ref.span.end_offset
                    or not edit.source_ref.editable
                ):
                    raise StaleTextEditError(
                        "text edit range is not the authorized source ref"
                    )
            else:
                index.validate_insertion_anchor(edit.insertion_anchor)
                if (
                    edit.start_offset != edit.insertion_anchor.offset
                    or edit.end_offset != edit.insertion_anchor.offset
                ):
                    raise StaleTextEditError(
                        "text edit range is not the authorized insertion anchor"
                    )
        except StaleSourceRefError as error:
            raise StaleTextEditError(str(error)) from error

    def _validate(self, session: DocumentSession) -> DocumentSession:
        hints = {
            os.path.normcase(str(canonical_path(path))): encoding
            for path, encoding in session.encoding_hints
        }
        if session.last_valid_snapshot is not None:
            for document in session.last_valid_snapshot.source_index.documents.values():
                if document.path != session.path:
                    hints.setdefault(
                        os.path.normcase(document.path), document.encoding
                    )

        def resolve_encoding(path):
            return hints.get(os.path.normcase(str(canonical_path(path))))

        try:
            index, payload = load_text_with_source_index(
                session.path,
                session.source_text,
                loader=lambda source_index: self._load_and_inspect(
                    source_index.root_document.text,
                    session.path,
                ),
                revision=session.source_revision,
                encoding=session.encoding,
                encoding_resolver=resolve_encoding,
            )
            model, report = payload
        except (GrammarParseError, SyntaxFailError) as error:
            return session.with_validation(
                ValidationState.INVALID_SYNTAX,
                _diagnostics_for_exception(error),
                None,
            )
        except (ModelValidationError, SyntaxError) as error:
            return session.with_validation(
                ValidationState.INVALID_MODEL,
                _diagnostics_for_exception(error),
                None,
            )
        except SourceIndexError as error:
            return session.with_validation(
                ValidationState.STALE_DEPENDENCY,
                _diagnostics_for_exception(error),
                None,
            )

        diagnostics = tuple(report.diagnostics)
        severities = {
            str(getattr(item, "severity", "")).lower()
            for item in diagnostics
        }
        if "error" in severities:
            return session.with_validation(
                ValidationState.INVALID_MODEL, diagnostics, None
            )
        state = (
            ValidationState.VALID_WITH_WARNINGS
            if "warning" in severities
            else ValidationState.VALID
        )
        snapshot = ValidSnapshot(
            source_revision=session.source_revision,
            model=model,
            inspect_report=report.to_json(),
            source_index=index,
            dependency_fingerprint=index.dependency_fingerprint,
            dependency_manifest=index.dependency_manifest,
        )
        return session.with_validation(state, diagnostics, snapshot)

    @staticmethod
    def _load_and_inspect(source_text: str, path: str):
        model = load_state_machine_from_text(source_text, path=path)
        return model, inspect_model(model)
