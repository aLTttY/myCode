from __future__ import annotations

from mycode.context.estimator import TokenEstimator, approximate_tokens, request_snapshot
from mycode.prompts.modes import DynamicInstruction
from mycode.providers.base import ChatRequest
from mycode.types import Message, TokenUsage, ToolCall, ToolSpec


def request(
    text: str = "hello",
    *,
    parameters: dict[str, object] | None = None,
) -> ChatRequest:
    return ChatRequest(
        stable_system_prompt="stable",
        dynamic_system_messages=(DynamicInstruction(tag="env", content="cwd: /tmp", full=True),),
        optional_system_prompt="optional",
        messages=(
            Message(role="user", content=text),
            Message(
                role="assistant",
                content="",
                tool_calls=(ToolCall(id="1", name="read_file", arguments={"path": "a.txt"}),),
            ),
            Message(role="tool", content='{"ok":true}', tool_call_id="1"),
        ),
        tools=(
            ToolSpec(
                name="read_file",
                description="read",
                parameters=parameters or {"type": "object", "properties": {"path": {"type": "string"}}},
            ),
        ),
    )


def test_approximate_tokens_uses_ascii_and_unicode_weights() -> None:
    assert approximate_tokens("abcdef") == 2
    assert approximate_tokens("中文") == 2
    assert approximate_tokens("abc中") == 2


def test_request_snapshot_is_stable_for_mapping_order() -> None:
    first = request(parameters={"type": "object", "properties": {"b": {}, "a": {}}})
    second = request(parameters={"properties": {"a": {}, "b": {}}, "type": "object"})

    assert request_snapshot(first) == request_snapshot(second)


def test_estimates_complete_request_without_anchor() -> None:
    estimator = TokenEstimator()

    assert estimator.estimate(request()) == approximate_tokens(request_snapshot(request()))


def test_anchor_applies_only_snapshot_delta() -> None:
    estimator = TokenEstimator()
    anchored = request("hello")
    estimator.record_usage(anchored, TokenUsage(input_tokens=1_000))
    grown = request("hello" + "a" * 30)

    expected_delta = estimator.snapshot_score(grown) - estimator.snapshot_score(anchored)
    assert estimator.estimate(grown) == 1_000 + expected_delta


def test_anchor_accounts_for_deletions_and_has_zero_floor() -> None:
    estimator = TokenEstimator()
    large = request("a" * 300)
    estimator.record_usage(large, TokenUsage(input_tokens=5))

    assert estimator.estimate(request("")) == 0


def test_tool_definition_changes_affect_estimate() -> None:
    estimator = TokenEstimator()
    first = request(parameters={"type": "object"})
    estimator.record_usage(first, TokenUsage(input_tokens=100))
    second = request(parameters={"type": "object", "description": "x" * 90})

    assert estimator.estimate(second) > 100


def test_missing_input_usage_does_not_replace_anchor() -> None:
    estimator = TokenEstimator()
    anchored = request("anchor")
    assert estimator.record_usage(anchored, TokenUsage(input_tokens=200)) is True

    assert estimator.record_usage(request("summary"), TokenUsage(output_tokens=10)) is False
    assert estimator.anchor is not None
    assert estimator.anchor.input_tokens == 200
