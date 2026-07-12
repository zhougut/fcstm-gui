import pytest

from app.application.formulas import (
    FormulaKind,
    FormulaValidationRequest,
    FormulaValidationService,
    FormulaValidationStatus,
)


def _validate(
    kind,
    text,
    revision=7,
    token="request-7",
    variable_definitions=None,
):
    return FormulaValidationService().validate(
        FormulaValidationRequest(
            kind=kind,
            text=text,
            source_revision=revision,
            request_token=token,
            variable_definitions=variable_definitions,
        )
    )


@pytest.mark.unittest
@pytest.mark.parametrize(
    ("kind", "text"),
    [
        (FormulaKind.LOGICAL, "x > 0 && y < 3"),
        (FormulaKind.NUMERIC, "x * 2 + 1"),
    ],
)
def test_expression_validation_uses_the_requested_production_grammar(kind, text):
    result = _validate(kind, text)

    assert result.status is FormulaValidationStatus.VALID
    assert result.kind is kind
    assert result.message == "公式有效"
    assert result.location is None
    assert result.source_revision == 7
    assert result.request_token == "request-7"


@pytest.mark.unittest
@pytest.mark.parametrize(
    ("kind", "text"),
    [
        (FormulaKind.LOGICAL, "x +"),
        (FormulaKind.NUMERIC, "x > 0"),
    ],
)
def test_expression_validation_rejects_invalid_mode_specific_input(kind, text):
    result = _validate(kind, text, revision=11, token="latest-field-edit")

    assert result.status is FormulaValidationStatus.INVALID
    assert result.kind is kind
    assert result.message
    assert result.source_revision == 11
    assert result.request_token == "latest-field-edit"
    assert result.location is not None
    assert result.location.line == 1
    assert result.location.column >= 0
    assert 0 <= result.location.offset <= len(text)


@pytest.mark.unittest
def test_effect_validation_loads_a_complete_model_and_executes_real_assembly():
    result = _validate(FormulaKind.EFFECT, "x = x + 1;")

    assert result.status is FormulaValidationStatus.VALID
    assert result.message == "动作有效"


def test_action_validation_declares_identifiers_from_the_edited_document_field():
    effect = _validate(
        FormulaKind.EFFECT,
        "count = count + delta;",
        variable_definitions="def int count = 0;\ndef int delta = 1;",
    )
    lifecycle = _validate(
        FormulaKind.LIFECYCLE,
        "total = total + amount;",
        variable_definitions="def int total = 0;\ndef int amount = 1;",
    )

    assert effect.status is FormulaValidationStatus.VALID
    assert lifecycle.status is FormulaValidationStatus.VALID


def test_action_validation_does_not_invent_unknown_document_variables():
    result = _validate(FormulaKind.EFFECT, "count = count + 1;")

    assert result.status is FormulaValidationStatus.INVALID


@pytest.mark.unittest
def test_effect_validation_rejects_invalid_action_with_relative_location():
    text = "x = ;"

    result = _validate(FormulaKind.EFFECT, text)

    assert result.status is FormulaValidationStatus.INVALID
    assert result.message
    assert result.location is not None
    assert result.location.line == 1
    assert result.location.column == text.index(";")
    assert result.location.offset == text.index(";")


@pytest.mark.unittest
def test_lifecycle_validation_loads_a_complete_model_and_executes_real_assembly():
    result = _validate(FormulaKind.LIFECYCLE, "x = x + 1;")

    assert result.status is FormulaValidationStatus.VALID
    assert result.message == "动作有效"


@pytest.mark.unittest
def test_lifecycle_validation_rejects_multiline_action_at_relative_location():
    text = "x = x + 1;\nx = ;"

    result = _validate(FormulaKind.LIFECYCLE, text)

    assert result.status is FormulaValidationStatus.INVALID
    assert result.location is not None
    assert result.location.line == 2
    assert result.location.column == 4
    assert result.location.offset == text.rindex(";")


@pytest.mark.unittest
def test_action_validation_uses_full_loader_not_standalone_operation_parser(monkeypatch):
    import app.application.formulas as formulas

    loaded = []

    def fake_loader(source, path=None):
        loaded.append((source, path))
        return object()

    monkeypatch.setattr(formulas, "load_state_machine_from_text", fake_loader)

    effect = _validate(FormulaKind.EFFECT, "x = 1;")
    lifecycle = _validate(FormulaKind.LIFECYCLE, "x = 2;")

    assert effect.status is FormulaValidationStatus.VALID
    assert lifecycle.status is FormulaValidationStatus.VALID
    assert len(loaded) == 2
    assert "state Root" in loaded[0][0]
    assert "effect {\nx = 1;\n}" in loaded[0][0]
    assert "state Root" in loaded[1][0]
    assert "enter {\nx = 2;\n}" in loaded[1][0]


@pytest.mark.unittest
def test_request_rejects_unknown_kind_and_non_string_token():
    with pytest.raises(ValueError, match="kind"):
        FormulaValidationRequest("unknown", "x", 0, "token")
    with pytest.raises(TypeError, match="request_token"):
        FormulaValidationRequest(FormulaKind.LOGICAL, "true", 0, 123)
