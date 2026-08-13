from __future__ import annotations

import json
import shlex
import sys
import threading
from pathlib import Path

import httpx

from mycode.hooks.actions import HookActionExecutor
from mycode.hooks.models import AgentAction, CommandAction, FrozenDict, HookEvent, HTTPAction


def event(name: str = "turn_start") -> HookEvent:
    return HookEvent(  # type: ignore[arg-type]
        name,
        FrozenDict({"schema_version": 1, "event": name, "marker": "动态值"}),
    )


def test_command_runs_in_workspace_and_receives_payload_on_stdin(tmp_path: Path) -> None:
    script = (
        f"{shlex.quote(sys.executable)} -c \"import json,pathlib,sys; "
        "p=json.load(sys.stdin); "
        "pathlib.Path('hook-result.txt').write_text(p['marker'], encoding='utf-8')\""
    )
    executor = HookActionExecutor(tmp_path)
    try:
        outcome = executor.execute(CommandAction(script), event())
    finally:
        executor.close()

    assert outcome.status == "success"
    assert (tmp_path / "hook-result.txt").read_text(encoding="utf-8") == "动态值"


def test_command_accepts_scoped_workspace_and_environment(tmp_path: Path) -> None:
    child = tmp_path / "child"
    child.mkdir()
    executor = HookActionExecutor(tmp_path)
    try:
        outcome = executor.execute(
            CommandAction("printf \"$MEWCODE_HOOK_SCOPE\" > scoped.txt"),
            event(),
            workspace_root=child,
            process_environment={"MEWCODE_HOOK_SCOPE": "child"},
        )
    finally:
        executor.close()

    assert outcome.status == "success"
    assert (child / "scoped.txt").read_text(encoding="utf-8") == "child"
    assert not (tmp_path / "scoped.txt").exists()


def test_command_tool_before_exit_two_denies_with_bounded_stderr(tmp_path: Path) -> None:
    executor = HookActionExecutor(tmp_path)
    try:
        outcome = executor.execute(
            CommandAction(
                f"{shlex.quote(sys.executable)} -c \"import sys; "
                "sys.stderr.write('x' * 5000); sys.exit(2)\""
            ),
            event("tool_before"),
        )
    finally:
        executor.close()

    assert outcome.status == "denied"
    assert outcome.code == "command_denied"
    assert len(outcome.reason) == 2_000


def test_tool_denial_reasons_are_redacted_for_model_feedback(tmp_path: Path) -> None:
    executor = HookActionExecutor(tmp_path)
    try:
        command = executor.execute(
            CommandAction("printf 'API_KEY=secret-value Bearer bearer-value' >&2; exit 2"),
            event("tool_before"),
        )
    finally:
        executor.close()

    assert command.status == "denied"
    assert "secret-value" not in command.reason
    assert "bearer-value" not in command.reason
    assert command.reason == "API_KEY=<redacted> Bearer <redacted>"


def test_command_timeout_and_non_interceptor_failure_fail_closed_to_outcome(tmp_path: Path) -> None:
    executor = HookActionExecutor(tmp_path)
    try:
        timed_out = executor.execute(
            CommandAction(
                f"{shlex.quote(sys.executable)} -c \"import time; time.sleep(2)\"",
                timeout_seconds=0.1,
            ),
            event(),
        )
        failed = executor.execute(CommandAction("exit 7"), event("tool_before"))
    finally:
        executor.close()

    assert (timed_out.status, timed_out.code) == ("failed", "command_timeout")
    assert (failed.status, failed.code) == ("failed", "command_failed")


def test_http_sends_fixed_json_protocol_and_custom_fields(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    executor = HookActionExecutor(
        tmp_path,
        http_client_factory=lambda **kwargs: httpx.Client(
            transport=httpx.MockTransport(handler),
            **kwargs,
        ),
    )
    try:
        outcome = executor.execute(
            HTTPAction("https://example.com/hook", "PATCH", {"X-Test": "static"}),
            event(),
        )
    finally:
        executor.close()

    assert outcome.status == "success"
    assert requests[0].method == "PATCH"
    assert requests[0].headers["content-type"] == "application/json"
    assert requests[0].headers["x-test"] == "static"
    assert json.loads(requests[0].content)["marker"] == "动态值"


def test_http_tool_before_parses_strict_allow_and_deny(tmp_path: Path) -> None:
    bodies = iter(
        [
            {"decision": "allow"},
            {"decision": "deny", "reason": "blocked API_TOKEN=hidden"},
            {"decision": "allow", "extra": True},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(bodies))

    executor = HookActionExecutor(
        tmp_path,
        http_client_factory=lambda **kwargs: httpx.Client(
            transport=httpx.MockTransport(handler),
            **kwargs,
        ),
    )
    action = HTTPAction("https://example.com/hook")
    try:
        allow = executor.execute(action, event("tool_before"))
        deny = executor.execute(action, event("tool_before"))
        invalid = executor.execute(action, event("tool_before"))
    finally:
        executor.close()

    assert (allow.status, allow.code) == ("success", "http_allowed")
    assert (deny.status, deny.reason) == ("denied", "blocked API_TOKEN=<redacted>")
    assert (invalid.status, invalid.code) == ("failed", "http_invalid_decision")


def test_http_errors_do_not_expose_header_values(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret-token", request=request)

    executor = HookActionExecutor(
        tmp_path,
        http_client_factory=lambda **kwargs: httpx.Client(
            transport=httpx.MockTransport(handler),
            **kwargs,
        ),
    )
    try:
        outcome = executor.execute(
            HTTPAction("https://example.com", headers={"Authorization": "secret-token"}),
            event(),
        )
    finally:
        executor.close()

    assert outcome.status == "failed"
    assert "secret-token" not in outcome.reason


def test_http_timeout_and_oversized_invalid_decision_are_bounded_failures(tmp_path: Path) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    timeout_executor = HookActionExecutor(
        tmp_path,
        http_client_factory=lambda **kwargs: httpx.Client(
            transport=httpx.MockTransport(timeout),
            **kwargs,
        ),
    )
    try:
        timed_out = timeout_executor.execute(HTTPAction("https://example.com"), event())
    finally:
        timeout_executor.close()

    def oversized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 100_000)

    oversized_executor = HookActionExecutor(
        tmp_path,
        http_client_factory=lambda **kwargs: httpx.Client(
            transport=httpx.MockTransport(oversized),
            **kwargs,
        ),
    )
    try:
        invalid = oversized_executor.execute(
            HTTPAction("https://example.com"),
            event("tool_before"),
        )
    finally:
        oversized_executor.close()

    assert (timed_out.status, timed_out.code) == ("failed", "http_timeout")
    assert (invalid.status, invalid.code) == ("failed", "http_invalid_decision")


def test_agent_is_placeholder_and_prompt_is_reserved_for_runtime(tmp_path: Path) -> None:
    from mycode.hooks.models import PromptAction

    executor = HookActionExecutor(tmp_path)
    try:
        agent = executor.execute(AgentAction("investigate"), event())
        prompt = executor.execute(PromptAction("remember"), event())
    finally:
        executor.close()

    assert agent.status == "placeholder"
    assert agent.code == "agent_not_implemented"
    assert prompt.code == "prompt_runtime_required"


def test_synchronous_and_agent_actions_do_not_start_background_workers(tmp_path: Path) -> None:
    before = {thread.name for thread in threading.enumerate()}
    executor = HookActionExecutor(tmp_path)
    try:
        executor.execute(AgentAction("later"), event())
        executor.execute(CommandAction("exit 0"), event())
        during = {thread.name for thread in threading.enumerate()}
    finally:
        executor.close()

    assert not {name for name in during - before if name.startswith("mycode-hook-")}


def test_async_queue_is_bounded_and_callbacks_receive_completion(tmp_path: Path) -> None:
    executor = HookActionExecutor(tmp_path, worker_count=1, queue_size=1)
    started = threading.Event()
    release = threading.Event()
    completed: list[str] = []

    def controlled(action, hook_event):
        started.set()
        release.wait(2)
        from mycode.hooks.models import HookActionOutcome

        return HookActionOutcome("success", code="controlled")

    executor._execute_sync = controlled  # type: ignore[method-assign]
    action = CommandAction("unused", asynchronous=True)
    first = executor.execute(action, event(), lambda outcome: completed.append(outcome.code))
    assert started.wait(1)
    second = executor.execute(action, event())
    full = executor.execute(action, event())
    release.set()
    executor._jobs.join()
    executor.close()

    assert first.status == "submitted"
    assert second.status == "submitted"
    assert (full.status, full.code) == ("failed", "async_queue_full")
    assert completed == ["controlled"]


def test_close_cancels_queued_async_action_without_waiting(tmp_path: Path) -> None:
    executor = HookActionExecutor(tmp_path, worker_count=1, queue_size=2)
    started = threading.Event()
    release = threading.Event()
    callbacks: list[str] = []

    def controlled(action, hook_event):
        started.set()
        release.wait(2)
        from mycode.hooks.models import HookActionOutcome

        return HookActionOutcome("success", code="controlled")

    executor._execute_sync = controlled  # type: ignore[method-assign]
    action = CommandAction("unused", asynchronous=True)
    executor.execute(action, event())
    assert started.wait(1)
    executor.execute(action, event(), lambda outcome: callbacks.append(outcome.code))
    executor.close()
    release.set()

    assert callbacks == ["shutdown"]
