from types import SimpleNamespace

from pyfcstm.diagnostics.codes import CODE_REGISTRY
from pyfcstm.dsl.error import GrammarParseError, SyntaxFailError
from pyfcstm.utils.validate import (
    ModelDiagnostic,
    ModelValidationError,
    Span,
    ValidationError,
)

from app.application.diagnostics import (
    DiagnosticQuery,
    DiagnosticReport,
    DiagnosticService,
    DiagnosticSourceKind,
)


SOURCE_URI = "file:///tmp/model.fcstm"


def test_grammar_parse_errors_preserve_native_syntax_fields_without_fake_code():
    native = SyntaxFailError(7, 3, "state", "mismatched input")

    report = DiagnosticService().from_syntax_error(
        GrammarParseError([native]),
        source_uri=SOURCE_URI,
        source_revision=12,
        dependency_fingerprint="deps-a",
    )

    assert report.source_revision == 12
    assert report.dependency_fingerprint == "deps-a"
    assert len(report.items) == 1
    item = report.items[0]
    assert item.source_kind is DiagnosticSourceKind.SYNTAX
    assert item.source_uri == SOURCE_URI
    assert item.code is None
    assert item.severity is None
    assert item.message == native.msg
    assert item.raw_message == native.raw_msg
    assert item.offending_symbol_text == "state"
    assert (item.span.line, item.span.column) == (7, 3)
    assert item.refs is None
    assert item.suggested_fix is None
    assert item.provenance == "pyfcstm.dsl.error.SyntaxFailError"


def test_standalone_syntax_error_and_non_positional_grammar_item_are_not_fabricated():
    positioned = DiagnosticService().from_syntax_error(
        SyntaxFailError(2, 0, None, "bad token"), SOURCE_URI, 1, None
    ).items[0]
    plain = DiagnosticService().from_syntax_error(
        GrammarParseError([ValueError("grammar failed")]),
        SOURCE_URI,
        1,
        None,
    ).items[0]

    assert positioned.span.line == 2
    assert positioned.span.column == 0
    assert plain.message == "grammar failed"
    assert plain.span is None
    assert plain.raw_message is None


def test_model_validation_maps_structured_and_legacy_entries_independently():
    native = ModelDiagnostic(
        code="E_UNDEFINED_VAR",
        severity="error",
        message="missing variable",
        span=Span(5, 8, 5, 15),
        refs={"var_name": "lost", "referenced_in": "guard"},
    )
    error = ModelValidationError(
        errors=[ValidationError("legacy validation failure")],
        diagnostics=[native],
    )

    report = DiagnosticService().from_model_error(
        error, SOURCE_URI, 9, "deps-model"
    )

    assert len(report.items) == 2
    structured, legacy = report.items
    assert structured.source_kind is DiagnosticSourceKind.MODEL
    assert structured.code == "E_UNDEFINED_VAR"
    assert structured.severity == "error"
    assert structured.refs == {
        "var_name": "lost",
        "referenced_in": "guard",
    }
    assert structured.span.end_column == 15
    assert structured.suggested_fix is None
    assert legacy.code is None
    assert legacy.severity is None
    assert legacy.message == "legacy validation failure"
    assert legacy.provenance.endswith("ValidationError")


def test_model_suggested_fix_comes_only_from_upstream_code_catalog():
    code = next(
        code
        for code, spec in CODE_REGISTRY.items()
        if spec.suggested_fix is not None
    )
    spec = CODE_REGISTRY[code].suggested_fix
    diagnostic = ModelDiagnostic(
        code=code,
        severity=CODE_REGISTRY[code].severity,
        message="catalogued finding",
        refs={"parent_path": "Root"},
    )

    item = DiagnosticService().from_model_error(
        ModelValidationError(diagnostics=[diagnostic]), SOURCE_URI, 1, None
    ).items[0]

    assert item.suggested_fix.kind == spec.kind
    assert item.suggested_fix.target == spec.target
    assert item.suggested_fix.anchor_ref == spec.anchor_ref
    assert item.suggested_fix.text_template == spec.text_template
    assert item.suggested_fix.rationale == spec.rationale


def test_inspect_suggested_fix_preserves_upstream_materialized_text_and_anchor():
    diagnostic = ModelDiagnostic(
        code="W_DEADLOCK_LEAF",
        severity="warning",
        message="leaf cannot exit",
        refs={
            "parent_path": "Root",
            "suggested_fix": {
                "kind": "insert",
                "target": "deadlock_leaf_exit_transition",
                "anchor": {"type": "ref", "ref": "refs.parent_path"},
                "text": "A -> [*];\n",
                "rationale": "Add an exit transition.",
            },
        },
    )

    item = DiagnosticService().from_inspect_report(
        {"diagnostics": [diagnostic]}, SOURCE_URI, 1, None
    ).items[0]

    assert item.suggested_fix.anchor_ref == "refs.parent_path"
    assert item.suggested_fix.text_template == "A -> [*];\n"


def test_inspect_report_maps_native_diagnostics_without_reclassifying_them():
    warning = ModelDiagnostic(
        code="W_DEAD_GUARD",
        severity="warning",
        message="guard cannot pass",
        span=Span(11, 4),
        refs={"state_path": "Root.Active", "expr_text": "false"},
    )
    report = DiagnosticService().from_inspect_report(
        SimpleNamespace(diagnostics=(warning,)),
        SOURCE_URI,
        22,
        "deps-inspect",
    )

    item = report.items[0]
    assert item.source_kind is DiagnosticSourceKind.INSPECT
    assert item.code == "W_DEAD_GUARD"
    assert item.severity == "warning"
    assert item.refs["state_path"] == "Root.Active"
    assert item.source_revision == 22
    assert item.dependency_fingerprint == "deps-inspect"


def test_native_items_adapter_reuses_requested_source_kind_mapping():
    syntax = DiagnosticService().from_native_items(
        (SyntaxFailError(4, 1, "}", "unexpected close"),),
        DiagnosticSourceKind.SYNTAX,
        SOURCE_URI,
        31,
        "deps-native",
    ).items[0]
    inspect = DiagnosticService().from_native_items(
        (
            ModelDiagnostic(
                code="W_DEAD_GUARD",
                severity="warning",
                message="guard cannot pass",
            ),
        ),
        DiagnosticSourceKind.INSPECT,
        SOURCE_URI,
        31,
        "deps-native",
    ).items[0]

    assert syntax.source_kind is DiagnosticSourceKind.SYNTAX
    assert syntax.code is None
    assert syntax.span.line == 4
    assert inspect.source_kind is DiagnosticSourceKind.INSPECT
    assert inspect.code == "W_DEAD_GUARD"
    assert inspect.source_revision == 31


def test_inspect_json_payload_is_supported_as_its_real_serialized_shape():
    report = DiagnosticService().from_inspect_report(
        {
            "diagnostics": [
                {
                    "code": "I_NOTE",
                    "severity": "info",
                    "message": "serialized info",
                    "span": {"line": 3, "column": 2},
                    "refs": {"state_path": "Root"},
                }
            ]
        },
        SOURCE_URI,
        2,
        "deps-json",
    )

    assert report.items[0].message == "serialized info"
    assert report.items[0].span.line == 3
    assert report.items[0].refs == {"state_path": "Root"}


def test_filter_and_search_cover_severity_source_message_code_uri_and_refs():
    service = DiagnosticService()
    syntax = service.from_syntax_error(
        SyntaxFailError(1, 0, "BAD", "unexpected"), SOURCE_URI, 4, "deps"
    ).items[0]
    model = service.from_model_error(
        ModelValidationError(
            diagnostics=[
                ModelDiagnostic(
                    code="E_UNDEFINED_VAR",
                    severity="error",
                    message="Unknown variable",
                    refs={"var_name": "CounterValue"},
                )
            ]
        ),
        "file:///tmp/imported.fcstm",
        4,
        "deps",
    ).items[0]
    report = DiagnosticReport(4, "deps", (syntax, model))

    assert report.select(DiagnosticQuery(severities=("error",))) == (model,)
    assert report.select(
        DiagnosticQuery(source_kinds=(DiagnosticSourceKind.SYNTAX,))
    ) == (syntax,)
    assert report.select(DiagnosticQuery(search="undefined_var")) == (model,)
    assert report.select(DiagnosticQuery(search="countervalue")) == (model,)
    assert report.select(DiagnosticQuery(search="IMPORTED.FCSTM")) == (model,)
    assert report.select(DiagnosticQuery(search="no-match")) == ()


def test_revision_and_dependency_stamp_reject_stale_results():
    report = DiagnosticService().from_syntax_error(
        SyntaxFailError(1, 0, None, "bad"), SOURCE_URI, 8, "deps-8"
    )

    assert report.matches(8, "deps-8")
    assert not report.matches(9, "deps-8")
    assert not report.matches(8, "deps-9")
    assert report.items[0].matches(8, "deps-8")


def test_native_session_items_are_adapted_without_rebuilding_exceptions():
    syntax = SyntaxFailError(2, 4, "bad", "unexpected token")
    model = ModelDiagnostic(
        code="E_UNDEFINED_VAR",
        severity="error",
        message="missing variable",
        span=Span(3, 1),
        refs={"var_name": "lost"},
    )
    service = DiagnosticService()

    syntax_report = service.from_native_items(
        (syntax,), DiagnosticSourceKind.SYNTAX, SOURCE_URI, 5, "deps"
    )
    model_report = service.from_native_items(
        (model, ValidationError("legacy")),
        DiagnosticSourceKind.MODEL,
        SOURCE_URI,
        5,
        "deps",
    )

    assert syntax_report.items[0].offending_symbol_text == "bad"
    assert model_report.items[0].code == "E_UNDEFINED_VAR"
    assert model_report.items[1].message == "legacy"
    assert model_report.items[1].code is None
