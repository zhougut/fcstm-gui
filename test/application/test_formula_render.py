import pytest

from app.application.formula_render import (
    FormulaRenderService,
    formula_kind_description,
)
from app.application.formulas import FormulaKind
from app.application.formulas import (
    FormulaValidationRequest,
    FormulaValidationService,
)


@pytest.mark.parametrize(
    ("kind", "source", "expected"),
    [
        (FormulaKind.NUMERIC, "sqrt(x ** 2 + y * 3)", ("√", "<sup>", "×")),
        (FormulaKind.LOGICAL, "x >= 2 && y != 0", ("≥", "∧", "≠")),
        (
            FormulaKind.EFFECT,
            "count = count + 1;\nif [count >= 10] { count = 0; }",
            ("count", "←", "如果", "≥"),
        ),
        (
            FormulaKind.LIFECYCLE,
            "elapsed = elapsed + step;",
            ("elapsed", "←", "step"),
        ),
    ],
)
def test_formula_renderer_uses_fcstm_parser_and_semantic_symbols(
    kind, source, expected
):
    result = FormulaRenderService().render(kind, source)

    assert result.kind is kind
    assert result.plain_text
    for fragment in expected:
        assert fragment in result.html


def test_formula_descriptions_document_the_real_fcstm_grammar_families():
    numeric = formula_kind_description(FormulaKind.NUMERIC)
    logical = formula_kind_description(FormulaKind.LOGICAL)
    effect = formula_kind_description(FormulaKind.EFFECT)

    assert "sqrt/cbrt" in numeric.syntax_summary
    assert "pi、E、tau" in numeric.syntax_summary
    assert "and/&&" in logical.syntax_summary
    assert "implies/=&gt;" in logical.syntax_summary
    assert "if [逻辑公式]" in effect.syntax_summary
    assert "分号" in effect.syntax_summary


def test_every_built_in_example_is_accepted_by_the_production_validator():
    definitions = "\n".join(
        "def int {} = 0;".format(name)
        for name in (
            "count",
            "enabled",
            "failed",
            "retry",
            "x",
            "y",
            "error",
            "offset",
            "counter",
            "active",
            "elapsed",
            "step",
            "limit",
        )
    )
    service = FormulaValidationService()
    for kind in FormulaKind:
        for index, source in enumerate(formula_kind_description(kind).examples):
            result = service.validate(
                FormulaValidationRequest(
                    kind=kind,
                    text=source,
                    source_revision=0,
                    request_token="{}-{}".format(kind.value, index),
                    variable_definitions=definitions,
                )
            )
            assert result.is_valid, (kind, source, result.message)
