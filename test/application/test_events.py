import re

import pytest

from app.application.document import DocumentService
from app.application.events import (
    EventConflictError,
    EventProjectionService,
    EventReadOnlyError,
    InvalidEventNameError,
)


def _load(tmp_path, source, name="root.fcstm"):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return DocumentService().load(path)


def test_lists_only_explicit_events_for_the_requested_owner(tmp_path):
    session = _load(
        tmp_path,
        """state Root {
    event Go named "Go Event";
    state A {
        event Go;
        state X;
        state Y;
        [*] -> X;
        X -> Y :: Implicit;
    }
    state B;
    [*] -> A;
    A -> B : Go;
}
""",
    )
    events = EventProjectionService().list_events(session, ("Root",))

    assert [(item.name, item.display_name) for item in events] == [
        ("Go", "Go Event")
    ]
    event = events[0]
    assert event.owner_path == ("Root",)
    assert event.resolved_path == ("Root", "Go")
    assert event.source_ref.kind == "event"
    assert event.name_ref.kind == "event_name"
    assert event.editable
    assert event.source_uri == session.current_valid_snapshot.source_index.root_document.uri
    assert event.scope == "declaration"
    assert [ref.scope for ref in event.use_refs] == ["chain"]


def test_rename_updates_only_resolved_event_uses_and_preserves_scope_syntax(tmp_path):
    session = _load(
        tmp_path,
        """state Root {
    event Go named "Root Go";
    state A {
        event Go named "A Go";
        state X { event Go; state P; state Q; [*] -> P; P -> Q :: Go; }
        state Y;
        [*] -> X;
        X -> Y : Go;
    }
    state B;
    [*] -> A;
    A -> B : Go;
    B -> A : /Go;
    A -> B : A.Go;
}
""",
    )
    service = EventProjectionService()
    root_go = service.list_events(session, ("Root",))[0]

    edits = service.edit_edits(session, root_go, name="Run", display_name="Root Go")
    changed = service.apply_edits(session, edits)

    assert "event Run named \"Root Go\";" in changed.source_text
    assert "A -> B : Run;" in changed.source_text
    assert "B -> A : /Run;" in changed.source_text
    assert "A -> B : A.Go;" in changed.source_text
    assert "event Go named \"A Go\";" in changed.source_text
    assert "X -> Y : Go;" in changed.source_text
    assert "P -> Q :: Go;" in changed.source_text


def test_rename_updates_every_combo_and_forced_use_without_deduplication(tmp_path):
    session = _load(
        tmp_path,
        """state Root {
    event Go;
    event Stop;
    state A;
    state B;
    [*] -> A;
    A -> B : Go + Stop + Go;
    ! * -> B : Go;
    ! A -> B : /Go;
}
""",
    )
    service = EventProjectionService()
    event = service.list_events(session, ("Root",))[0]

    assert len(event.use_refs) == 4
    changed = service.apply_edits(
        session,
        service.edit_edits(session, event, name="Run", display_name=None),
    )

    assert "A -> B : Run + Stop + Run;" in changed.source_text
    assert "! * -> B : Run;" in changed.source_text
    assert "! A -> B : /Run;" in changed.source_text


def test_rename_nested_event_updates_local_combo_and_forced_uses(tmp_path):
    session = _load(
        tmp_path,
        """state Root {
    state A { event Go; }
    state B;
    [*] -> A;
    A -> B :: Go + Go;
    ! A -> B :: Go;
}
""",
    )
    service = EventProjectionService()
    event = service.list_events(session, ("Root", "A"))[0]

    assert [ref.scope for ref in event.use_refs] == ["local", "local", "local"]
    changed = service.apply_edits(
        session,
        service.edit_edits(session, event, name="Run", display_name=None),
    )

    assert "state A { event Run; }" in changed.source_text
    assert "A -> B :: Run + Run;" in changed.source_text
    assert "! A -> B :: Run;" in changed.source_text


def test_display_name_edit_replaces_only_the_exact_string_ref(tmp_path):
    session = _load(
        tmp_path,
        'state Root { event Go named "Old"; event Stop; state A; [*] -> A; }',
    )
    service = EventProjectionService()
    event = service.list_events(session, ("Root",))[0]

    edits = service.edit_edits(
        session, event, name="Go", display_name='New "label"'
    )
    assert len(edits) == 1
    assert edits[0].source_ref == event.display_name_ref

    changed = service.apply_edits(session, edits)
    projected = service.list_events(changed, ("Root",))[0]
    assert projected.display_name == 'New "label"'
    assert 'event Stop;' in changed.source_text


def test_display_name_modify_add_and_clear_preserve_comments_whitespace_and_crlf(
    tmp_path,
):
    source = (
        "state Root {\r\n"
        "    event Go // keep declaration trivia\r\n"
        "        named // keep named trivia\r\n"
        "        \"Old\";\r\n"
        "    event Stop // keep anchor trivia\r\n"
        "        ;\r\n"
        "    state A;\r\n"
        "    [*] -> A;\r\n"
        "}\r\n"
    )
    path = tmp_path / "display-trivia.fcstm"
    path.write_bytes(source.encode("utf-8"))
    service = EventProjectionService()
    session = DocumentService().load(path)
    go, stop = service.list_events(session, ("Root",))

    modified = service.apply_edits(
        session,
        service.edit_edits(session, go, name="Go", display_name="New"),
    )
    assert (
        "// keep declaration trivia\r\n"
        "        named // keep named trivia\r\n"
        "        \"New\";"
    ) in modified.source_text
    assert re.search(r"(?<!\r)\n", modified.source_text) is None

    stop = next(
        item for item in service.list_events(modified, ("Root",)) if item.name == "Stop"
    )
    added = service.apply_edits(
        modified,
        service.edit_edits(modified, stop, name="Stop", display_name="Stop Event"),
    )
    assert "// keep anchor trivia\r\n         named \"Stop Event\";" in added.source_text

    go = next(
        item for item in service.list_events(added, ("Root",)) if item.name == "Go"
    )
    cleared = service.apply_edits(
        added,
        service.edit_edits(added, go, name="Go", display_name=None),
    )
    assert (
        "// keep declaration trivia\r\n"
        "         // keep named trivia\r\n"
        "        ;"
    ) in cleared.source_text
    assert "named \"Old\"" not in cleared.source_text
    assert "named \"New\"" not in cleared.source_text


def test_name_and_display_name_can_change_in_one_exact_transaction(tmp_path):
    source = 'state Root { event Go named "Before"; state A; [*] -> A; }'
    path = tmp_path / "event.fcstm"
    path.write_text(source, encoding="utf-8")
    service = EventProjectionService()
    session = DocumentService().load(path)
    event = service.list_events(session, ("Root",))[0]

    edits = service.edit_edits(
        session, event, name="Run", display_name="After"
    )
    changed = service.apply_edits(session, edits)

    assert 'event Run named "After";' in changed.source_text
    assert {edit.source_ref.kind for edit in edits} == {
        "event_name",
        "event_display_name",
    }


def test_rename_updates_import_mapping_target_without_touching_import_source(tmp_path):
    child = tmp_path / "child.fcstm"
    child.write_text(
        "state Child { event Go; state A; state B; [*] -> A; A -> B : Go; }",
        encoding="utf-8",
    )
    root = tmp_path / "root.fcstm"
    root.write_text(
        'state Root { event Target; import "./child.fcstm" as First { '
        "event /Go -> Target; } [*] -> First; }",
        encoding="utf-8",
    )
    session = DocumentService().load(root)
    service = EventProjectionService()
    event = service.list_events(session, ("Root",))[0]

    assert [ref.kind for ref in event.use_refs] == ["import_event_target"]
    changed = service.apply_edits(
        session,
        service.edit_edits(session, event, name="Renamed", display_name=None),
    )

    assert "event Renamed;" in changed.source_text
    assert "event /Go -> Renamed;" in changed.source_text
    assert "event /Renamed" not in changed.source_text
    assert set(changed.current_valid_snapshot.model.root_state.events) == {"Renamed"}


def test_nested_mapping_is_not_renamed_with_same_named_ancestor_event(tmp_path):
    child = tmp_path / "child.fcstm"
    child.write_text(
        "state Child { event Go; state A; [*] -> A; }", encoding="utf-8"
    )
    source = tmp_path / "root.fcstm"
    source.write_text(
        'state Root { event Target; state Host { event Target; '
        'import "./child.fcstm" as First { event /Go -> Target; } '
        '[*] -> First; } [*] -> Host; }',
        encoding="utf-8",
    )
    service = EventProjectionService()
    session = DocumentService().load(source)
    root_event = service.list_events(session, ("Root",))[0]

    changed = service.apply_edits(
        session,
        service.edit_edits(
            session, root_event, name="RootTarget", display_name=None
        ),
    )

    assert "event RootTarget;" in changed.source_text
    assert "event /Go -> Target;" in changed.source_text


def test_delete_cascade_blocks_mapping_reference_and_preserves_import(tmp_path):
    child = tmp_path / "child.fcstm"
    child.write_text(
        "state Child { event Go; state A; state B; [*] -> A; A -> B : Go; }",
        encoding="utf-8",
    )
    source = (
        'state Root { event Target; import "./child.fcstm" as First { '
        "event /Go -> Target; } [*] -> First; }"
    )
    root = tmp_path / "root.fcstm"
    root.write_text(source, encoding="utf-8")
    session = DocumentService().load(root)
    service = EventProjectionService()
    event = service.list_events(session, ("Root",))[0]

    with pytest.raises(
        EventConflictError, match="non-transition import mapping"
    ) as caught:
        service.delete_edits(session, event, delete_references=True)

    assert caught.value.source_ref.kind == "import_event_target"
    assert caught.value.reference_kind == "import_event_target"
    assert session.source_text == source
    assert 'import "./child.fcstm" as First' in session.source_text


def test_add_and_delete_use_authorized_anchor_and_declaration_ref(tmp_path):
    session = _load(tmp_path, "state Root {\n    state A;\n    [*] -> A;\n}\n")
    service = EventProjectionService()

    add_edits = service.add_edits(
        session, ("Root",), "Go", display_name="Go Event"
    )
    assert len(add_edits) == 1
    assert add_edits[0].insertion_anchor.slot == "event"
    added = service.apply_edits(session, add_edits)
    event = service.list_events(added, ("Root",))[0]
    assert event.display_name == "Go Event"

    delete_edits = service.delete_edits(added, event)
    assert len(delete_edits) == 1
    assert delete_edits[0].source_ref == event.source_ref
    deleted = service.apply_edits(added, delete_edits)
    assert service.list_events(deleted, ("Root",)) == ()
    assert "state A;" in deleted.source_text


def test_add_nested_event_preserves_crlf_and_owner_indentation(tmp_path):
    source = (
        "state Root {\r\n"
        "    state A {\r\n"
        "        state Leaf;\r\n"
        "        [*] -> Leaf;\r\n"
        "    }\r\n"
        "    [*] -> A;\r\n"
        "}\r\n"
    )
    path = tmp_path / "crlf.fcstm"
    path.write_bytes(source.encode("utf-8"))
    session = DocumentService().load(path)
    service = EventProjectionService()

    changed = service.apply_edits(
        session,
        service.add_edits(session, ("Root", "A"), "Go"),
    )

    assert "        event Go;\r\n    }" in changed.source_text
    assert re.search(r"(?<!\r)\n", changed.source_text) is None
    assert service.list_events(changed, ("Root", "A"))[0].name == "Go"


def test_delete_event_with_references_is_blocked_by_default(tmp_path):
    session = _load(
        tmp_path,
        "state Root { event Go; state A; state B; [*] -> A; A -> B : Go; }",
    )
    service = EventProjectionService()
    event = service.list_events(session, ("Root",))[0]

    with pytest.raises(EventConflictError, match="1 transition reference"):
        service.delete_edits(session, event)


def test_delete_event_and_referencing_transitions_is_one_validated_transaction(
    tmp_path,
):
    session = _load(
        tmp_path,
        "state Root { event Go; state A; state B; [*] -> A; "
        "A -> B : Go; B -> A : Go + Go; }",
    )
    service = EventProjectionService()
    event = service.list_events(session, ("Root",))[0]

    edits = service.delete_edits(session, event, delete_references=True)
    deleted = service.apply_edits(session, edits)

    assert "event Go" not in deleted.source_text
    assert "A -> B : Go;" not in deleted.source_text
    assert "B -> A : Go + Go;" not in deleted.source_text
    assert "[*] -> A;" in deleted.source_text
    assert service.list_events(deleted, ("Root",)) == ()


def test_same_owner_conflicts_are_rejected_but_same_leaf_in_other_owner_is_valid(
    tmp_path,
):
    session = _load(
        tmp_path,
        "state Root { event Go; event Stop; state A { event Go; } [*] -> A; }",
    )
    service = EventProjectionService()
    root_events = service.list_events(session, ("Root",))

    with pytest.raises(EventConflictError, match="Root.Go"):
        service.add_edits(session, ("Root",), "Go")
    with pytest.raises(EventConflictError, match="Root.Stop"):
        service.edit_edits(
            session, root_events[0], name="Stop", display_name=None
        )

    nested = service.list_events(session, ("Root", "A"))[0]
    assert nested.name == "Go"


def test_rename_rejects_conflict_with_an_implicit_event_in_the_same_scope(tmp_path):
    session = _load(
        tmp_path,
        "state Root { event Go; state A; state B; [*] -> A; A -> B : Fire; }",
    )
    service = EventProjectionService()
    event = service.list_events(session, ("Root",))[0]

    with pytest.raises(EventConflictError, match="Root.Fire"):
        service.edit_edits(session, event, name="Fire", display_name=None)


@pytest.mark.parametrize("name", [None, "", "2Go", "with-dash", "中文"])
def test_invalid_dsl_event_names_are_rejected_before_an_edit_is_created(
    tmp_path, name
):
    session = _load(
        tmp_path,
        "state Root { state A; [*] -> A; }",
    )

    with pytest.raises(InvalidEventNameError):
        EventProjectionService().add_edits(session, ("Root",), name)


def test_imported_event_is_projected_with_display_and_use_provenance_but_read_only(
    tmp_path,
):
    child = tmp_path / "child.fcstm"
    child.write_text(
        'state Child { event Go named "Child Go"; state A; state B; '
        "[*] -> A; A -> B : Go; }",
        encoding="utf-8",
    )
    root = tmp_path / "root.fcstm"
    root.write_text(
        'state Root { import "./child.fcstm" as First; [*] -> First; }',
        encoding="utf-8",
    )
    session = DocumentService().load(root)
    service = EventProjectionService()

    event = service.list_events(session, ("Root", "First"))[0]
    assert event.name == "Go"
    assert event.display_name == "Child Go"
    assert event.resolved_path == ("Root", "First", "Go")
    assert not event.editable
    assert event.source_uri == child.resolve().as_uri()
    assert len(event.use_refs) == 1
    assert not event.use_refs[0].editable

    with pytest.raises(EventReadOnlyError) as caught:
        service.edit_edits(session, event, name="Run", display_name=None)
    assert caught.value.source_ref == event.source_ref
    with pytest.raises(EventReadOnlyError):
        service.delete_edits(session, event)
    with pytest.raises(EventReadOnlyError):
        service.add_edits(session, ("Root", "First"), "New")


def test_stale_projection_cannot_authorize_a_later_revision(tmp_path):
    session = _load(tmp_path, "state Root { event Go; state A; [*] -> A; }")
    service = EventProjectionService()
    stale = service.list_events(session, ("Root",))[0]
    changed = service.apply_edits(
        session, service.add_edits(session, ("Root",), "Stop")
    )

    with pytest.raises(EventReadOnlyError, match="current snapshot"):
        service.edit_edits(changed, stale, name="Run", display_name=None)
