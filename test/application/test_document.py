import os
from dataclasses import replace
from types import MappingProxyType

import pytest

from app.application.document import (
    DocumentDependencyStaleError,
    DocumentService,
    DocumentValidationError,
    InvalidDocumentSaveError,
    OverlappingTextEditError,
    StaleTextEditError,
    TextEdit,
)
from app.model.session import ValidationState
from app.source import build_source_index


VALID_SOURCE = """\
state Root {
    state A;
    [*] -> A;
    A -> [*];
}
"""


@pytest.mark.unittest
def test_load_valid_document_builds_one_revision_snapshot(tmp_path):
    path = tmp_path / "valid.fcstm"
    path.write_bytes(VALID_SOURCE.encode("utf-8"))

    session = DocumentService().load(path)

    assert session.source_text == VALID_SOURCE
    assert session.validation_state is ValidationState.VALID
    assert session.validated_revision == session.source_revision == 0
    assert session.last_valid_snapshot.source_index.root_document.text == VALID_SOURCE
    assert session.last_valid_snapshot.inspect_report["root_state_path"] == "Root"
    assert isinstance(session.last_valid_snapshot.inspect_report, MappingProxyType)
    assert session.require_current_valid_snapshot().model.root_state.name == "Root"

    object.__setattr__(session, "source_text", "state Forged {")
    with pytest.raises(Exception, match="current revision"):
        session.require_current_valid_snapshot()


@pytest.mark.unittest
def test_load_warning_document_is_valid_with_warnings(tmp_path):
    path = tmp_path / "warning.fcstm"
    path.write_text("state Root;", encoding="utf-8")

    session = DocumentService().load(path)

    assert session.validation_state is ValidationState.VALID_WITH_WARNINGS
    assert session.validated_revision == 0
    assert any(item.severity == "warning" for item in session.current_diagnostics)


@pytest.mark.unittest
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("state Broken { state ; }", ValidationState.INVALID_SYNTAX),
        ("state Root { state A; state A; }", ValidationState.INVALID_MODEL),
    ],
)
def test_invalid_document_opens_as_editable_source_without_snapshot(
    tmp_path, source, expected
):
    path = tmp_path / "invalid.fcstm"
    path.write_text(source, encoding="utf-8")

    session = DocumentService().load(path)

    assert session.source_text == source
    assert session.validation_state is expected
    assert session.validated_revision is None
    assert session.last_valid_snapshot is None
    assert session.current_diagnostics


@pytest.mark.unittest
def test_exact_text_edit_preserves_untouched_source_and_has_inverse(tmp_path):
    path = tmp_path / "edit.fcstm"
    path.write_bytes(VALID_SOURCE.encode("utf-8"))
    service = DocumentService()
    session = service.load(path)
    index = session.last_valid_snapshot.source_index
    ref = next(item for item in index.refs(kind="state") if item.owner_path == ("Root", "A"))
    replacement = "state B;"
    edit = TextEdit.for_ref(session.source_revision, ref, replacement, intent="rename state")

    transaction = service.preview_edits(session, (edit,))

    assert transaction.before_text[:ref.span.start_offset] == transaction.after_text[:ref.span.start_offset]
    assert transaction.before_text[ref.span.end_offset:] == transaction.after_text[ref.span.start_offset + len(replacement):]
    assert transaction.apply_inverse(transaction.after_text) == session.source_text


@pytest.mark.unittest
def test_text_edits_reject_stale_overlap_and_wrong_context(tmp_path):
    path = tmp_path / "edit.fcstm"
    path.write_bytes(VALID_SOURCE.encode("utf-8"))
    service = DocumentService()
    session = service.load(path)
    index = session.last_valid_snapshot.source_index
    ref = next(item for item in index.refs(kind="state") if item.owner_path == ("Root", "A"))
    edit = TextEdit.for_ref(session.source_revision, ref, "state B;")

    with pytest.raises(StaleTextEditError, match="revision"):
        service.preview_edits(session.with_source_text(session.source_text), (edit,))

    duplicate = TextEdit.for_ref(session.source_revision, ref, "state C;")
    with pytest.raises(OverlappingTextEditError):
        service.preview_edits(session, (edit, duplicate))

    variable_source = tmp_path / "variable.fcstm"
    variable_source.write_text("def int old = 0;\n" + VALID_SOURCE, encoding="utf-8")
    variable_session = service.load(variable_source)
    variable_index = variable_session.last_valid_snapshot.source_index
    variable_ref = variable_index.refs(kind="variable")[0]
    variable_anchor = variable_index.insertion_anchor("variable")
    same_start = (
        TextEdit.for_anchor(
            variable_session.source_revision,
            variable_anchor,
            "def int new = 1;\n",
        ),
        TextEdit.for_ref(
            variable_session.source_revision,
            variable_ref,
            "def int changed = 2;",
        ),
    )
    for ordered in (same_start, tuple(reversed(same_start))):
        with pytest.raises(OverlappingTextEditError):
            service.preview_edits(variable_session, ordered)

    different_index = build_source_index(path, revision=session.source_revision + 1)
    wrong_ref = next(
        item for item in different_index.refs(kind="state") if item.owner_path == ("Root", "A")
    )
    forged = TextEdit(
        base_source_revision=session.source_revision,
        start_offset=wrong_ref.span.start_offset,
        end_offset=wrong_ref.span.end_offset,
        replacement_text="state D;",
        intent="forged",
        source_ref=wrong_ref,
    )
    with pytest.raises(StaleTextEditError):
        service.preview_edits(session, (forged,))

    forged_identity = TextEdit.for_ref(
        session.source_revision,
        replace(ref, stable_key="state:forged"),
        "state Forged;",
    )
    with pytest.raises(StaleTextEditError, match="issued"):
        service.preview_edits(session, (forged_identity,))


@pytest.mark.unittest
def test_candidate_edit_requires_full_loader_and_inspect_before_commit(tmp_path):
    path = tmp_path / "edit.fcstm"
    path.write_bytes(VALID_SOURCE.encode("utf-8"))
    service = DocumentService()
    session = service.load(path)
    index = session.last_valid_snapshot.source_index
    ref = next(item for item in index.refs(kind="state") if item.owner_path == ("Root", "A"))
    invalid = TextEdit.for_ref(session.source_revision, ref, "state ;")

    with pytest.raises(DocumentValidationError) as error:
        service.apply_edits(session, (invalid,))

    assert session.source_revision == 0
    assert session.validation_state is ValidationState.VALID
    assert error.value.candidate.validation_state is ValidationState.INVALID_SYNTAX


@pytest.mark.unittest
def test_direct_invalid_edit_retains_last_valid_snapshot_but_blocks_execution(tmp_path):
    path = tmp_path / "edit.fcstm"
    path.write_bytes(VALID_SOURCE.encode("utf-8"))
    service = DocumentService()
    valid = service.load(path)

    invalid = service.replace_source_text(valid, "state Root {")

    assert invalid.source_revision == 1
    assert invalid.validation_state is ValidationState.INVALID_SYNTAX
    assert invalid.last_valid_snapshot is valid.last_valid_snapshot
    assert invalid.validated_revision is None
    with pytest.raises(DocumentValidationError):
        service.require_current_valid_snapshot(invalid)


@pytest.mark.unittest
def test_invalid_save_requires_confirmation_and_does_not_mark_valid(tmp_path):
    path = tmp_path / "edit.fcstm"
    path.write_bytes(VALID_SOURCE.encode("utf-8"))
    service = DocumentService()
    invalid = service.replace_source_text(service.load(path), "state Root {")

    with pytest.raises(InvalidDocumentSaveError):
        service.save(invalid)
    saved = service.save(invalid, allow_invalid=True)

    assert path.read_text(encoding="utf-8") == "state Root {"
    assert saved.saved_revision == saved.source_revision
    assert saved.validation_state is ValidationState.INVALID_SYNTAX
    assert saved.validated_revision is None


@pytest.mark.unittest
def test_save_revalidates_and_replace_failure_leaves_file_and_revision_unchanged(
    tmp_path, monkeypatch
):
    path = tmp_path / "edit.fcstm"
    path.write_bytes(VALID_SOURCE.encode("utf-8"))
    service = DocumentService()
    session = service.load(path)
    before = path.read_bytes()

    def fail_replace(source, target):
        raise OSError("replace denied")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace denied"):
        service.save(session)

    assert path.read_bytes() == before
    assert session.saved_revision == 0
    assert not tuple(tmp_path.glob(".edit.fcstm-*.tmp"))


@pytest.mark.unittest
def test_multiple_text_edits_apply_descending_and_inverse_exactly(tmp_path):
    path = tmp_path / "edit.fcstm"
    path.write_bytes(VALID_SOURCE.encode("utf-8"))
    service = DocumentService()
    session = service.load(path)
    index = session.last_valid_snapshot.source_index
    state_ref = next(
        item
        for item in index.refs(kind="state")
        if item.owner_path == ("Root", "A")
    )
    transition_ref = next(
        item
        for item in index.refs(kind="transition")
        if index.text_for_ref(item) == "A -> [*];"
    )
    edits = (
        TextEdit.for_ref(
            session.source_revision,
            transition_ref,
            "Ready -> [*];",
        ),
        TextEdit.for_ref(
            session.source_revision,
            state_ref,
            "state Ready;",
        ),
    )

    transaction = service.preview_edits(session, edits)

    assert "state Ready;" in transaction.after_text
    assert "Ready -> [*];" in transaction.after_text
    assert transaction.apply_inverse(transaction.after_text) == VALID_SOURCE


@pytest.mark.unittest
def test_transitive_dependency_change_blocks_current_snapshot(tmp_path):
    leaf = tmp_path / "leaf.fcstm"
    child = tmp_path / "child.fcstm"
    root = tmp_path / "root.fcstm"
    leaf.write_text("state Leaf;", encoding="utf-8")
    child.write_text(
        'state Child { import "./leaf.fcstm" as Nested; [*] -> Nested; }',
        encoding="utf-8",
    )
    root.write_text(
        'state Root { import "./child.fcstm" as Imported; [*] -> Imported; }',
        encoding="utf-8",
    )
    service = DocumentService()
    session = service.load(root)
    assert session.validation_state in {
        ValidationState.VALID,
        ValidationState.VALID_WITH_WARNINGS,
    }

    leaf.write_text("state Changed;", encoding="utf-8")

    with pytest.raises(DocumentDependencyStaleError) as error:
        service.require_current_valid_snapshot(session)
    assert error.value.session.validation_state is ValidationState.STALE_DEPENDENCY
    assert session.validation_state in {
        ValidationState.VALID,
        ValidationState.VALID_WITH_WARNINGS,
    }


@pytest.mark.unittest
def test_loading_failure_does_not_mutate_existing_session(tmp_path):
    good = tmp_path / "good.fcstm"
    good.write_bytes(VALID_SOURCE.encode("utf-8"))
    service = DocumentService()
    current = service.load(good)

    with pytest.raises(OSError):
        service.load(tmp_path / "missing.fcstm")

    assert current.source_text == VALID_SOURCE
    assert current.validation_state is ValidationState.VALID


@pytest.mark.unittest
def test_import_encoding_hint_survives_dirty_revalidation(tmp_path):
    child = tmp_path / "child.fcstm"
    root = tmp_path / "root.fcstm"
    child_text = 'state Child named "状态";'
    child.write_bytes(child_text.encode("gb18030"))
    root.write_text(
        'state Root { import "./child.fcstm" as Imported; '
        '[*] -> Imported; Imported -> [*]; }',
        encoding="utf-8",
    )
    service = DocumentService()

    session = service.load(
        root,
        encoding_hints=((str(child), "gb18030"),),
    )
    changed = service.replace_source_text(
        session,
        "// dirty\n" + session.source_text,
    )

    assert changed.current_valid_snapshot is not None
    assert changed.encoding_hints == ((str(child.resolve()), "gb18030"),)
    imported = next(
        document
        for document in changed.current_valid_snapshot.source_index.documents.values()
        if document.path == str(child.resolve())
    )
    assert imported.text == child_text
