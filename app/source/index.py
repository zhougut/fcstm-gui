import ast
import hashlib
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import (
    Callable,
    DefaultDict,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    TypeVar,
)

from antlr4 import CommonTokenStream, InputStream, ParserRuleContext
from pyfcstm.dsl import parse_state_machine_dsl
from pyfcstm.dsl.grammar import GrammarLexer, GrammarParser

from .model import (
    DeclarationRef,
    ImportEdge,
    InsertionAnchor,
    PathLike,
    SourceDocument,
    SourceProjection,
    SourceRef,
    SourceSpan,
    StaleSourceRefError,
    canonical_path,
)


T = TypeVar("T")


class SourceIndexError(ValueError):
    def __init__(
        self,
        message: str,
        path: Optional[str] = None,
        operation: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.path = path
        self.operation = operation


class SourceImportNotFoundError(SourceIndexError):
    pass


class SourceImportCycleError(SourceIndexError):
    pass


class SourceSnapshotChangedError(SourceIndexError):
    pass


@dataclass(frozen=True)
class _ImportDirective:
    source_ref: SourceRef
    source_path: str
    alias: str
    owner_path: Tuple[str, ...]


@dataclass(frozen=True)
class _CapturedSnapshot:
    manifest: Tuple[Tuple[str, str], ...]
    fingerprint: str
    raw_by_path: Mapping[str, bytes]
    encoding_by_path: Mapping[str, str]


@dataclass(frozen=True)
class SourceIndex:
    root_document_id: str
    documents: Mapping[str, SourceDocument]
    refs_by_document: Mapping[str, Tuple[SourceRef, ...]]
    imports: Tuple[ImportEdge, ...]
    closure_manifest: Tuple[Tuple[str, str], ...]
    closure_fingerprint: str
    projections: Tuple[SourceProjection, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "documents", MappingProxyType(dict(self.documents))
        )
        object.__setattr__(
            self,
            "refs_by_document",
            MappingProxyType(
                {
                    file_id: tuple(refs)
                    for file_id, refs in self.refs_by_document.items()
                }
            ),
        )
        object.__setattr__(self, "imports", tuple(self.imports))
        object.__setattr__(self, "projections", tuple(self.projections))

    @property
    def root_document(self) -> SourceDocument:
        return self.documents[self.root_document_id]

    @property
    def dependency_manifest(self) -> Tuple[Tuple[str, str], ...]:
        return tuple(
            item for item in self.closure_manifest if item[0] != self.root_document.uri
        )

    @property
    def dependency_fingerprint(self) -> str:
        return _fingerprint_manifest(self.dependency_manifest)

    def refs(
        self, kind: Optional[str] = None, document_id: Optional[str] = None
    ) -> Tuple[SourceRef, ...]:
        document_ids = (
            [document_id] if document_id is not None else list(self.documents.keys())
        )
        result = []
        for current_id in document_ids:
            for ref in self.refs_by_document.get(current_id, ()):
                if kind is None or ref.kind == kind:
                    result.append(ref)
        return tuple(result)

    def document_for_ref(self, ref: SourceRef) -> SourceDocument:
        try:
            document = self.documents[ref.document_id]
        except KeyError:
            raise StaleSourceRefError(
                "source ref file does not belong to this source snapshot"
            )
        if (
            document.uri != ref.source_uri
            or document.document_id != ref.file_id
            or document.revision != ref.revision
            or document.snapshot_fingerprint != ref.snapshot_fingerprint
            or document.sha256 != ref.document_sha256
        ):
            raise StaleSourceRefError(
                "source ref identity does not match the indexed source snapshot"
            )
        return document

    def text_for_ref(self, ref: SourceRef) -> str:
        document = self.document_for_ref(ref)
        if not (
            0 <= ref.span.start_offset <= ref.span.end_offset <= len(document.text)
        ):
            raise StaleSourceRefError(
                "source ref range is outside the indexed document"
            )
        text = document.text[ref.span.start_offset:ref.span.end_offset]
        range_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if range_sha256 != ref.range_sha256:
            raise StaleSourceRefError(
                "source ref range no longer matches the indexed declaration"
            )
        return text

    def matches_disk(self) -> bool:
        encodings = {
            os.path.normcase(document.path): document.encoding
            for document in self.documents.values()
        }

        def resolve_encoding(path: Path) -> Optional[str]:
            return encodings.get(os.path.normcase(str(canonical_path(path))))

        try:
            current = build_source_index(
                self.root_document.path,
                encoding=self.root_document.encoding,
                encoding_resolver=resolve_encoding,
            )
        except (OSError, SourceIndexError):
            return False
        return current.closure_manifest == self.closure_manifest

    def projections_for_ref(self, ref: SourceRef) -> Tuple[SourceProjection, ...]:
        return tuple(
            projection
            for projection in self.projections
            if projection.physical_ref == ref
        )

    def generated_projections(
        self,
        declaration_ref: DeclarationRef,
        projected_owner_paths: Iterable[Tuple[str, ...]],
    ) -> Tuple[SourceProjection, ...]:
        raw_ref = next(
            (
                ref
                for ref in self.refs_by_document.get(declaration_ref.file_id, ())
                if ref.declaration_ref == declaration_ref
                and ref.stable_key == declaration_ref.stable_key
                and ref.kind in {"forced_transition", "combo_transition"}
            ),
            None,
        )
        if raw_ref is None:
            raise SourceIndexError(
                "generated projections require a raw forced/combo declaration"
            )
        projections = []
        for owner_path in projected_owner_paths:
            projection_id = hashlib.sha256(
                "\0".join(
                    (raw_ref.stable_key, ".".join(owner_path))
                ).encode("utf-8")
            ).hexdigest()
            projections.append(
                SourceProjection(
                    projection_id=projection_id,
                    physical_ref=raw_ref,
                    edge_chain=(),
                    alias_chain=(),
                    projected_owner_path=owner_path,
                    ownership="generated",
                    editable=False,
                )
            )
        return tuple(projections)

    def projection_for_model_transition(
        self, transition: object, source_uri: Optional[str] = None
    ) -> SourceProjection:
        raw_ref = None  # type: Optional[SourceRef]
        identity_parts = []  # type: List[str]
        if bool(getattr(transition, "is_forced", False)):
            forced_origin = getattr(transition, "forced_origin", None)
            if not forced_origin:
                raise SourceIndexError(
                    "forced transition does not expose its raw origin"
                )
            candidates = tuple(
                ref
                for ref in self.refs(kind="forced_transition")
                if self.text_for_ref(ref) == forced_origin
                and (
                    ref.source_uri == source_uri
                    if source_uri is not None
                    else ref.ownership == "root"
                )
            )
            if len(candidates) != 1:
                raise SourceIndexError(
                    "forced transition origin is not unique in the source closure"
                )
            raw_ref = candidates[0]
            identity_parts.append(str(forced_origin))
        else:
            origin_refs = tuple(getattr(transition, "combo_origin_refs", ()))
            if not origin_refs:
                raise SourceIndexError(
                    "transition is not a forced/combo expanded object"
                )
            spans = {
                (
                    origin.transition_span.line,
                    origin.transition_span.column,
                    origin.transition_span.end_line,
                    origin.transition_span.end_column,
                )
                for origin in origin_refs
            }
            candidates = tuple(
                ref
                for ref in self.refs(kind="combo_transition")
                if (
                    ref.span.start_line,
                    ref.span.start_column,
                    ref.span.end_line,
                    ref.span.end_column,
                )
                in spans
                and (
                    ref.source_uri == source_uri
                    if source_uri is not None
                    else ref.ownership == "root"
                )
            )
            if len(candidates) != 1:
                raise SourceIndexError(
                    "combo transition origin is not unique in the source closure"
                )
            raw_ref = candidates[0]
            identity_parts.extend(
                "{}:{}:{}".format(
                    origin.origin_id, origin.term_index, origin.role
                )
                for origin in origin_refs
            )

        identity_parts.extend(
            (
                raw_ref.stable_key,
                str(getattr(transition, "from_state", "")),
                str(getattr(transition, "to_state", "")),
                str(getattr(transition, "event_scope", "")),
            )
        )
        projection_id = hashlib.sha256(
            "\0".join(identity_parts).encode("utf-8")
        ).hexdigest()
        combo_projection_key = getattr(
            transition, "combo_projection_key", None
        )
        if combo_projection_key:
            model_owner_path = tuple(combo_projection_key[0])
        else:
            parent_ref = getattr(transition, "parent_ref", None)
            parent = parent_ref() if callable(parent_ref) else None
            model_owner_path = tuple(getattr(parent, "path", raw_ref.owner_path))
        return SourceProjection(
            projection_id=projection_id,
            physical_ref=raw_ref,
            edge_chain=(),
            alias_chain=(),
            projected_owner_path=(
                model_owner_path
                + (
                    str(getattr(transition, "from_state", "")),
                    str(getattr(transition, "to_state", "")),
                )
            ),
            ownership="generated",
            editable=False,
        )

    def text_for_declaration(self, declaration: DeclarationRef) -> str:
        candidates = (
            ref
            for ref in self.refs_by_document.get(declaration.file_id, ())
            if ref.declaration_ref == declaration
            and ref.stable_key == declaration.stable_key
            and ref.span == declaration.span
        )
        ref = next(candidates, None)
        if ref is None:
            raise StaleSourceRefError(
                "declaration ref does not belong to this source snapshot"
            )
        return self.text_for_ref(ref)

    def insertion_anchor(
        self,
        kind: str,
        owner_path: Tuple[str, ...] = (),
        declaration_ref: Optional[DeclarationRef] = None,
    ) -> InsertionAnchor:
        document = self.root_document
        container_ref = None  # type: Optional[SourceRef]
        slot = kind
        if kind == "variable" and not owner_path:
            offset = 0
            container_declaration = None
        elif kind in {"state", "event", "transition", "lifecycle"}:
            container_ref = next(
                (
                    ref
                    for ref in self.refs(kind="state", document_id=document.document_id)
                    if ref.owner_path == owner_path
                ),
                None,
            )
            if container_ref is None:
                raise SourceIndexError(
                    "no editable state container for {}".format(owner_path)
                )
            container_text = self.text_for_ref(container_ref)
            relative = container_text.rfind("}")
            if relative < 0:
                raise SourceIndexError(
                    "state container has no body insertion point"
                )
            offset = container_ref.span.start_offset + relative
            container_declaration = container_ref.declaration_ref
        elif kind in {"action", "guard", "effect"}:
            if declaration_ref is None:
                raise SourceIndexError(
                    "{} insertion requires a declaration ref".format(kind)
                )
            declaration_source_ref = next(
                (
                    ref
                    for ref in self.refs_by_document.get(
                        declaration_ref.file_id, ()
                    )
                    if ref.declaration_ref == declaration_ref
                    and ref.stable_key == declaration_ref.stable_key
                    and ref.span == declaration_ref.span
                ),
                None,
            )
            if (
                declaration_source_ref is None
                or not declaration_source_ref.editable
                or declaration_source_ref.file_id != document.document_id
            ):
                raise SourceIndexError(
                    "insertion target is not an editable root declaration"
                )
            declaration_text = self.text_for_ref(declaration_source_ref)
            transition_kinds = {
                "transition",
                "combo_transition",
                "forced_transition",
            }
            declaration_kind = declaration_source_ref.kind
            if (
                kind in {"guard", "effect"}
                and declaration_kind not in transition_kinds
            ):
                raise SourceIndexError(
                    "{} insertion requires a transition declaration".format(kind)
                )
            if kind == "action" and not (
                declaration_kind == "lifecycle"
                or (
                    declaration_kind in transition_kinds
                    and re.search(r"\beffect\s*\{", declaration_text)
                    is not None
                )
            ):
                raise SourceIndexError(
                    "action insertion requires a lifecycle or effect block"
                )
            if kind in {"guard", "effect"} and any(
                ref.kind == kind
                and ref.declaration_ref == declaration_ref
                for ref in self.refs_by_document.get(document.document_id, ())
            ):
                raise SourceIndexError(
                    "{} declaration already exists; use its SourceRef".format(kind)
                )
            start = declaration_ref.span.start_offset
            if kind == "action":
                relative = declaration_text.rfind("}")
                if relative < 0:
                    raise SourceIndexError(
                        "action container has no block insertion point"
                    )
                offset = start + relative
            elif kind == "guard":
                effect_match = re.search(r"\beffect\s*\{", declaration_text)
                if effect_match is not None:
                    offset = start + effect_match.start()
                else:
                    offset = start + len(declaration_text.rstrip())
                    if declaration_text.rstrip().endswith(";"):
                        offset -= 1
            else:
                offset = start + len(declaration_text.rstrip())
                if declaration_text.rstrip().endswith(";"):
                    offset -= 1
            container_declaration = declaration_ref
        else:
            raise SourceIndexError("unsupported insertion slot: {}".format(kind))

        left = document.text[max(0, offset - 32):offset]
        right = document.text[offset:offset + 32]
        return InsertionAnchor(
            source_uri=document.uri,
            file_id=document.document_id,
            source_revision=document.revision,
            snapshot_fingerprint=document.snapshot_fingerprint,
            document_sha256=document.sha256,
            offset=offset,
            slot=slot,
            owner_path=owner_path,
            left_context_sha256=hashlib.sha256(
                left.encode("utf-8")
            ).hexdigest(),
            right_context_sha256=hashlib.sha256(
                right.encode("utf-8")
            ).hexdigest(),
            container_declaration_ref=container_declaration,
            editable=True,
        )

    def validate_insertion_anchor(self, anchor: InsertionAnchor) -> None:
        document = self.root_document
        if (
            not anchor.editable
            or anchor.source_uri != document.uri
            or anchor.file_id != document.document_id
            or anchor.source_revision != document.revision
            or anchor.snapshot_fingerprint != document.snapshot_fingerprint
            or anchor.document_sha256 != document.sha256
            or not 0 <= anchor.offset <= len(document.text)
        ):
            raise StaleSourceRefError(
                "insertion anchor does not match the current root snapshot"
            )
        left = document.text[max(0, anchor.offset - 32):anchor.offset]
        right = document.text[anchor.offset:anchor.offset + 32]
        if (
            hashlib.sha256(left.encode("utf-8")).hexdigest()
            != anchor.left_context_sha256
            or hashlib.sha256(right.encode("utf-8")).hexdigest()
            != anchor.right_context_sha256
        ):
            raise StaleSourceRefError(
                "insertion anchor context no longer matches the source"
            )
        if anchor.container_declaration_ref is not None:
            self.text_for_declaration(anchor.container_declaration_ref)


def _rule_name(context: ParserRuleContext) -> str:
    return GrammarParser.ruleNames[context.getRuleIndex()]


def _context_contains_rule(context: ParserRuleContext, names: Iterable[str]) -> bool:
    expected = set(names)
    for child in context.getChildren():
        if not isinstance(child, ParserRuleContext):
            continue
        if _rule_name(child) in expected or _context_contains_rule(child, expected):
            return True
    return False


def _span(document: SourceDocument, context: ParserRuleContext) -> SourceSpan:
    start = context.start.start
    end = context.stop.stop + 1
    start_line, start_column = document.offset_to_line_column(start)
    end_line, end_column = document.offset_to_line_column(end)
    return SourceSpan(
        start_offset=start,
        end_offset=end,
        start_line=start_line,
        start_column=start_column,
        end_line=end_line,
        end_column=end_column,
    )


def _offset_span(document: SourceDocument, start: int, end: int) -> SourceSpan:
    start_line, start_column = document.offset_to_line_column(start)
    end_line, end_column = document.offset_to_line_column(end)
    return SourceSpan(
        start_offset=start,
        end_offset=end,
        start_line=start_line,
        start_column=start_column,
        end_line=end_line,
        end_column=end_column,
    )


def _token_text(context: ParserRuleContext, attribute: str) -> Optional[str]:
    token = getattr(context, attribute, None)
    return token.text if token is not None else None


def _terminal_text(context: ParserRuleContext, accessor: str) -> Optional[str]:
    method = getattr(context, accessor, None)
    if method is None:
        return None
    terminal = method()
    return terminal.getText() if terminal is not None else None


def _fingerprint_manifest(manifest: Iterable[Tuple[str, str]]) -> str:
    payload = "\n".join("{}\0{}".format(*item) for item in manifest)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _content_identity(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _index_document(
    document: SourceDocument, ownership: str
) -> Tuple[Tuple[SourceRef, ...], Tuple[_ImportDirective, ...]]:
    parse_state_machine_dsl(document.text)
    lexer = GrammarLexer(InputStream(document.text))
    parser = GrammarParser(CommonTokenStream(lexer))
    tree = parser.state_machine_dsl()

    refs = []
    imports = []
    ordinals = defaultdict(int)  # type: DefaultDict[Tuple[str, Tuple[str, ...], str], int]

    def add_ref(
        context: ParserRuleContext,
        kind: str,
        owner_path: Tuple[str, ...],
        semantic_base: str,
        declaration_ref: Optional[DeclarationRef] = None,
    ) -> SourceRef:
        source_span = _span(document, context)
        source_text = document.text[
            source_span.start_offset:source_span.end_offset
        ]
        ordinal_key = (kind, owner_path, semantic_base)
        ordinal = ordinals[ordinal_key]
        ordinals[ordinal_key] += 1
        semantic_key = semantic_base
        if ordinal:
            semantic_key = "{}#{}".format(semantic_base, ordinal)
        range_sha256 = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        if declaration_ref is None:
            declaration_ref = DeclarationRef(
                source_uri=document.uri,
                file_id=document.document_id,
                source_revision=document.revision,
                snapshot_fingerprint=document.snapshot_fingerprint,
                document_sha256=document.sha256,
                kind=kind,
                span=source_span,
                stable_key=semantic_key,
                range_sha256=range_sha256,
            )
        ref = SourceRef(
            source_uri=document.uri,
            file_id=document.document_id,
            source_revision=document.revision,
            snapshot_fingerprint=document.snapshot_fingerprint,
            document_sha256=document.sha256,
            kind=kind,
            span=source_span,
            stable_key=semantic_key,
            ownership=ownership,
            editable=ownership == "root",
            declaration_ref=declaration_ref,
            owner_path=owner_path,
            range_sha256=range_sha256,
        )
        refs.append(ref)
        return ref

    def add_offset_ref(
        start: int,
        end: int,
        kind: str,
        owner_path: Tuple[str, ...],
        stable_key: str,
        declaration_ref: DeclarationRef,
        deletion_replacement: str = "",
    ) -> SourceRef:
        source_text = document.text[start:end]
        source_span = _offset_span(document, start, end)
        ref = SourceRef(
            source_uri=document.uri,
            file_id=document.document_id,
            source_revision=document.revision,
            snapshot_fingerprint=document.snapshot_fingerprint,
            document_sha256=document.sha256,
            kind=kind,
            span=source_span,
            stable_key=stable_key,
            ownership=ownership,
            editable=ownership == "root",
            declaration_ref=declaration_ref,
            owner_path=owner_path,
            range_sha256=hashlib.sha256(
                source_text.encode("utf-8")
            ).hexdigest(),
            deletion_replacement=deletion_replacement,
        )
        refs.append(ref)
        return ref

    def walk(
        context: ParserRuleContext,
        owner_path: Tuple[str, ...] = (),
        declaration_key: str = "program",
        declaration_kind: Optional[str] = None,
        declaration_ref: Optional[DeclarationRef] = None,
    ) -> None:
        rule = _rule_name(context)
        current_owner = owner_path
        current_key = declaration_key
        current_kind = declaration_kind
        current_declaration_ref = declaration_ref

        if rule == "state_definition":
            state_name = _token_text(context, "state_id") or "<state>"
            current_owner = (*owner_path, state_name)
            current_key = "state:{}".format(".".join(current_owner))
            state_ref = add_ref(context, "state", current_owner, current_key)
            current_declaration_ref = state_ref.declaration_ref
            current_kind = "state"
        elif rule == "def_assignment":
            name = (
                _token_text(context, "var_name")
                or _token_text(context, "def_name")
                or _terminal_text(context, "ID")
            )
            current_key = "variable:{}".format(name or len(refs))
            variable_ref = add_ref(context, "variable", owner_path, current_key)
            current_declaration_ref = variable_ref.declaration_ref
            current_kind = "variable"
        elif rule == "event_definition":
            name = _token_text(context, "event_name") or "<event>"
            current_key = "event:{}:{}".format(".".join(owner_path), name)
            event_ref = add_ref(context, "event", owner_path, current_key)
            current_declaration_ref = event_ref.declaration_ref
            current_kind = "event"
        elif rule == "transition_definition":
            kind = (
                "combo_transition"
                if _context_contains_rule(
                    context,
                    {
                        "entry_combo_transition_trigger",
                        "combo_transition_trigger",
                    },
                )
                else "transition"
            )
            declaration_text = document.text[context.start.start:context.stop.stop + 1]
            current_key = "{}:{}:{}".format(
                kind, ".".join(owner_path), _content_identity(declaration_text)
            )
            transition_ref = add_ref(context, kind, owner_path, current_key)
            current_declaration_ref = transition_ref.declaration_ref
            declaration_text = document.text[
                context.start.start:context.stop.stop + 1
            ]
            effect_match = re.search(r"\beffect\s*\{", declaration_text)
            if effect_match is not None:
                effect_start = context.start.start + effect_match.start()
                add_offset_ref(
                    effect_start,
                    context.stop.stop + 1,
                    "effect",
                    owner_path,
                    current_key + "/effect",
                    current_declaration_ref,
                    deletion_replacement=";",
                )
            current_kind = kind
        elif rule == "transition_force_definition":
            declaration_text = document.text[context.start.start:context.stop.stop + 1]
            current_key = "forced_transition:{}:{}".format(
                ".".join(owner_path), _content_identity(declaration_text)
            )
            forced_ref = add_ref(
                context, "forced_transition", owner_path, current_key
            )
            current_declaration_ref = forced_ref.declaration_ref
            current_kind = "forced_transition"
        elif rule in {
            "enter_definition",
            "during_definition",
            "exit_definition",
            "during_aspect_definition",
        }:
            declaration_text = document.text[context.start.start:context.stop.stop + 1]
            current_key = "lifecycle:{}:{}:{}".format(
                ".".join(owner_path), rule, _content_identity(declaration_text)
            )
            lifecycle_ref = add_ref(
                context, "lifecycle", owner_path, current_key
            )
            current_declaration_ref = lifecycle_ref.declaration_ref
            current_kind = "lifecycle"
        elif rule == "operation_assignment":
            action_text = document.text[context.start.start:context.stop.stop + 1]
            current_key = "{}/action/{}".format(
                declaration_key, _content_identity(action_text)
            )
            add_ref(
                context,
                "action",
                owner_path,
                current_key,
                declaration_ref=current_declaration_ref,
            )
            current_kind = "action"
        elif rule == "cond_expression":
            parent = context.parentCtx
            if not (
                isinstance(parent, ParserRuleContext)
                and _rule_name(parent) == "cond_expression"
            ):
                kind = (
                    "guard"
                    if declaration_kind
                    in {"transition", "combo_transition", "forced_transition"}
                    else "expression"
                )
                add_ref(
                    context,
                    kind,
                    owner_path,
                    "{}/{}".format(declaration_key, kind),
                    declaration_ref=current_declaration_ref,
                )
                if kind == "guard" and current_declaration_ref is not None:
                    declaration_start = current_declaration_ref.span.start_offset
                    declaration_end = current_declaration_ref.span.end_offset
                    expression_start = context.start.start
                    expression_end = context.stop.stop + 1
                    open_bracket = document.text.rfind(
                        "[", declaration_start, expression_start + 1
                    )
                    close_bracket = document.text.find(
                        "]", expression_end, declaration_end
                    )
                    if open_bracket >= declaration_start and close_bracket >= 0:
                        clause_start = open_bracket
                        prefix = document.text[declaration_start:open_bracket]
                        delimiter_match = re.search(
                            r"(?:(?::\s*if)|:|\+)\s*$", prefix
                        )
                        if delimiter_match is not None:
                            clause_start = (
                                declaration_start + delimiter_match.start()
                            )
                        add_offset_ref(
                            clause_start,
                            close_bracket + 1,
                            "guard_clause",
                            owner_path,
                            current_declaration_ref.stable_key + "/guard_clause",
                            current_declaration_ref,
                        )
        elif rule == "import_statement":
            raw_path = _token_text(context, "import_path")
            alias = _token_text(context, "state_alias") or "<alias>"
            if raw_path is None:
                raise SourceIndexError("import statement does not contain a path")
            source_path = ast.literal_eval(raw_path)
            current_key = "import:{}:{}:{}".format(
                ".".join(owner_path), alias, source_path
            )
            ref = add_ref(context, "import", owner_path, current_key)
            current_declaration_ref = ref.declaration_ref
            imports.append(
                _ImportDirective(
                    source_ref=ref,
                    source_path=source_path,
                    alias=alias,
                    owner_path=owner_path,
                )
            )
            current_kind = "import"

        for child in context.getChildren():
            if isinstance(child, ParserRuleContext):
                walk(
                    child,
                    current_owner,
                    current_key,
                    current_kind,
                    current_declaration_ref,
                )

    walk(tree)
    refs.sort(key=lambda ref: (ref.span.start_offset, -ref.span.end_offset, ref.kind))
    return tuple(refs), tuple(imports)


class _SourceIndexBuilder:
    def __init__(
        self,
        root_path: PathLike,
        revision: int,
        snapshot: _CapturedSnapshot,
    ):
        self.root_path = canonical_path(root_path)
        self.revision = revision
        self.snapshot = snapshot
        self.snapshot_fingerprint = snapshot.fingerprint
        self.documents = {}  # type: Dict[str, SourceDocument]
        self.refs_by_document = {}  # type: Dict[str, Tuple[SourceRef, ...]]
        self.imports = []  # type: List[ImportEdge]

    def build(self) -> SourceIndex:
        root = self._visit(self.root_path, "root", ())
        manifest = tuple(
            sorted((document.uri, document.sha256) for document in self.documents.values())
        )
        projections = _build_import_projections(
            root.document_id,
            self.documents,
            self.refs_by_document,
            tuple(self.imports),
        )
        return SourceIndex(
            root_document_id=root.document_id,
            documents=MappingProxyType(dict(self.documents)),
            refs_by_document=MappingProxyType(dict(self.refs_by_document)),
            imports=tuple(self.imports),
            closure_manifest=manifest,
            closure_fingerprint=_fingerprint_manifest(manifest),
            projections=projections,
        )

    def _visit(
        self,
        path: Path,
        ownership: str,
        stack: Sequence[str],
    ) -> SourceDocument:
        resolved = canonical_path(path)
        if not resolved.is_file():
            raise SourceImportNotFoundError(
                "import source file does not exist: {}".format(resolved)
            )
        document = self._read_document(resolved)
        if document.document_id in stack:
            chain = [self.documents[item].path for item in stack if item in self.documents]
            chain.append(document.path)
            raise SourceImportCycleError(
                "circular import detected: {}".format(" -> ".join(chain))
            )
        if document.document_id in self.documents:
            return self.documents[document.document_id]

        self.documents[document.document_id] = document
        refs, directives = _index_document(document, ownership)
        self.refs_by_document[document.document_id] = refs
        next_stack = (*stack, document.document_id)

        for directive in directives:
            source_path = Path(directive.source_path)
            target_path = (
                source_path
                if source_path.is_absolute()
                else Path(document.path).parent / source_path
            )
            resolved_target = canonical_path(target_path)
            if not resolved_target.is_file():
                raise SourceImportNotFoundError(
                    "import {!r} from {} does not exist: {}".format(
                        directive.source_path, document.path, resolved_target
                    )
                )
            target = self._read_document(resolved_target)
            if target.document_id in next_stack:
                chain = [self.documents[item].path for item in next_stack]
                chain.append(target.path)
                raise SourceImportCycleError(
                    "circular import detected: {}".format(" -> ".join(chain))
                )
            if target.document_id not in self.documents:
                target = self._visit(resolved_target, "imported", next_stack)
            else:
                target = self.documents[target.document_id]
            self.imports.append(
                ImportEdge(
                    source_document_id=document.document_id,
                    target_document_id=target.document_id,
                    source_ref=directive.source_ref,
                    source_path=directive.source_path,
                    alias=directive.alias,
                    owner_path=directive.owner_path,
                    instance_id=hashlib.sha256(
                        "\0".join(
                            (
                                document.document_id,
                                directive.source_ref.semantic_key,
                                target.document_id,
                                directive.alias,
                            )
                        ).encode("utf-8")
                    ).hexdigest(),
                )
            )
        return document

    def _read_document(self, path: Path) -> SourceDocument:
        resolved = canonical_path(path)
        path_key = os.path.normcase(str(resolved))
        raw = self.snapshot.raw_by_path.get(path_key)
        if raw is None:
            raise SourceIndexError(
                "source file was not present in the captured snapshot: {}".format(
                    resolved
                ),
                path=str(resolved),
                operation="snapshot",
            )
        return SourceDocument.from_bytes(
            resolved,
            raw,
            revision=self.revision,
            encoding=self.snapshot.encoding_by_path.get(path_key),
            snapshot_fingerprint=self.snapshot_fingerprint,
        )


def _capture_snapshot(
    root_path: PathLike,
    root_encoding: Optional[str] = None,
    encoding_resolver: Optional[Callable[[Path], Optional[str]]] = None,
) -> _CapturedSnapshot:
    documents = {}  # type: Dict[str, SourceDocument]
    raw_by_path = {}  # type: Dict[str, bytes]
    encoding_by_path = {}  # type: Dict[str, str]

    def visit(path: Path, stack: Tuple[str, ...]) -> None:
        resolved = canonical_path(path)
        selected_encoding = (
            root_encoding
            if not stack and root_encoding is not None
            else encoding_resolver(resolved)
            if encoding_resolver is not None
            else None
        )
        try:
            document = SourceDocument.from_file(
                resolved, encoding=selected_encoding
            )
        except OSError as error:
            raise SourceIndexError(
                "unable to read source file {}: {}".format(resolved, error),
                path=str(resolved),
                operation="read",
            ) from error
        except UnicodeError as error:
            raise SourceIndexError(
                "unable to decode source file {}: {}".format(resolved, error),
                path=str(resolved),
                operation="decode",
            ) from error
        if document.document_id in stack:
            raise SourceImportCycleError(
                "circular import detected while discovering {}".format(resolved)
            )
        if document.document_id in documents:
            return
        documents[document.document_id] = document
        path_key = os.path.normcase(document.path)
        raw_by_path[path_key] = document.original_bytes
        encoding_by_path[path_key] = document.encoding
        _, directives = _index_document_impl(document, "root" if not stack else "imported")
        next_stack = stack + (document.document_id,)
        for directive in directives:
            source_path = Path(directive.source_path)
            target_path = (
                source_path
                if source_path.is_absolute()
                else Path(document.path).parent / source_path
            )
            resolved_target = canonical_path(target_path)
            if not resolved_target.is_file():
                raise SourceImportNotFoundError(
                    "import {!r} from {} does not exist: {}".format(
                        directive.source_path, document.path, resolved_target
                    )
                )
            visit(resolved_target, next_stack)

    visit(canonical_path(root_path), ())
    manifest = tuple(
        sorted((item.uri, item.sha256) for item in documents.values())
    )
    return _CapturedSnapshot(
        manifest=manifest,
        fingerprint=_fingerprint_manifest(manifest),
        raw_by_path=MappingProxyType(dict(raw_by_path)),
        encoding_by_path=MappingProxyType(dict(encoding_by_path)),
    )


def _discover_manifest(root_path: PathLike) -> Tuple[Tuple[str, str], ...]:
    return _capture_snapshot(root_path).manifest


_index_document_impl = _index_document


def _build_import_projections(
    root_document_id: str,
    documents: Mapping[str, SourceDocument],
    refs_by_document: Mapping[str, Tuple[SourceRef, ...]],
    imports: Tuple[ImportEdge, ...],
) -> Tuple[SourceProjection, ...]:
    edges_by_source = defaultdict(list)  # type: DefaultDict[str, List[ImportEdge]]
    for edge in imports:
        edges_by_source[edge.source_document_id].append(edge)
    projections = []  # type: List[SourceProjection]

    def visit(
        document_id: str,
        edge_chain: Tuple[str, ...],
        alias_chain: Tuple[str, ...],
        projected_prefix: Tuple[str, ...],
    ) -> None:
        for edge in edges_by_source.get(document_id, ()):
            next_edge_chain = edge_chain + (edge.instance_id,)
            next_alias_chain = alias_chain + (edge.alias,)
            source_owner_path = edge.owner_path
            if document_id != root_document_id and source_owner_path:
                source_owner_path = source_owner_path[1:]
            next_prefix = projected_prefix + source_owner_path + (edge.alias,)
            for ref in refs_by_document.get(edge.target_document_id, ()):
                projection_id = hashlib.sha256(
                    "\0".join(next_edge_chain + (ref.stable_key,)).encode("utf-8")
                ).hexdigest()
                projections.append(
                    SourceProjection(
                        projection_id=projection_id,
                        physical_ref=ref,
                        edge_chain=next_edge_chain,
                        alias_chain=next_alias_chain,
                        projected_owner_path=(
                            next_prefix
                            + (ref.owner_path[1:] if ref.owner_path else ())
                        ),
                    )
                )
            visit(
                edge.target_document_id,
                next_edge_chain,
                next_alias_chain,
                next_prefix,
            )

    visit(root_document_id, (), (), ())
    return tuple(projections)


def _build_from_snapshot(
    root_path: PathLike,
    before: _CapturedSnapshot,
    revision: Optional[int],
) -> SourceIndex:
    before_manifest = before.manifest
    before_fingerprint = before.fingerprint
    if revision is None:
        revision = int(before_fingerprint[:16], 16)
    return _SourceIndexBuilder(
        root_path,
        revision=revision,
        snapshot=before,
    ).build()


def _require_snapshot_unchanged(
    root_path: PathLike,
    before_manifest: Tuple[Tuple[str, str], ...],
    index: SourceIndex,
    root_encoding: Optional[str] = None,
    encoding_resolver: Optional[Callable[[Path], Optional[str]]] = None,
) -> None:
    after_manifest = _capture_snapshot(
        root_path,
        root_encoding=root_encoding,
        encoding_resolver=encoding_resolver,
    ).manifest
    if (
        before_manifest != index.closure_manifest
        or before_manifest != after_manifest
    ):
        raise SourceSnapshotChangedError(
            "source dependency snapshot changed while the index was being built",
            path=str(canonical_path(root_path)),
            operation="snapshot",
        )


def build_source_index(
    root_path: PathLike,
    revision: Optional[int] = None,
    encoding: Optional[str] = None,
    encoding_resolver: Optional[Callable[[Path], Optional[str]]] = None,
) -> SourceIndex:
    before = _capture_snapshot(
        root_path,
        root_encoding=encoding,
        encoding_resolver=encoding_resolver,
    )
    index = _build_from_snapshot(root_path, before, revision)
    _require_snapshot_unchanged(
        root_path,
        before.manifest,
        index,
        root_encoding=encoding,
        encoding_resolver=encoding_resolver,
    )
    return index


def load_with_source_index(
    root_path: PathLike,
    loader: Callable[[SourceIndex], T],
    revision: Optional[int] = None,
    encoding: Optional[str] = None,
    encoding_resolver: Optional[Callable[[Path], Optional[str]]] = None,
) -> Tuple[SourceIndex, T]:
    before = _capture_snapshot(
        root_path,
        root_encoding=encoding,
        encoding_resolver=encoding_resolver,
    )
    index = _build_from_snapshot(root_path, before, revision)
    result = loader(index)
    _require_snapshot_unchanged(
        root_path,
        before.manifest,
        index,
        root_encoding=encoding,
        encoding_resolver=encoding_resolver,
    )
    return index, result
