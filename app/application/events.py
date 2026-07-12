import json
import re
from dataclasses import dataclass
from typing import Optional, Tuple

from app.application.document import DocumentService, TextEdit
from app.model.session import DocumentSession
from app.source import SourceIndex, SourceRef


class EventProjectionError(RuntimeError):
    def __init__(self, message, source_ref=None, reference_kind=None):
        super().__init__(message)
        self.source_ref = source_ref
        self.reference_kind = reference_kind


class EventNotFoundError(EventProjectionError):
    pass


class EventReadOnlyError(EventProjectionError):
    pass


class EventConflictError(EventProjectionError):
    pass


class InvalidEventNameError(EventProjectionError):
    pass


@dataclass(frozen=True)
class EventProjection:
    name: str
    display_name: Optional[str]
    owner_path: Tuple[str, ...]
    resolved_path: Tuple[str, ...]
    source_ref: SourceRef
    name_ref: SourceRef
    display_name_ref: Optional[SourceRef]
    named_keyword_ref: Optional[SourceRef]
    named_clause_ref: Optional[SourceRef]
    named_anchor_ref: Optional[SourceRef]
    use_refs: Tuple[SourceRef, ...]
    editable: bool
    source_uri: str
    ownership: str
    scope: str
    projection_id: str


class EventProjectionService:
    _IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def __init__(self, document_service=None):
        self._documents = document_service or DocumentService()

    def list_events(
        self, session: DocumentSession, owner_path: Tuple[str, ...]
    ) -> Tuple[EventProjection, ...]:
        snapshot = self._documents.require_current_valid_snapshot(session)
        index = snapshot.source_index
        owner_path = tuple(owner_path)
        model_state = self._model_state(snapshot.model, owner_path)
        if model_state is None:
            return ()

        declarations = self._event_declarations(index)
        result = []
        for event_ref, name_ref in declarations:
            if name_ref.ownership == "root":
                projected_owner = name_ref.owner_path
                resolved_path = name_ref.resolved_path
                projection_id = name_ref.stable_key
            else:
                matching = tuple(
                    projection
                    for projection in index.projections_for_ref(name_ref)
                    if projection.projected_owner_path == owner_path
                )
                if not matching:
                    continue
                for projection in matching:
                    resolved_path = projection.projected_resolved_path
                    if not resolved_path:
                        resolved_path = owner_path + (
                            index.text_for_ref(name_ref),
                        )
                    result.append(
                        self._projection(
                            index,
                            model_state,
                            event_ref,
                            name_ref,
                            owner_path,
                            resolved_path,
                            projection.projection_id,
                        )
                    )
                continue

            if projected_owner != owner_path:
                continue
            result.append(
                self._projection(
                    index,
                    model_state,
                    event_ref,
                    name_ref,
                    projected_owner,
                    resolved_path,
                    projection_id,
                )
            )
        return tuple(
            sorted(
                result,
                key=lambda item: (
                    item.source_uri,
                    item.name_ref.span.start_offset,
                    item.projection_id,
                ),
            )
        )

    def add_edits(
        self,
        session: DocumentSession,
        owner_path: Tuple[str, ...],
        name: str,
        display_name: Optional[str] = None,
    ) -> Tuple[TextEdit, ...]:
        name = self._validate_name(name)
        owner_path = tuple(owner_path)
        snapshot = self._documents.require_current_valid_snapshot(session)
        index = snapshot.source_index
        self._require_editable_owner(index, snapshot.model, owner_path)
        self._require_available(session, owner_path, name)
        anchor = index.insertion_anchor("event", owner_path=owner_path)
        declaration = self._render_declaration(name, display_name)
        insertion = self._render_insertion(index, anchor.offset, owner_path, declaration)
        return (
            TextEdit.for_anchor(
                session.source_revision,
                anchor,
                insertion,
                intent="add event {}".format(".".join(owner_path + (name,))),
            ),
        )

    def edit_edits(
        self,
        session: DocumentSession,
        event: EventProjection,
        name: str,
        display_name: Optional[str],
    ) -> Tuple[TextEdit, ...]:
        current = self._require_current_editable(session, event)
        name = self._validate_name(name)
        if name != current.name:
            self._require_available(session, current.owner_path, name)

        edits = []
        if display_name != current.display_name:
            rendered_display = (
                None
                if display_name is None
                else json.dumps(str(display_name), ensure_ascii=False)
            )
            if current.display_name is None:
                display_ref = current.named_anchor_ref
                replacement = " named {};".format(rendered_display)
            elif display_name is None:
                display_refs = (
                    current.named_keyword_ref,
                    current.display_name_ref,
                )
                if any(ref is None or not ref.editable for ref in display_refs):
                    conflict_ref = next(
                        (ref for ref in display_refs if ref is not None),
                        current.source_ref,
                    )
                    raise EventReadOnlyError(
                        "event named-clause references are not editable",
                        source_ref=conflict_ref,
                    )
                edits.extend(
                    TextEdit.for_ref(
                        session.source_revision,
                        ref,
                        "",
                        intent="clear event display name {}".format(
                            ".".join(current.resolved_path)
                        ),
                    )
                    for ref in display_refs
                )
                display_ref = None
                replacement = None
            else:
                display_ref = current.display_name_ref
                replacement = rendered_display
            if display_ref is not None:
                if not display_ref.editable:
                    raise EventReadOnlyError(
                        "event display-name reference is not editable",
                        source_ref=display_ref,
                    )
                edits.append(
                    TextEdit.for_ref(
                        session.source_revision,
                        display_ref,
                        replacement,
                        intent="edit event display name {}".format(
                            ".".join(current.resolved_path)
                        ),
                    )
                )
        if name != current.name:
            edits.append(
                TextEdit.for_ref(
                    session.source_revision,
                    current.name_ref,
                    name,
                    intent="rename event declaration {}".format(
                        ".".join(current.resolved_path)
                    ),
                )
            )

        if name != current.name:
            index = session.require_current_valid_snapshot().source_index
            for use_ref in current.use_refs:
                declaration_ref = self.source_ref_for_declaration(
                    index, use_ref.declaration_ref
                )
                if not use_ref.editable or not declaration_ref.editable:
                    raise EventReadOnlyError(
                        "event rename includes a read-only {} reference".format(
                            self.reference_label(use_ref)
                        ),
                        source_ref=declaration_ref,
                        reference_kind=use_ref.kind,
                    )
                raw = index.text_for_ref(use_ref)
                edits.append(
                    TextEdit.for_ref(
                        session.source_revision,
                        use_ref,
                        self._rename_use(raw, name),
                        intent="rename event use {}".format(
                            ".".join(current.resolved_path)
                        ),
                    )
                )
        if not edits:
            return ()
        return tuple(edits)

    def delete_edits(
        self,
        session: DocumentSession,
        event: EventProjection,
        delete_references: bool = False,
    ) -> Tuple[TextEdit, ...]:
        current = self._require_current_editable(session, event)
        if current.use_refs and not delete_references:
            conflict_ref = current.use_refs[0]
            raise EventConflictError(
                "event {} has {} {} reference(s)".format(
                    ".".join(current.resolved_path),
                    len(current.use_refs),
                    self.reference_label(conflict_ref),
                ),
                source_ref=conflict_ref,
                reference_kind=conflict_ref.kind,
            )

        edits = [
            TextEdit.for_ref(
                session.source_revision,
                current.source_ref,
                current.source_ref.deletion_replacement,
                intent="delete explicit event {}".format(
                    ".".join(current.resolved_path)
                ),
            )
        ]
        if delete_references:
            index = session.require_current_valid_snapshot().source_index
            declarations = {}
            for use_ref in current.use_refs:
                if use_ref.kind != "event_use":
                    raise EventConflictError(
                        "event {} has a non-transition import mapping reference"
                        .format(".".join(current.resolved_path)),
                        source_ref=use_ref,
                        reference_kind=use_ref.kind,
                    )
                declaration = use_ref.declaration_ref
                declaration_ref = self.source_ref_for_declaration(
                    index, declaration
                )
                if not declaration_ref.editable:
                    raise EventReadOnlyError(
                        "event reference belongs to a read-only transition",
                        source_ref=declaration_ref,
                        reference_kind=use_ref.kind,
                    )
                declarations[declaration.stable_key] = declaration_ref
            edits.extend(
                TextEdit.for_ref(
                    session.source_revision,
                    declaration_ref,
                    declaration_ref.deletion_replacement,
                    intent="delete transition referencing event {}".format(
                        ".".join(current.resolved_path)
                    ),
                )
                for declaration_ref in declarations.values()
            )
        return tuple(edits)

    def apply_edits(
        self, session: DocumentSession, edits: Tuple[TextEdit, ...]
    ) -> DocumentSession:
        if not edits:
            return session
        return self._documents.apply_edits(session, edits)

    def _projection(
        self,
        index: SourceIndex,
        model_state,
        event_ref: SourceRef,
        name_ref: SourceRef,
        owner_path: Tuple[str, ...],
        resolved_path: Tuple[str, ...],
        projection_id: str,
    ) -> EventProjection:
        name = index.text_for_ref(name_ref)
        model_event = getattr(model_state, "events", {}).get(name)
        display_name = getattr(model_event, "extra_name", None)
        declaration_refs = tuple(
            ref
            for ref in index.refs(document_id=name_ref.file_id)
            if ref.declaration_ref == name_ref.declaration_ref
        )

        def declaration_ref(kind):
            return next(
                (ref for ref in declaration_refs if ref.kind == kind), None
            )

        use_refs = self._uses_for_path(index, resolved_path)
        return EventProjection(
            name=name,
            display_name=display_name,
            owner_path=owner_path,
            resolved_path=resolved_path,
            source_ref=event_ref,
            name_ref=name_ref,
            display_name_ref=declaration_ref("event_display_name"),
            named_keyword_ref=declaration_ref("event_named_keyword"),
            named_clause_ref=declaration_ref("event_named_clause"),
            named_anchor_ref=declaration_ref("event_named_anchor"),
            use_refs=use_refs,
            editable=event_ref.editable and name_ref.editable,
            source_uri=event_ref.source_uri,
            ownership=event_ref.ownership,
            scope=name_ref.scope or "declaration",
            projection_id=projection_id,
        )

    @staticmethod
    def _event_declarations(index: SourceIndex):
        events = {
            ref.declaration_ref: ref for ref in index.refs(kind="event")
        }
        return tuple(
            (events[name_ref.declaration_ref], name_ref)
            for name_ref in index.refs(kind="event_name")
            if name_ref.declaration_ref in events
        )

    @staticmethod
    def source_ref_for_declaration(index, declaration):
        source_ref = next(
            (
                ref
                for ref in index.refs(document_id=declaration.file_id)
                if ref.declaration_ref == declaration
                and ref.stable_key == declaration.stable_key
                and ref.span == declaration.span
            ),
            None,
        )
        if source_ref is None:
            raise EventReadOnlyError(
                "event reference declaration is not in the current snapshot",
                source_ref=declaration,
            )
        return source_ref

    @staticmethod
    def _model_state(model, owner_path):
        root = getattr(model, "root_state", None)
        if root is None:
            return None
        return next(
            (
                state
                for state in root.walk_states()
                if tuple(getattr(state, "path", ())) == owner_path
            ),
            None,
        )

    @staticmethod
    def _uses_for_path(index: SourceIndex, resolved_path):
        uses = []
        for ref in index.refs():
            if ref.kind not in {
                "event_use",
                "import_event_source",
                "import_event_target",
            }:
                continue
            if ref.ownership == "root":
                matches = ref.resolved_path == resolved_path
            else:
                matches = any(
                    projection.projected_resolved_path == resolved_path
                    for projection in index.projections_for_ref(ref)
                )
            if matches:
                uses.append(ref)
        return tuple(
            sorted(
                uses,
                key=lambda ref: (ref.source_uri, ref.span.start_offset),
            )
        )

    def _require_current_editable(self, session, event):
        current = next(
            (
                item
                for item in self.list_events(session, event.owner_path)
                if item == event
            ),
            None,
        )
        if current is None:
            raise EventReadOnlyError(
                "event projection does not belong to the current snapshot",
                source_ref=event.source_ref,
            )
        if not current.editable:
            raise EventReadOnlyError(
                "imported event projection is read-only",
                source_ref=current.source_ref,
            )
        return current

    @staticmethod
    def reference_label(source_ref):
        if source_ref.kind in {"import_event_source", "import_event_target"}:
            return "import event mapping"
        return "transition"

    def _require_available(self, session, owner_path, name):
        resolved = owner_path + (name,)
        snapshot = self._documents.require_current_valid_snapshot(session)
        state = self._model_state(snapshot.model, owner_path)
        if state is not None and name in getattr(state, "events", {}):
            raise EventConflictError(
                "event {} already exists in this scope".format(".".join(resolved))
            )

    @staticmethod
    def _require_editable_owner(index, model, owner_path):
        if any(
            ref.editable and ref.owner_path == owner_path
            for ref in index.refs(kind="state", document_id=index.root_document_id)
        ):
            return
        state = EventProjectionService._model_state(model, owner_path)
        if state is not None:
            raise EventReadOnlyError(
                "state {} is imported and read-only".format(".".join(owner_path))
            )
        raise EventNotFoundError("state {} does not exist".format(".".join(owner_path)))

    @classmethod
    def _validate_name(cls, name):
        if not isinstance(name, str):
            raise InvalidEventNameError("event name must be a DSL identifier")
        name = name.strip()
        if not cls._IDENTIFIER.match(name):
            raise InvalidEventNameError(
                "event name must be an ASCII DSL identifier"
            )
        return name

    @staticmethod
    def _render_declaration(name, display_name):
        if display_name is None or display_name == "":
            return "event {};".format(name)
        return "event {} named {};".format(
            name, json.dumps(str(display_name), ensure_ascii=False)
        )

    @staticmethod
    def _render_insertion(index, offset, owner_path, declaration):
        text = index.root_document.text
        line_start = text.rfind("\n", 0, offset) + 1
        line_prefix = text[line_start:offset]
        indent = "    " * len(owner_path)
        closing_indent = "    " * max(0, len(owner_path) - 1)
        crlf_count = text.count("\r\n")
        newline = "\r\n" if crlf_count * 2 >= max(1, text.count("\n")) else "\n"
        if not line_prefix.strip() and indent.startswith(line_prefix):
            return (
                indent[len(line_prefix):]
                + declaration
                + newline
                + closing_indent
            )
        return newline + indent + declaration + newline + closing_indent

    @staticmethod
    def _rename_use(raw, name):
        separator = raw.rfind(".")
        if separator >= 0:
            return raw[: separator + 1] + name
        if raw.startswith("/"):
            return "/" + name
        return name
