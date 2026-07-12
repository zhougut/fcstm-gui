import hashlib
import os
from pathlib import Path

import pytest

from app.source import (
    SourceDocument,
    SourceImportCycleError,
    SourceImportNotFoundError,
    SourceIndexError,
    StaleSourceRefError,
    build_source_index,
    build_source_index_from_text,
    load_with_source_index,
)


def _slices(index, kind):
    return [index.text_for_ref(ref) for ref in index.refs(kind=kind)]


def _ref_slices(index, kind):
    return [(index.text_for_ref(ref), ref) for ref in index.refs(kind=kind)]


def test_indexes_exact_root_declarations_and_raw_transition_forms(tmp_path):
    source = """def int x = 0;
state Root {
    event Go;
    enter { x = x + 1; }
    state A;
    state B;
    [*] -> A;
    A -> B :: Go + [x > 0] effect { x = x + 1; }
    ! * -> B : if [x < 0];
}
"""
    path = tmp_path / "root.fcstm"
    path.write_bytes(source.encode("utf-8"))

    index = build_source_index(path)

    assert _slices(index, "variable") == ["def int x = 0;"]
    assert index.refs(kind="variable")[0].semantic_key == "variable:x"
    assert _slices(index, "state")[0].startswith("state Root {")
    assert "state A;" in _slices(index, "state")
    assert _slices(index, "event") == ["event Go;"]
    assert _slices(index, "lifecycle") == ["enter { x = x + 1; }"]
    assert _slices(index, "combo_transition") == [
        "A -> B :: Go + [x > 0] effect { x = x + 1; }"
    ]
    assert _slices(index, "forced_transition") == [
        "! * -> B : if [x < 0];"
    ]
    assert sorted(_slices(index, "guard")) == ["x < 0", "x > 0"]
    assert _slices(index, "action") == [
        "x = x + 1;",
        "x = x + 1;",
    ]
    assert all(ref.ownership == "root" for ref in index.refs())
    assert all(index.text_for_ref(ref) for ref in index.refs())
    assert all(len(ref.range_sha256) == 64 for ref in index.refs())


def test_event_names_are_exact_owner_qualified_declaration_refs(tmp_path):
    source = """state Root {
    event Go named "Go";
    state A { event Go; }
    state B { event Go; }
}
"""
    path = tmp_path / "events.fcstm"
    path.write_text(source, encoding="utf-8")

    index = build_source_index(path)
    event_names = index.refs(kind="event_name")

    assert [index.text_for_ref(ref) for ref in event_names] == ["Go", "Go", "Go"]
    assert [ref.owner_path for ref in event_names] == [
        ("Root",),
        ("Root", "A"),
        ("Root", "B"),
    ]
    assert [ref.resolved_path for ref in event_names] == [
        ("Root", "Go"),
        ("Root", "A", "Go"),
        ("Root", "B", "Go"),
    ]
    assert all(ref.scope == "declaration" for ref in event_names)
    assert len({ref.stable_key for ref in event_names}) == 3
    for name_ref in event_names:
        assert name_ref.declaration_ref.kind == "event"
        assert index.text_for_declaration(name_ref.declaration_ref).startswith(
            "event Go"
        )


def test_event_display_name_and_named_clause_refs_preserve_exact_trivia(tmp_path):
    source = (
        "state Root {\r\n"
        "    event Go // keep this comment\r\n"
        "        named \"Go Event\";\r\n"
        "    event Stop;\r\n"
        "}\r\n"
    )
    path = tmp_path / "event-display.fcstm"
    path.write_bytes(source.encode("utf-8"))

    index = build_source_index(path)

    assert _slices(index, "event_display_name") == ['"Go Event"']
    assert _slices(index, "event_named_keyword") == ["named"]
    assert _slices(index, "event_named_clause") == ['named "Go Event"']
    anchors = index.refs(kind="event_named_anchor")
    assert len(anchors) == 1
    assert index.text_for_ref(anchors[0]) == ";"
    assert anchors[0].span.start_offset == source.index(";", source.index("event Stop"))


def test_import_event_mapping_endpoints_have_exact_resolved_refs(tmp_path):
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

    index = build_source_index(root)
    source_ref = index.refs(kind="import_event_source")[0]
    target_ref = index.refs(kind="import_event_target")[0]

    assert index.text_for_ref(source_ref) == "/Go"
    assert source_ref.resolved_path == ("Root", "First", "Go")
    assert source_ref.scope == "mapping_source"
    assert index.text_for_ref(target_ref) == "Target"
    assert target_ref.resolved_path == ("Root", "Target")
    assert target_ref.scope == "mapping_target_chain"
    assert source_ref.declaration_ref == target_ref.declaration_ref
    assert source_ref.declaration_ref.kind == "import"
    assert source_ref.editable and target_ref.editable


def test_nested_import_mapping_target_does_not_resolve_to_ancestor_event(tmp_path):
    child = tmp_path / "child.fcstm"
    child.write_text(
        "state Child { event Go; state A; [*] -> A; }", encoding="utf-8"
    )
    root = tmp_path / "root.fcstm"
    root.write_text(
        'state Root { event Target; state Host { event Target; '
        'import "./child.fcstm" as First { event /Go -> Target; } '
        '[*] -> First; } [*] -> Host; }',
        encoding="utf-8",
    )

    index = build_source_index(root)
    target_ref = index.refs(kind="import_event_target")[0]

    assert index.text_for_ref(target_ref) == "Target"
    assert target_ref.resolved_path == ("Root", "Host", "Target")


def test_event_uses_preserve_exact_scope_and_model_resolved_path(tmp_path):
    from pyfcstm.model import load_state_machine_from_file

    source = """state Root {
    event Go;
    state A {
        event Local;
        state X;
        state Y;
        [*] -> X;
        X -> Y :: Fire;
        Y -> X : Local;
    }
    state B;
    [*] -> A;
    A -> B : Go;
    B -> A : /Go;
}
"""
    path = tmp_path / "scopes.fcstm"
    path.write_text(source, encoding="utf-8")

    index = build_source_index(path)
    uses = _ref_slices(index, "event_use")

    assert [(text, ref.scope, ref.owner_path, ref.resolved_path) for text, ref in uses] == [
        ("Fire", "local", ("Root", "A"), ("Root", "A", "X", "Fire")),
        ("Local", "chain", ("Root", "A"), ("Root", "A", "Local")),
        ("Go", "chain", ("Root",), ("Root", "Go")),
        ("/Go", "absolute", ("Root",), ("Root", "Go")),
    ]
    assert all(
        ref.declaration_ref.kind in {"transition", "combo_transition"}
        for _, ref in uses
    )

    model = load_state_machine_from_file(path)
    model_paths = {
        (transition.event_scope, transition.event.path_name)
        for state in model.walk_states()
        for transition in state.transitions
        if transition.event is not None
        and transition.event_scope in {"local", "chain", "absolute"}
    }
    assert {(ref.scope, ".".join(ref.resolved_path)) for _, ref in uses} <= model_paths


def test_combo_and_forced_event_uses_link_one_raw_declaration_without_dedup(tmp_path):
    source = """state Root {
    event Go;
    event Stop;
    state A;
    state B;
    [*] -> A;
    A -> B : Go + Stop + Go;
    ! A -> B :: Fire;
    ! * -> B : Stop;
}
"""
    path = tmp_path / "raw-event-uses.fcstm"
    path.write_text(source, encoding="utf-8")

    index = build_source_index(path)
    uses = index.refs(kind="event_use")
    combo = index.refs(kind="combo_transition")[0]
    forced = index.refs(kind="forced_transition")

    assert [index.text_for_ref(ref) for ref in uses] == [
        "Go",
        "Stop",
        "Go",
        "Fire",
        "Stop",
    ]
    assert len({ref.stable_key for ref in uses}) == 5
    assert [ref.declaration_ref for ref in uses[:3]] == [combo.declaration_ref] * 3
    assert [ref.declaration_ref for ref in uses[3:]] == [
        ref.declaration_ref for ref in forced
    ]
    assert uses[3].scope == "local"
    assert uses[3].resolved_path == ("Root", "A", "Fire")
    assert all(ref.resolved_path[:1] == ("Root",) for ref in uses)


def test_imported_event_refs_are_physical_read_only_with_projection_provenance(
    tmp_path,
):
    child = tmp_path / "child.fcstm"
    child.write_text(
        "state Child { event Go; state A; state B; [*] -> A; A -> B : Go; }",
        encoding="utf-8",
    )
    root = tmp_path / "root.fcstm"
    root.write_text(
        'state Root { import "./child.fcstm" as First; '
        'import "./child.fcstm" as Second; }',
        encoding="utf-8",
    )

    index = build_source_index(root)
    imported_refs = tuple(
        ref
        for ref in index.refs()
        if ref.kind in {"event_name", "event_use"} and ref.ownership == "imported"
    )

    assert {index.text_for_ref(ref) for ref in imported_refs} == {"Go"}
    assert all(ref.read_only for ref in imported_refs)
    child_uri = SourceDocument.from_file(child).uri
    assert all(ref.source_uri == child_uri for ref in imported_refs)
    for ref in imported_refs:
        projections = index.projections_for_ref(ref)
        assert {projection.alias_chain for projection in projections} == {
            ("First",),
            ("Second",),
        }
        assert all(projection.physical_ref == ref for projection in projections)
        assert {projection.projected_resolved_path for projection in projections} == {
            ("Root", "First", "Go"),
            ("Root", "Second", "Go"),
        }


def test_transitive_imports_are_read_only_and_fingerprinted(tmp_path):
    grandchild = tmp_path / "grandchild.fcstm"
    grandchild.write_text("state Grandchild;", encoding="utf-8")
    child = tmp_path / "child.fcstm"
    child.write_text(
        'state Child { import "./grandchild.fcstm" as Grand; }',
        encoding="utf-8",
    )
    root = tmp_path / "root.fcstm"
    root.write_text(
        'state Root { import "./child.fcstm" as Child; }',
        encoding="utf-8",
    )

    index = build_source_index(root)

    assert len(index.documents) == 3
    assert len(index.imports) == 2
    assert len(index.dependency_manifest) == 2
    assert index.dependency_fingerprint != index.closure_fingerprint
    assert sorted(_slices(index, "import")) == [
        'import "./child.fcstm" as Child;',
        'import "./grandchild.fcstm" as Grand;',
    ]
    assert index.matches_disk()
    imported_refs = [ref for ref in index.refs() if ref.ownership == "imported"]
    assert imported_refs
    assert all(ref.read_only for ref in imported_refs)
    assert {Path(index.document_for_ref(ref).path).name for ref in imported_refs} == {
        "child.fcstm",
        "grandchild.fcstm",
    }

    original_fingerprint = index.closure_fingerprint
    grandchild.write_text("state GrandchildChanged;", encoding="utf-8")

    assert not index.matches_disk()
    assert build_source_index(root).closure_fingerprint != original_fingerprint


def test_same_imported_file_can_have_multiple_alias_instances(tmp_path):
    child = tmp_path / "child.fcstm"
    child.write_text("state Child;", encoding="utf-8")
    root = tmp_path / "root.fcstm"
    root.write_text(
        """state Root {
    import "./child.fcstm" as First;
    import "./child.fcstm" as Second;
}
""",
        encoding="utf-8",
    )

    index = build_source_index(root)

    assert len(index.documents) == 2
    assert [edge.alias for edge in index.imports] == ["First", "Second"]
    assert len({edge.target_document_id for edge in index.imports}) == 1


def test_missing_and_circular_imports_are_explicit(tmp_path):
    missing = tmp_path / "missing_root.fcstm"
    missing.write_text(
        'state Root { import "./does-not-exist.fcstm" as Missing; }',
        encoding="utf-8",
    )
    with pytest.raises(
        SourceImportNotFoundError, match="does-not-exist.fcstm"
    ) as error:
        build_source_index(missing)
    assert error.value.path == str((tmp_path / "does-not-exist.fcstm").resolve())
    assert error.value.operation == "read"

    first = tmp_path / "first.fcstm"
    second = tmp_path / "second.fcstm"
    first.write_text(
        'state First { import "./second.fcstm" as Second; }',
        encoding="utf-8",
    )
    second.write_text(
        'state Second { import "./first.fcstm" as First; }',
        encoding="utf-8",
    )
    with pytest.raises(SourceImportCycleError, match="first.fcstm"):
        build_source_index(first)


def test_source_document_preserves_encoding_and_qt_offsets(tmp_path):
    path = tmp_path / "encoded.fcstm"
    text = '// 😀 中文\r\nstate Root named "状态机";'
    raw = text.encode("gb18030")
    path.write_bytes(raw)

    document = SourceDocument.from_file(path)

    assert document.original_bytes == raw
    assert document.text == text
    assert document.encoding in {"gb18030", "gbk", "cp936"}
    emoji_offset = text.index("😀")
    assert document.python_to_qt_offset(emoji_offset) == emoji_offset
    assert document.python_to_qt_offset(emoji_offset + 1) == emoji_offset + 2
    assert document.qt_to_python_offset(emoji_offset + 2) == emoji_offset + 1
    root_offset = text.index("Root")
    root_qt_offset = document.python_to_qt_offset(root_offset)
    assert root_qt_offset == len(text[:root_offset].encode("utf-16-le")) // 2 - 1
    assert document.qt_to_python_offset(root_qt_offset) == root_offset
    assert document.offset_to_line_column(root_offset) == (2, 7)


def test_crlf_tabs_and_same_line_declarations_have_distinct_ranges(tmp_path):
    path = tmp_path / "layout.fcstm"
    path.write_bytes(b"state Root {\r\n\tstate A; state B;\r\n}\r\n")

    index = build_source_index(path)
    state_refs = index.refs(kind="state")

    assert [index.text_for_ref(ref) for ref in state_refs] == [
        "state Root {\r\n\tstate A; state B;\r\n}",
        "state A;",
        "state B;",
    ]
    assert state_refs[1].span.end_offset <= state_refs[2].span.start_offset


def test_crlf_edits_use_indexed_source_text_and_preserve_untouched_bytes(tmp_path):
    path = tmp_path / "crlf-edit.fcstm"
    raw = b"state Root {\r\n    state A;\r\n    state B;\r\n}\r\n"
    path.write_bytes(raw)
    index = build_source_index(path, revision=9)
    ref = next(
        item
        for item in index.refs(kind="state")
        if index.text_for_ref(item) == "state A;"
    )
    source_text = index.root_document.text
    replacement = "state Renamed;"

    edited = (
        source_text[:ref.span.start_offset]
        + replacement
        + source_text[ref.span.end_offset:]
    )
    path.write_bytes(edited.encode(index.root_document.encoding))
    rebuilt = build_source_index(path, revision=10)

    assert "\r\n" in rebuilt.root_document.text
    assert rebuilt.root_document.text.replace(replacement, "state A;", 1) == source_text


def test_symlinked_imports_use_one_canonical_document(tmp_path):
    child = tmp_path / "child.fcstm"
    child.write_text("state Child;", encoding="utf-8")
    alias = tmp_path / "child-link.fcstm"
    try:
        alias.symlink_to(child)
    except OSError as exc:
        pytest.skip("host cannot create symlinks: {}".format(exc))

    root = tmp_path / "root.fcstm"
    root.write_text(
        """state Root {
    import "./child.fcstm" as Direct;
    import "./child-link.fcstm" as Linked;
}
""",
        encoding="utf-8",
    )

    index = build_source_index(root)

    assert len(index.documents) == 2
    assert len({edge.target_document_id for edge in index.imports}) == 1


def test_ref_from_previous_content_is_rejected_after_rebuild(tmp_path):
    path = tmp_path / "root.fcstm"
    path.write_text("state Root { state A; }", encoding="utf-8")
    old_index = build_source_index(path)
    old_ref = next(
        ref
        for ref in old_index.refs(kind="state")
        if old_index.text_for_ref(ref) == "state A;"
    )

    path.write_text("state Root { state Renamed; }", encoding="utf-8")
    new_index = build_source_index(path)

    with pytest.raises(StaleSourceRefError):
        new_index.text_for_ref(old_ref)


def test_big5_source_is_not_silently_misdecoded_as_gb18030(tmp_path):
    path = tmp_path / "big5.fcstm"
    text = "// 繁體中文測試\nstate Root;"
    raw = text.encode("big5")
    path.write_bytes(raw)

    document = SourceDocument.from_file(path)

    assert document.original_bytes == raw
    assert document.text == text
    assert document.encoding.lower().replace("-", "") in {"big5", "cp950"}


def test_gb18030_source_is_not_silently_misdecoded_as_big5(tmp_path):
    path = tmp_path / "gb18030.fcstm"
    text = "// 简体中文状态机\nstate Root;"
    raw = text.encode("gb18030")
    path.write_bytes(raw)

    document = SourceDocument.from_file(path)

    assert document.original_bytes == raw
    assert document.text == text
    assert document.encoding.lower().replace("-", "") in {
        "gb18030",
        "gbk",
        "gb2312",
        "cp936",
    }


def test_short_low_confidence_gb18030_prefers_required_simplified_codec(tmp_path):
    path = tmp_path / "short-gb18030.fcstm"
    text = "// 中文测试\nstate Root;"
    path.write_bytes(text.encode("gb18030"))

    document = SourceDocument.from_file(path)

    assert document.text == text
    assert document.encoding.lower().replace("-", "") in {
        "gb18030",
        "gbk",
        "gb2312",
        "cp936",
    }


def test_ambiguous_utf8_gb18030_requires_explicit_build_encoding(tmp_path):
    path = tmp_path / "ambiguous.fcstm"
    text = 'state Root named "状态";'
    path.write_bytes(text.encode("gb18030"))

    with pytest.raises(SourceIndexError) as caught:
        build_source_index(path)
    assert caught.value.operation == "decode"

    index = build_source_index(path, encoding="gb18030")
    assert index.root_document.text == text
    assert index.root_document.encoding == "gb18030"
    assert index.matches_disk()


def test_transitive_imports_can_resolve_encodings_per_file(tmp_path):
    child = tmp_path / "child.fcstm"
    child_text = 'state Child named "状态";'
    child.write_bytes(child_text.encode("gb18030"))
    root = tmp_path / "root.fcstm"
    root.write_text(
        'state Root { import "./child.fcstm" as Child; }',
        encoding="utf-8",
    )

    index = build_source_index(
        root,
        encoding_resolver=lambda path: (
            "gb18030" if path.name == "child.fcstm" else None
        ),
    )
    imported = next(
        document
        for document in index.documents.values()
        if Path(document.path).name == "child.fcstm"
    )
    assert imported.text == child_text


def test_declaration_semantic_keys_survive_unrelated_prefix_insertions(tmp_path):
    path = tmp_path / "stable.fcstm"
    source = """state Root {
    enter { x = 1; }
    state A;
    state B;
    A -> B : [x > 0] effect { x = 2; }
    ! * -> A : if [x < 0];
}
"""
    path.write_text(source, encoding="utf-8")
    before = build_source_index(path)
    before_keys = {
        before.text_for_ref(ref): ref.semantic_key
        for ref in before.refs()
        if ref.kind
        in {
            "transition",
            "combo_transition",
            "forced_transition",
            "lifecycle",
            "guard",
            "action",
        }
    }

    path.write_text("def int unrelated = 99;\n" + source, encoding="utf-8")
    after = build_source_index(path)
    after_keys = {
        after.text_for_ref(ref): ref.semantic_key
        for ref in after.refs()
        if ref.kind
        in {
            "transition",
            "combo_transition",
            "forced_transition",
            "lifecycle",
            "guard",
            "action",
        }
    }

    assert after_keys == before_keys


def test_multiple_aliases_have_distinct_stable_import_instance_identities(tmp_path):
    child = tmp_path / "child.fcstm"
    child.write_text("state Child;", encoding="utf-8")
    root = tmp_path / "root.fcstm"
    root.write_text(
        """state Root {
    import "./child.fcstm" as First;
    import "./child.fcstm" as Second;
}
""",
        encoding="utf-8",
    )

    first_index = build_source_index(root)
    second_index = build_source_index(root)
    first_ids = [edge.instance_id for edge in first_index.imports]
    second_ids = [edge.instance_id for edge in second_index.imports]

    assert len(set(first_ids)) == 2
    assert first_ids == second_ids
    assert len({edge.target_document_id for edge in first_index.imports}) == 1


def test_source_index_mapping_views_are_immutable(tmp_path):
    path = tmp_path / "root.fcstm"
    path.write_text("state Root;", encoding="utf-8")
    index = build_source_index(path)

    with pytest.raises(TypeError):
        index.documents[index.root_document_id] = index.root_document
    with pytest.raises(TypeError):
        index.refs_by_document[index.root_document_id] = ()


def test_dependency_change_during_index_build_discards_snapshot(tmp_path, monkeypatch):
    import app.source.index as source_index_module

    child = tmp_path / "child.fcstm"
    child.write_text("state Child;", encoding="utf-8")
    root = tmp_path / "root.fcstm"
    root.write_text(
        'state Root { import "./child.fcstm" as Child; }',
        encoding="utf-8",
    )
    original_index_document = source_index_module._index_document
    changed = [False]

    def changing_index_document(document, ownership):
        result = original_index_document(document, ownership)
        if document.path == str(root.resolve()) and not changed[0]:
            child.write_text("state ChangedWhileLoading;", encoding="utf-8")
            changed[0] = True
        return result

    monkeypatch.setattr(
        source_index_module, "_index_document", changing_index_document
    )

    with pytest.raises(SourceIndexError, match="(?i)changed|snapshot|fingerprint"):
        build_source_index(root)


def test_loader_result_is_published_only_when_dependency_snapshot_is_stable(
    tmp_path,
):
    child = tmp_path / "child.fcstm"
    child.write_text("state Child;", encoding="utf-8")
    root = tmp_path / "root.fcstm"
    root.write_text(
        'state Root { import "./child.fcstm" as Child; }',
        encoding="utf-8",
    )

    index, result = load_with_source_index(
        root, lambda current: current.root_document.text
    )
    assert result == index.root_document.text

    def changing_loader(current):
        child.write_text("state ChangedDuringLoader;", encoding="utf-8")
        return current.root_document.text

    with pytest.raises(SourceIndexError, match="(?i)changed|snapshot"):
        load_with_source_index(root, changing_loader)


def test_unreadable_source_is_reported_as_structured_source_error(
    tmp_path, monkeypatch
):
    path = tmp_path / "root.fcstm"
    path.write_text("state Root;", encoding="utf-8")
    resolved = path.resolve()
    original_read_bytes = Path.read_bytes

    def rejecting_read_bytes(current_path):
        if current_path.resolve() == resolved:
            raise PermissionError("denied by test")
        return original_read_bytes(current_path)

    monkeypatch.setattr(Path, "read_bytes", rejecting_read_bytes)

    with pytest.raises(SourceIndexError) as caught:
        build_source_index(path)

    error = caught.value
    assert Path(error.path) == resolved
    assert error.operation == "read"
    assert isinstance(error.__cause__, PermissionError)


def test_case_insensitive_path_identity_normalizes_uri_as_well_as_file_id(
    tmp_path, monkeypatch
):
    import app.source.model as source_model

    monkeypatch.setattr(source_model.os.path, "normcase", lambda value: value.lower())
    mixed_path = tmp_path / "Folder" / "Model.fcstm"
    lower_path = tmp_path / "folder" / "model.fcstm"

    mixed = SourceDocument.from_bytes(mixed_path, b"state Root;")
    lower = SourceDocument.from_bytes(lower_path, b"state Root;")

    assert mixed.document_id == lower.document_id
    assert mixed.uri == lower.uri


def test_case_insensitive_snapshot_byte_lookup_uses_canonical_identity(
    tmp_path, monkeypatch
):
    import app.source.model as source_model

    monkeypatch.setattr(source_model.os.path, "normcase", lambda value: value.lower())
    monkeypatch.setattr("app.source.index.os.path.normcase", lambda value: value.lower())
    child_upper = tmp_path / "Child.fcstm"
    child_lower = tmp_path / "child.fcstm"
    child_upper.write_text("state Child;", encoding="utf-8")
    try:
        os.link(str(child_upper), str(child_lower))
    except OSError as error:
        pytest.skip("host cannot create hardlinks: {}".format(error))
    root = tmp_path / "root.fcstm"
    root.write_text(
        """state Root {
    import "./Child.fcstm" as Upper;
    import "./child.fcstm" as Lower;
}
""",
        encoding="utf-8",
    )

    index = build_source_index(root)

    assert len(index.documents) == 2
    assert len(index.imports) == 2
    assert len({edge.target_document_id for edge in index.imports}) == 1


def test_refs_bind_full_snapshot_identity_and_raw_declaration(tmp_path):
    path = tmp_path / "root.fcstm"
    path.write_text(
        """state Root {
    state A;
    state B;
    A -> B : [x > 0] effect { x = 1; }
}
""",
        encoding="utf-8",
    )

    index = build_source_index(path, revision=42)
    transition = index.refs(kind="combo_transition")[0]
    guard = index.refs(kind="guard")[0]
    action = index.refs(kind="action")[0]

    for ref in (transition, guard, action):
        assert ref.source_uri == index.root_document.uri
        assert ref.file_id == index.root_document.document_id
        assert ref.source_revision == 42
        assert ref.snapshot_fingerprint == index.closure_fingerprint
        assert ref.document_sha256 == index.root_document.sha256
        assert ref.stable_key
        assert ref.editable
        assert not ref.read_only
    assert transition.declaration_ref.stable_key == transition.stable_key
    assert guard.declaration_ref == transition.declaration_ref
    assert action.declaration_ref == transition.declaration_ref
    assert index.text_for_declaration(guard.declaration_ref).startswith("A -> B")


def test_guard_and_effect_clauses_map_to_one_raw_transition(tmp_path):
    path = tmp_path / "root.fcstm"
    path.write_text(
        """state Root {
    state A;
    state B;
    A -> B : [x > 0] effect { x = x + 1; }
    ! * -> A : if [x < 0];
}
""",
        encoding="utf-8",
    )

    index = build_source_index(path)

    assert _slices(index, "guard_clause") == [
        ": [x > 0]",
        ": if [x < 0]",
    ]
    assert _slices(index, "effect") == ["effect { x = x + 1; }"]
    effect = index.refs(kind="effect")[0]
    transition = index.refs(kind="combo_transition")[0]
    assert effect.declaration_ref == transition.declaration_ref
    assert index.text_for_declaration(effect.declaration_ref) == (
        "A -> B : [x > 0] effect { x = x + 1; }"
    )


def test_forced_and_combo_expansions_link_to_one_raw_declaration(tmp_path):
    from pyfcstm.model import load_state_machine_from_text

    path = tmp_path / "root.fcstm"
    source = """def int x = 0;
state Root {
    event Go;
    state A;
    state B;
    [*] -> A;
    A -> B :: Go + [x > 0] effect { x = 1; }
    ! A -> B : if [x < 0];
}
"""
    path.write_bytes(source.encode("utf-8"))
    index = build_source_index(path)
    combo = index.refs(kind="combo_transition")[0]
    forced = index.refs(kind="forced_transition")[0]

    combo_projections = index.generated_projections(
        combo.declaration_ref,
        (("Root", "A", "expanded-1"), ("Root", "A", "expanded-2")),
    )
    forced_projections = index.generated_projections(
        forced.declaration_ref,
        (("Root", "A", "forced-1"), ("Root", "A", "forced-2")),
    )

    assert len({item.projection_id for item in combo_projections}) == 2
    assert len({item.projection_id for item in forced_projections}) == 2
    assert all(item.ownership == "generated" for item in combo_projections)
    assert all(not item.editable for item in combo_projections + forced_projections)
    assert {item.physical_ref for item in combo_projections} == {combo}
    assert {item.physical_ref for item in forced_projections} == {forced}

    before = load_state_machine_from_text(source)
    model_projections = tuple(
        index.projection_for_model_transition(transition)
        for transition in before.root_state.transitions
        if transition.is_forced or transition.combo_origin_refs
    )
    assert len(model_projections) == 3
    assert len({item.projection_id for item in model_projections}) == 3
    assert [item.physical_ref for item in model_projections].count(combo) == 2
    assert [item.physical_ref for item in model_projections].count(forced) == 1
    replacement = "A -> B :: Go + [x >= 0] effect { x = 2; }"
    edited = (
        source[:combo.span.start_offset]
        + replacement
        + source[combo.span.end_offset:]
    )
    after = load_state_machine_from_text(edited)
    assert len(before.root_state.transitions) == len(after.root_state.transitions)
    assert len(before.forced_transitions) == len(after.forced_transitions)
    assert edited.count(replacement) == 1


def test_imported_combo_model_objects_require_and_use_physical_source_uri(tmp_path):
    from pyfcstm.model import load_state_machine_from_file

    child = tmp_path / "child.fcstm"
    child.write_text(
        "state Child { event Go; state A; state B; "
        "[*] -> A; A -> B :: Go + Go; }",
        encoding="utf-8",
    )
    root = tmp_path / "root.fcstm"
    root.write_text(
        'state Root { import "./child.fcstm" as Child; [*] -> Child; }',
        encoding="utf-8",
    )
    index = build_source_index(root)
    model = load_state_machine_from_file(root)
    transitions = tuple(
        transition
        for state in model.walk_states()
        for transition in state.transitions
        if transition.combo_origin_refs
    )

    assert len(transitions) == 2
    with pytest.raises(SourceIndexError, match="not unique"):
        index.projection_for_model_transition(transitions[0])

    child_uri = next(
        document.uri
        for document in index.documents.values()
        if Path(document.path).name == "child.fcstm"
    )
    projections = tuple(
        index.projection_for_model_transition(
            transition, source_uri=child_uri
        )
        for transition in transitions
    )
    raw = index.refs(kind="combo_transition")[0]
    assert {item.physical_ref for item in projections} == {raw}
    assert len({item.projection_id for item in projections}) == 2
    assert all(
        item.projected_owner_path[:2] == ("Root", "Child")
        for item in projections
    )


def test_import_alias_projections_are_distinct_read_only_source_links(tmp_path):
    child = tmp_path / "child.fcstm"
    child.write_text("state Child;", encoding="utf-8")
    root = tmp_path / "root.fcstm"
    root.write_text(
        """state Root {
    import "./child.fcstm" as First;
    import "./child.fcstm" as Second;
}
""",
        encoding="utf-8",
    )

    index = build_source_index(root)
    child_ref = next(
        ref
        for ref in index.refs(kind="state")
        if index.document_for_ref(ref).path == str(child.resolve())
    )
    projections = index.projections_for_ref(child_ref)

    assert len(projections) == 2
    assert {item.alias_chain for item in projections} == {("First",), ("Second",)}
    assert len({item.projection_id for item in projections}) == 2
    assert all(not item.editable for item in projections)
    assert all(item.source_uri == index.document_for_ref(child_ref).uri for item in projections)


def test_transitive_alias_projection_replaces_each_physical_root_name(tmp_path):
    leaf = tmp_path / "leaf.fcstm"
    leaf.write_text("state C { state Leaf; }", encoding="utf-8")
    middle = tmp_path / "middle.fcstm"
    middle.write_text(
        'state B { import "./leaf.fcstm" as ViaC; }', encoding="utf-8"
    )
    root = tmp_path / "root.fcstm"
    root.write_text(
        'state A { import "./middle.fcstm" as ViaB; }', encoding="utf-8"
    )

    index = build_source_index(root)
    leaf_ref = next(
        ref
        for ref in index.refs(kind="state")
        if ref.owner_path == ("C", "Leaf")
    )
    projection = index.projections_for_ref(leaf_ref)[0]

    assert projection.alias_chain == ("ViaB", "ViaC")
    assert projection.projected_owner_path == ("A", "ViaB", "ViaC", "Leaf")


def test_insertion_anchors_add_all_root_owned_declaration_slots(tmp_path):
    path = tmp_path / "root.fcstm"
    source = "state Root {\n}\n"
    path.write_bytes(source.encode("utf-8"))

    additions = (
        ("variable", (), "def int x = 0;\n"),
        ("state", ("Root",), "    state A;\n"),
        ("event", ("Root",), "    event Go;\n"),
        ("transition", ("Root",), "    [*] -> A;\n"),
        ("lifecycle", ("Root",), "    enter { x = 1; }\n"),
    )
    current = source
    for kind, owner_path, text in additions:
        path.write_bytes(current.encode("utf-8"))
        index = build_source_index(path)
        anchor = index.insertion_anchor(kind, owner_path=owner_path)
        assert anchor.editable
        assert anchor.source_revision == index.root_document.revision
        index.validate_insertion_anchor(anchor)
        current = current[:anchor.offset] + text + current[anchor.offset:]
        path.write_bytes(current.encode("utf-8"))
        rebuilt = build_source_index(path)
        assert rebuilt.refs(kind=kind)


def test_stale_or_imported_insertion_anchors_cannot_authorize_writes(tmp_path):
    child = tmp_path / "child.fcstm"
    child.write_text("state Child { enter { } }", encoding="utf-8")
    root = tmp_path / "root.fcstm"
    root.write_text(
        'state Root { import "./child.fcstm" as Child; }',
        encoding="utf-8",
    )
    index = build_source_index(root, revision=5)
    anchor = index.insertion_anchor("state", owner_path=("Root",))

    root.write_text(
        '// shifted\nstate Root { import "./child.fcstm" as Child; }',
        encoding="utf-8",
    )
    rebuilt = build_source_index(root, revision=5)
    with pytest.raises(StaleSourceRefError):
        rebuilt.validate_insertion_anchor(anchor)

    imported_lifecycle = next(
        ref
        for ref in rebuilt.refs(kind="lifecycle")
        if ref.ownership == "imported"
    )
    with pytest.raises(SourceIndexError, match="editable root"):
        rebuilt.insertion_anchor(
            "action", declaration_ref=imported_lifecycle.declaration_ref
        )


def test_insertion_anchor_rejects_declaration_slot_type_confusion(tmp_path):
    path = tmp_path / "root.fcstm"
    path.write_text(
        """state Root {
    state Leaf;
    state Composite { state Child; }
}
""",
        encoding="utf-8",
    )
    index = build_source_index(path)
    leaf = next(
        ref
        for ref in index.refs(kind="state")
        if ref.owner_path == ("Root", "Leaf")
    )
    composite = next(
        ref
        for ref in index.refs(kind="state")
        if ref.owner_path == ("Root", "Composite")
    )

    for kind in ("guard", "effect"):
        with pytest.raises(SourceIndexError, match="transition"):
            index.insertion_anchor(kind, declaration_ref=leaf.declaration_ref)
    with pytest.raises(SourceIndexError, match="lifecycle or effect"):
        index.insertion_anchor(
            "action", declaration_ref=composite.declaration_ref
        )


def test_guard_effect_and_action_insertion_anchors_round_trip(tmp_path):
    path = tmp_path / "root.fcstm"
    source = """def int x = 0;
state Root {
    state A;
    state B;
    A -> B;
    enter { }
}
"""
    path.write_bytes(source.encode("utf-8"))

    index = build_source_index(path)
    transition = index.refs(kind="transition")[0]
    guard_anchor = index.insertion_anchor(
        "guard", declaration_ref=transition.declaration_ref
    )
    source = source[:guard_anchor.offset] + " : [x > 0]" + source[guard_anchor.offset:]
    path.write_bytes(source.encode("utf-8"))
    index = build_source_index(path)
    assert _slices(index, "guard") == ["x > 0"]

    transition = index.refs(kind="combo_transition")[0]
    effect_anchor = index.insertion_anchor(
        "effect", declaration_ref=transition.declaration_ref
    )
    source = source[:effect_anchor.offset] + " effect { x = 1; }" + source[effect_anchor.offset:]
    path.write_bytes(source.encode("utf-8"))
    index = build_source_index(path)
    assert _slices(index, "effect") == ["effect { x = 1; }"]

    lifecycle = index.refs(kind="lifecycle")[0]
    action_anchor = index.insertion_anchor(
        "action", declaration_ref=lifecycle.declaration_ref
    )
    source = source[:action_anchor.offset] + " x = 2;" + source[action_anchor.offset:]
    path.write_bytes(source.encode("utf-8"))
    index = build_source_index(path)
    assert "x = 2;" in _slices(index, "action")


@pytest.mark.parametrize(
    ("kind", "old_text", "new_text"),
    [
        ("variable", "def int x = 0;", "def int x = 3;"),
        ("state", "state A;", "state Renamed;"),
        ("event", "event Go;", "event Stop;"),
        ("transition", "B -> A;", "A -> B;"),
        ("lifecycle", "enter { x = 1; }", "during { x = 2; }"),
        ("guard_clause", ": [x > 0]", ": [x >= 0]"),
        ("effect", "effect { x = 2; }", "effect { x = 3; }"),
        ("action", "x = 1;", "x = 4;"),
    ],
)
def test_existing_ui2_refs_support_exact_modify_and_delete_round_trip(
    tmp_path, kind, old_text, new_text
):
    path = tmp_path / "root.fcstm"
    source = """def int x = 0;
state Root {
    event Go;
    enter { x = 1; }
    state A;
    state B;
    A -> B : [x > 0] effect { x = 2; }
    B -> A;
}
"""
    path.write_bytes(source.encode("utf-8"))
    index = build_source_index(path)
    ref = next(ref for ref in index.refs(kind=kind) if index.text_for_ref(ref) == old_text)

    modified = source[:ref.span.start_offset] + new_text + source[ref.span.end_offset:]
    assert modified.replace(new_text, old_text, 1) == source
    path.write_bytes(modified.encode("utf-8"))
    build_source_index(path)

    deleted = (
        source[:ref.span.start_offset]
        + ref.deletion_replacement
        + source[ref.span.end_offset:]
    )
    path.write_bytes(deleted.encode("utf-8"))
    build_source_index(path)


def test_in_memory_root_overlay_keeps_physical_uri_and_real_import_closure(tmp_path):
    child = tmp_path / "child.fcstm"
    root = tmp_path / "root.fcstm"
    child.write_bytes(b"state Child;")
    disk_source = 'state Root { import "./child.fcstm" as Item; }'
    root.write_bytes(disk_source.encode("utf-8"))
    candidate = "// unsaved\n" + disk_source

    index = build_source_index_from_text(
        root,
        candidate,
        revision=9,
        encoding="utf-8",
    )

    assert index.root_document.path == str(root.resolve())
    assert index.root_document.uri == SourceDocument.from_file(root).uri
    assert index.root_document.text == candidate
    assert root.read_text(encoding="utf-8") == disk_source
    assert index.root_document.revision == 9
    assert index.dependency_manifest == (
        (
            SourceDocument.from_file(child).uri,
            hashlib.sha256(child.read_bytes()).hexdigest(),
        ),
    )


def test_dependency_match_ignores_unsaved_root_but_detects_import_change(tmp_path):
    child = tmp_path / "child.fcstm"
    root = tmp_path / "root.fcstm"
    child.write_bytes(b"state Child;")
    disk_source = 'state Root { import "./child.fcstm" as Item; }'
    root.write_bytes(disk_source.encode("utf-8"))
    index = build_source_index_from_text(
        root,
        "// dirty\n" + disk_source,
        revision=3,
        encoding="utf-8",
    )

    assert index.matches_dependencies_on_disk()
    assert not index.matches_disk()

    child.write_bytes(b"state Changed;")
    assert not index.matches_dependencies_on_disk()


def test_in_memory_root_overlay_supports_a_not_yet_saved_document(tmp_path):
    path = tmp_path / "new.fcstm"

    index = build_source_index_from_text(
        path,
        "state New;",
        revision=1,
        encoding="utf-8",
    )

    assert not path.exists()
    assert index.root_document.path == str(path.resolve())
    assert index.root_document.text == "state New;"
