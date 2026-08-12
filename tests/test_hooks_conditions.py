import pytest

from mycode.hooks.conditions import condition_matches, parse_clause, parse_condition


def payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "event": "tool_after",
        "tool": {
            "name": "run_command",
            "arguments": {"command": "git status", "nested": {"ok": True}},
        },
        "result": {"ok": False, "data": {"exit_code": 2, "items": [1]}},
    }


def test_all_and_any_conditions_match_scalar_fields() -> None:
    all_condition = parse_condition(
        {"all": ["tool.name(run_command)", "tool.arguments.command(re:^git)"]},
        "tool_after",
    )
    any_condition = parse_condition(
        {"any": ["result.ok(true)", "result.data.exit_code(2)"]},
        "tool_after",
    )

    assert condition_matches(all_condition, payload())
    assert condition_matches(any_condition, payload())


def test_boolean_and_number_use_json_scalar_text() -> None:
    boolean = parse_condition({"all": ["tool.arguments.nested.ok(true)"]}, "tool_after")
    number = parse_condition({"all": ["result.data.exit_code(2)"]}, "tool_after")

    assert condition_matches(boolean, payload())
    assert condition_matches(number, payload())


def test_missing_or_composite_field_never_matches_even_when_negated() -> None:
    missing = parse_condition({"all": ["!result.data.missing(x)"]}, "tool_after")
    composite = parse_condition({"all": ["!result.data.items(x)"]}, "tool_after")

    assert not condition_matches(missing, payload())
    assert not condition_matches(composite, payload())


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"all": []},
        {"all": ["tool.name(x)"], "any": ["tool.name(y)"]},
        {"all": [{"any": ["tool.name(x)"]}]},
    ],
)
def test_invalid_condition_groups_are_rejected(value: object) -> None:
    with pytest.raises(ValueError):
        parse_condition(value, "tool_before")


def test_event_specific_invalid_field_is_rejected() -> None:
    with pytest.raises(ValueError, match="不支持"):
        parse_clause("result.ok(true)", "tool_before")
