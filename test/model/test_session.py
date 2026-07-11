import pytest
from dataclasses import FrozenInstanceError

from app.model.session import (
    DocumentSession,
    ValidationState,
    ValidSnapshotRequiredError,
)


@pytest.mark.unittest
def test_document_session_tracks_dirty_saved_and_validated_revisions(tmp_path):
    session = DocumentSession.new(
        path=str(tmp_path / "machine.fcstm"),
        encoding="utf-8",
        source_text="state Root;",
    )

    assert session.source_revision == 0
    assert session.saved_revision == 0
    assert session.validated_revision is None
    assert session.validation_state is ValidationState.PENDING
    assert not session.dirty

    changed = session.with_source_text("state Changed;", validation_state=ValidationState.PENDING)
    assert changed.source_revision == 1
    assert changed.saved_revision == 0
    assert changed.validated_revision is None
    assert changed.dirty

    saved = changed.mark_saved()
    assert saved.saved_revision == saved.source_revision
    assert not saved.dirty


@pytest.mark.unittest
@pytest.mark.parametrize("state", list(ValidationState))
def test_all_six_validation_states_are_stable_enum_values(state):
    assert ValidationState(state.value) is state


@pytest.mark.unittest
def test_invalid_current_revision_never_exposes_last_valid_snapshot(tmp_path):
    session = DocumentSession.new(
        path=str(tmp_path / "machine.fcstm"),
        encoding="utf-8",
        source_text="state Root;",
    )
    invalid = session.with_source_text(
        "state Root {",
        validation_state=ValidationState.INVALID_SYNTAX,
        diagnostics=("syntax",),
    )

    with pytest.raises(ValidSnapshotRequiredError, match="current revision"):
        invalid.require_current_valid_snapshot()


@pytest.mark.unittest
def test_session_source_truth_cannot_be_mutated_behind_the_revision_gate(tmp_path):
    session = DocumentSession.new(
        path=str(tmp_path / "machine.fcstm"),
        encoding="utf-8",
        source_text="state Root;",
    )

    with pytest.raises(FrozenInstanceError):
        session.source_text = "state Broken {"


@pytest.mark.unittest
def test_validation_state_cannot_claim_valid_without_a_matching_snapshot(tmp_path):
    session = DocumentSession.new(
        path=str(tmp_path / "machine.fcstm"),
        encoding="utf-8",
        source_text="state Root;",
    )

    with pytest.raises(ValueError, match="requires a snapshot"):
        session.with_validation(ValidationState.VALID, (), None)
