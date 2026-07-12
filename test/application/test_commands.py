from dataclasses import replace

import pytest

from app.application.commands import (
    CommandStateError,
    DocumentCommandStack,
)
from app.application.document import (
    DocumentService,
    DocumentValidationError,
    TextEdit,
    TextTransaction,
)
from app.model.session import ValidationState


VALID_SOURCE = """\
state Root {
    state A;
    [*] -> A;
    A -> [*];
}
"""


def _rename_transaction(service, session, old_name, new_name):
    index = session.require_current_valid_snapshot().source_index
    state_ref = next(
        item
        for item in index.refs(kind="state")
        if item.owner_path == ("Root", old_name)
    )
    transition_refs = tuple(
        item
        for item in index.refs(kind="transition")
        if old_name in index.text_for_ref(item)
    )
    edits = [
        TextEdit.for_ref(
            session.source_revision,
            state_ref,
            "state {};".format(new_name),
            intent="rename state",
        )
    ]
    for ref in transition_refs:
        edits.append(
            TextEdit.for_ref(
                session.source_revision,
                ref,
                index.text_for_ref(ref).replace(old_name, new_name),
                intent="rename transition endpoint",
            )
        )
    return service.preview_edits(session, edits)


@pytest.fixture
def document(tmp_path):
    path = tmp_path / "commands.fcstm"
    path.write_text(VALID_SOURCE, encoding="utf-8")
    service = DocumentService()
    return service, service.load(path)


@pytest.mark.unittest
def test_execute_undo_redo_restore_source_with_fresh_revision_and_snapshot(document):
    service, original = document
    stack = DocumentCommandStack(service=service)
    transaction = _rename_transaction(service, original, "A", "Ready")

    changed = stack.execute(original, transaction)

    assert changed.source_revision == transaction.target_source_revision == 1
    assert changed.source_text == transaction.after_text
    assert changed.current_valid_snapshot.source_revision == 1
    assert (
        changed.current_valid_snapshot.source_index.root_document.text
        == changed.source_text
    )
    assert changed.dirty
    assert stack.can_undo
    assert not stack.can_redo

    undone = stack.undo(changed)

    assert undone.source_revision == 2
    assert undone.source_text == original.source_text
    assert undone.current_valid_snapshot is not original.current_valid_snapshot
    assert undone.current_valid_snapshot.source_revision == 2
    assert (
        undone.current_valid_snapshot.source_index.root_document.text
        == original.source_text
    )
    assert not undone.dirty
    assert not stack.can_undo
    assert stack.can_redo

    redone = stack.redo(undone)

    assert redone.source_revision == 3
    assert redone.source_text == changed.source_text
    assert redone.current_valid_snapshot is not changed.current_valid_snapshot
    assert redone.current_valid_snapshot.source_revision == 3
    assert redone.dirty


@pytest.mark.unittest
def test_successful_new_command_after_undo_truncates_redo_branch(document):
    service, original = document
    stack = DocumentCommandStack(service=service)
    ready = stack.execute(
        original, _rename_transaction(service, original, "A", "Ready")
    )
    restored = stack.undo(ready)

    running = stack.execute(
        restored, _rename_transaction(service, restored, "A", "Running")
    )

    assert "state Running;" in running.source_text
    assert (
        ready.source_revision,
        restored.source_revision,
        running.source_revision,
    ) == (1, 2, 3)
    assert not stack.can_redo
    with pytest.raises(CommandStateError, match="nothing to redo"):
        stack.redo(running)


@pytest.mark.unittest
def test_capacity_discards_oldest_command_without_breaking_recent_history(document):
    service, original = document
    stack = DocumentCommandStack(service=service, capacity=2)
    first = stack.execute(
        original, _rename_transaction(service, original, "A", "B")
    )
    second = stack.execute(first, _rename_transaction(service, first, "B", "C"))
    third = stack.execute(second, _rename_transaction(service, second, "C", "D"))

    assert stack.undo_depth == 2
    assert stack.undo(stack.undo(third)).source_text == first.source_text
    assert not stack.can_undo


@pytest.mark.unittest
def test_historical_session_cannot_reuse_a_revision_after_undo(document):
    service, original = document
    stack = DocumentCommandStack(service=service)
    transaction = _rename_transaction(service, original, "A", "Ready")
    changed = stack.execute(original, transaction)
    restored = stack.undo(changed)

    with pytest.raises(CommandStateError, match="older than an issued revision"):
        stack.execute(original, transaction)

    assert restored.source_revision == 2
    assert (stack.undo_depth, stack.redo_depth) == (0, 1)


@pytest.mark.unittest
def test_noop_transaction_still_issues_unique_undo_and_redo_revisions(document):
    service, original = document
    stack = DocumentCommandStack(service=service)
    unchanged = stack.execute(
        original, _rename_transaction(service, original, "A", "A")
    )

    restored = stack.undo(unchanged)
    redone = stack.redo(restored)

    assert unchanged.source_text == restored.source_text == redone.source_text
    assert (
        unchanged.source_revision,
        restored.source_revision,
        redone.source_revision,
    ) == (1, 2, 3)


@pytest.mark.unittest
def test_undo_revalidates_on_current_session_and_preserves_metadata_and_stale_state(
    document,
):
    service, original = document
    stack = DocumentCommandStack(service=service)
    changed = stack.execute(
        original, _rename_transaction(service, original, "A", "Ready")
    )
    stale = replace(
        changed.mark_stale_dependency("dependency changed"),
        task_ids=("load-7", "inspect-8"),
        encoding_hints=(("/imports/child.fcstm", "gb18030"),),
    )

    restored = stack.undo(stale)

    assert restored.source_revision == 2
    assert restored.source_text == original.source_text
    assert restored.task_ids == stale.task_ids
    assert restored.encoding_hints == stale.encoding_hints
    assert restored.validation_state is ValidationState.STALE_DEPENDENCY
    assert restored.validated_revision is None
    assert restored.current_valid_snapshot is None
    assert restored.current_diagnostics == stale.current_diagnostics
    # A fresh validation did run; its snapshot is retained only as the last
    # valid snapshot until an explicit dependency revalidation clears stale.
    assert restored.last_valid_snapshot.source_revision == restored.source_revision
    assert restored.last_valid_snapshot is not original.last_valid_snapshot

    latest = replace(
        restored,
        task_ids=("latest-task",),
        encoding_hints=(("/imports/latest.fcstm", "utf-16"),),
    )
    redone = stack.redo(latest)

    assert redone.source_revision == 3
    assert redone.source_text == changed.source_text
    assert redone.task_ids == latest.task_ids
    assert redone.encoding_hints == latest.encoding_hints
    assert redone.validation_state is ValidationState.STALE_DEPENDENCY
    assert redone.current_diagnostics == latest.current_diagnostics
    assert redone.last_valid_snapshot.source_revision == redone.source_revision


@pytest.mark.unittest
def test_failed_execute_undo_and_redo_leave_both_stacks_unchanged(document):
    service, original = document
    stack = DocumentCommandStack(service=service)
    transaction = _rename_transaction(service, original, "A", "Ready")

    stale = original.with_source_text(original.source_text)
    with pytest.raises(CommandStateError, match="base source"):
        stack.execute(stale, transaction)
    assert (stack.undo_depth, stack.redo_depth) == (0, 0)

    changed = stack.execute(original, transaction)
    unrelated = changed.with_source_text(changed.source_text + "\n")
    with pytest.raises(CommandStateError, match="current source"):
        stack.undo(unrelated)
    assert (stack.undo_depth, stack.redo_depth) == (1, 0)

    restored = stack.undo(changed)
    unrelated = restored.with_source_text(restored.source_text + "\n")
    with pytest.raises(CommandStateError, match="current source"):
        stack.redo(unrelated)
    assert (stack.undo_depth, stack.redo_depth) == (0, 1)


@pytest.mark.unittest
def test_invalid_forward_or_inverse_transaction_does_not_mutate_history(document):
    service, original = document
    stack = DocumentCommandStack(service=service)
    valid = _rename_transaction(service, original, "A", "Ready")
    inconsistent = TextTransaction(
        base_source_revision=valid.base_source_revision,
        target_source_revision=valid.target_source_revision,
        before_text=valid.before_text,
        after_text=valid.after_text + "\n",
        forward_edits=valid.forward_edits,
        inverse_edits=valid.inverse_edits,
    )

    with pytest.raises(CommandStateError, match="inverse result"):
        stack.execute(original, inconsistent)

    assert (stack.undo_depth, stack.redo_depth) == (0, 0)


@pytest.mark.unittest
def test_full_validation_failure_does_not_commit_command(document):
    service, original = document
    stack = DocumentCommandStack(service=service)
    index = original.require_current_valid_snapshot().source_index
    state_ref = next(
        item
        for item in index.refs(kind="state")
        if item.owner_path == ("Root", "A")
    )
    invalid = TextEdit.for_ref(
        original.source_revision,
        state_ref,
        "state ;",
    )
    transaction = service.preview_edits(original, (invalid,))

    with pytest.raises(DocumentValidationError):
        stack.execute(original, transaction)

    assert original.source_revision == 0
    assert original.source_text == VALID_SOURCE
    assert (stack.undo_depth, stack.redo_depth) == (0, 0)


@pytest.mark.unittest
def test_save_then_undo_and_branch_keep_dirty_semantics(document):
    service, original = document
    stack = DocumentCommandStack(service=service)
    changed = stack.execute(
        original, _rename_transaction(service, original, "A", "Ready")
    )
    saved = service.save(changed)
    stack.mark_saved(saved)

    restored = stack.undo(saved)

    assert restored.source_revision == 2
    assert restored.saved_revision == 1
    assert restored.dirty

    branch = stack.execute(
        restored, _rename_transaction(service, restored, "A", "Running")
    )

    assert branch.source_revision == 3
    assert "state Running;" in branch.source_text
    assert branch.dirty
    assert branch.saved_revision != branch.source_revision


@pytest.mark.unittest
def test_saved_baseline_survives_direct_edit_clear_and_form_edit_back_to_original(
    document,
):
    service, original = document
    stack = DocumentCommandStack(service=service)
    form_changed = stack.execute(
        original, _rename_transaction(service, original, "A", "Ready")
    )
    saved = service.save(form_changed)
    stack.mark_saved(saved)

    direct_changed = service.validate(
        saved.with_source_text(
            saved.source_text.replace("state Ready;", "state Running;").replace(
                "-> Ready", "-> Running"
            ).replace("Ready ->", "Running ->")
        )
    )
    stack.clear()
    restored_original = stack.execute(
        direct_changed,
        _rename_transaction(service, direct_changed, "Running", "A"),
    )

    assert restored_original.source_text == original.source_text
    assert restored_original.source_revision == 3
    assert restored_original.saved_revision != restored_original.source_revision
    assert restored_original.dirty


@pytest.mark.unittest
def test_mark_saved_requires_the_session_returned_by_a_successful_save(document):
    service, original = document
    stack = DocumentCommandStack(service=service)
    changed = stack.execute(
        original, _rename_transaction(service, original, "A", "Ready")
    )

    with pytest.raises(CommandStateError, match="still dirty"):
        stack.mark_saved(changed)

    assert stack.undo_depth == 1
    assert stack.redo_depth == 0


@pytest.mark.unittest
def test_reset_document_replaces_baseline_and_releases_old_revision_history(
    document, tmp_path
):
    service, original = document
    stack = DocumentCommandStack(service=service)
    changed = stack.execute(
        original, _rename_transaction(service, original, "A", "Ready")
    )
    saved = service.save(changed)
    stack.mark_saved(saved)

    other_path = tmp_path / "other.fcstm"
    other_path.write_text(VALID_SOURCE, encoding="utf-8")
    other = service.load(other_path)
    stack.reset_document(other)

    assert not stack.can_undo
    assert not stack.can_redo
    assert original.session_id not in stack._highest_source_revisions
    other_changed = stack.execute(
        other, _rename_transaction(service, other, "A", "Other")
    )
    assert other_changed.dirty
    assert not stack.undo(other_changed).dirty

    # Resetting is the document-lifecycle boundary. Returning to a newly
    # loaded incarnation of the old path must not inherit its old high-water.
    reloaded_original = service.load(original.path)
    stack.reset_document(reloaded_original)
    changed_again = stack.execute(
        reloaded_original,
        _rename_transaction(service, reloaded_original, "Ready", "Running"),
    )

    assert changed_again.source_revision == 1
    assert changed_again.dirty


@pytest.mark.unittest
def test_reset_document_rejects_dirty_session_without_mutating_existing_state(
    document,
):
    service, original = document
    stack = DocumentCommandStack(service=service)
    changed = stack.execute(
        original, _rename_transaction(service, original, "A", "Ready")
    )

    with pytest.raises(CommandStateError, match="still dirty"):
        stack.reset_document(changed)

    assert stack.undo_depth == 1
    assert stack.redo_depth == 0


@pytest.mark.unittest
def test_capacity_must_be_positive(document):
    service, _ = document

    with pytest.raises(ValueError, match="capacity"):
        DocumentCommandStack(service=service, capacity=0)
