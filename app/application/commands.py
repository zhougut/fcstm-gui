from dataclasses import dataclass, replace
from typing import Dict, List, Optional

from app.application.document import (
    DocumentService,
    StaleTextEditError,
    TextTransaction,
)
from app.model.session import DocumentSession, ValidationState


_DETACHED_SAVED_REVISION = -1


class CommandStateError(RuntimeError):
    pass


def _same_command_source(left: DocumentSession, right: DocumentSession) -> bool:
    return (
        left.session_id == right.session_id
        and left.source_text == right.source_text
    )


def _restore_and_validate(
    service: DocumentService,
    current: DocumentSession,
    source_text: str,
) -> DocumentSession:
    preserve_stale = current.validation_state is ValidationState.STALE_DEPENDENCY
    stale_diagnostics = current.current_diagnostics
    # A command may be textually idempotent.  Even then, traversing history
    # must issue a fresh revision so an asynchronous result stamped before
    # the traversal can never match the restored state by accident.
    restored = service.validate(current.with_source_text(source_text))
    if preserve_stale and restored.validation_state in {
        ValidationState.VALID,
        ValidationState.VALID_WITH_WARNINGS,
    }:
        # Undo/redo is a source operation, not an explicit acknowledgement
        # that a previously stale dependency is current again.  Retain the
        # freshly-built snapshot as the last valid one, but keep the gate
        # closed until the normal dependency revalidation flow clears it.
        return replace(
            restored,
            validation_state=ValidationState.STALE_DEPENDENCY,
            validated_revision=None,
            current_diagnostics=stale_diagnostics,
        )
    return restored


@dataclass(frozen=True)
class TextTransactionCommand:
    transaction: TextTransaction
    before_session: DocumentSession
    after_session: DocumentSession

    def restore_before(
        self,
        current: DocumentSession,
        service: DocumentService,
    ) -> DocumentSession:
        if not _same_command_source(current, self.after_session):
            raise CommandStateError(
                "current source does not match the command result"
            )
        try:
            before_text = self.transaction.apply_inverse(current.source_text)
        except StaleTextEditError as error:
            raise CommandStateError(str(error)) from error
        if before_text != self.before_session.source_text:
            raise CommandStateError(
                "inverse result does not match the command base source"
            )
        return _restore_and_validate(
            service,
            current,
            before_text,
        )

    def restore_after(
        self,
        current: DocumentSession,
        service: DocumentService,
    ) -> DocumentSession:
        if not _same_command_source(current, self.before_session):
            raise CommandStateError(
                "current source does not match the command base"
            )
        if self.transaction.before_text != current.source_text:
            raise CommandStateError(
                "command base text does not match the current source"
            )
        return _restore_and_validate(
            service,
            current,
            self.transaction.after_text,
        )


class DocumentCommandStack:
    def __init__(
        self,
        service: Optional[DocumentService] = None,
        capacity: int = 100,
    ) -> None:
        if capacity <= 0:
            raise ValueError("command stack capacity must be positive")
        self._service = service or DocumentService()
        self._capacity = capacity
        self._undo_commands = []  # type: List[TextTransactionCommand]
        self._redo_commands = []  # type: List[TextTransactionCommand]
        self._saved_source_text = None  # type: Optional[str]
        self._saved_session_id = None  # type: Optional[str]
        self._highest_source_revisions = {}  # type: Dict[str, int]

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_commands)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_commands)

    @property
    def undo_depth(self) -> int:
        return len(self._undo_commands)

    @property
    def redo_depth(self) -> int:
        return len(self._redo_commands)

    def execute(
        self,
        session: DocumentSession,
        transaction: TextTransaction,
    ) -> DocumentSession:
        self._reject_reused_revision(session)
        self._validate_base(session, transaction)
        try:
            inverse_text = transaction.apply_inverse(transaction.after_text)
        except StaleTextEditError as error:
            raise CommandStateError(str(error)) from error
        if inverse_text != transaction.before_text:
            raise CommandStateError(
                "inverse result does not match the transaction base source"
            )

        candidate = self._service.apply_edits(
            session,
            transaction.forward_edits,
        )
        if (
            candidate.source_revision != transaction.target_source_revision
            or candidate.source_text != transaction.after_text
        ):
            raise CommandStateError(
                "forward result does not match the transaction target source"
            )

        self._observe_saved_source(session)
        candidate = self._preserve_dirty_semantics(candidate)
        command = TextTransactionCommand(
            transaction=transaction,
            before_session=session,
            after_session=candidate,
        )

        new_undo = self._undo_commands + [command]
        if len(new_undo) > self._capacity:
            new_undo = new_undo[-self._capacity:]
        self._record_revision(candidate)
        self._undo_commands = new_undo
        self._redo_commands = []
        return candidate

    def undo(self, session: DocumentSession) -> DocumentSession:
        if not self._undo_commands:
            raise CommandStateError("nothing to undo")
        self._reject_reused_revision(session)
        command = self._undo_commands[-1]
        restored = command.restore_before(session, self._service)
        self._observe_saved_source(session)
        restored = self._preserve_dirty_semantics(restored)

        self._record_revision(restored)
        self._undo_commands = self._undo_commands[:-1]
        self._redo_commands = self._redo_commands + [command]
        return restored

    def redo(self, session: DocumentSession) -> DocumentSession:
        if not self._redo_commands:
            raise CommandStateError("nothing to redo")
        self._reject_reused_revision(session)
        command = self._redo_commands[-1]
        restored = command.restore_after(session, self._service)
        self._observe_saved_source(session)
        restored = self._preserve_dirty_semantics(restored)

        self._record_revision(restored)
        self._redo_commands = self._redo_commands[:-1]
        self._undo_commands = self._undo_commands + [command]
        return restored

    def clear(self) -> None:
        """Discard form-command history while retaining document identity."""
        self._undo_commands = []
        self._redo_commands = []

    def mark_saved(self, session: DocumentSession) -> DocumentSession:
        """Record the disk baseline after ``DocumentService.save`` succeeds."""
        if session.dirty:
            raise CommandStateError(
                "cannot mark a session that is still dirty as saved"
            )
        if (
            self._saved_session_id is not None
            and self._saved_session_id != session.session_id
        ):
            raise CommandStateError(
                "saved session belongs to another document; reset it first"
            )
        self._saved_session_id = session.session_id
        self._saved_source_text = session.source_text
        self._observe_revision(session)
        return session

    def reset_document(self, session: DocumentSession) -> DocumentSession:
        """Start command tracking for a newly loaded, clean document."""
        if session.dirty:
            raise CommandStateError(
                "cannot reset command tracking from a session that is still dirty"
            )
        self.clear()
        self._saved_session_id = session.session_id
        self._saved_source_text = session.source_text
        self._highest_source_revisions = {}
        self._observe_revision(session)
        return session

    @staticmethod
    def _validate_base(
        session: DocumentSession,
        transaction: TextTransaction,
    ) -> None:
        if (
            session.source_revision != transaction.base_source_revision
            or session.source_text != transaction.before_text
        ):
            raise CommandStateError(
                "transaction base source does not match the current source"
            )
        if transaction.target_source_revision != session.source_revision + 1:
            raise CommandStateError(
                "transaction target revision does not follow its base revision"
            )

    def _observe_saved_source(self, session: DocumentSession) -> None:
        if self._saved_session_id is None and not session.dirty:
            self._saved_session_id = session.session_id
            self._saved_source_text = session.source_text

    def _observe_revision(self, session: DocumentSession) -> None:
        highest = self._highest_source_revisions.get(session.session_id, -1)
        self._highest_source_revisions[session.session_id] = max(
            highest,
            session.source_revision,
        )

    def _reject_reused_revision(self, session: DocumentSession) -> None:
        highest = self._highest_source_revisions.get(session.session_id)
        if highest is not None and session.source_revision < highest:
            raise CommandStateError(
                "current source revision is older than an issued revision"
            )

    def _record_revision(self, session: DocumentSession) -> None:
        highest = self._highest_source_revisions.get(session.session_id, -1)
        if session.source_revision <= highest:
            raise CommandStateError("source revision was already issued")
        self._highest_source_revisions[session.session_id] = session.source_revision

    def _preserve_dirty_semantics(
        self,
        session: DocumentSession,
    ) -> DocumentSession:
        if (
            self._saved_session_id == session.session_id
            and self._saved_source_text is not None
            and session.source_text == self._saved_source_text
        ):
            return replace(session, saved_revision=session.source_revision)
        if (
            self._saved_session_id == session.session_id
            and self._saved_source_text is not None
            and session.source_revision == session.saved_revision
        ):
            # Revisions are non-negative. This sentinel means the disk text
            # belongs to a truncated branch, so equality must not imply clean.
            return replace(
                session,
                saved_revision=_DETACHED_SAVED_REVISION,
            )
        return session


__all__ = [
    "CommandStateError",
    "DocumentCommandStack",
    "TextTransactionCommand",
]
