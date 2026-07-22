import json

import pytest

from mycode.memory.parser import MemoryFormatError, parse_index_response, parse_memory_response


def test_parse_memory_create_and_reject_unknown_update() -> None:
    payload = {"operations": [{
        "action": "create", "scope": "project", "category": "project_knowledge",
        "importance": 3, "title": "Stack", "summary": "Uses Python", "body": "Python 3.10+",
    }]}
    decision = parse_memory_response(f"<memory_update>{json.dumps(payload)}</memory_update>")
    assert decision.operations[0].title == "Stack"

    payload["operations"][0].update({"action": "update", "target_id": "20260721-100000-abcd"})
    with pytest.raises(MemoryFormatError):
        parse_memory_response(f"<memory_update>{json.dumps(payload)}</memory_update>", {"project": set()})


def test_parse_compact_index_requires_all_known_ids() -> None:
    text = '<memory_index>{"entries":[{"id":"20260721-100000-abcd","summary":"short","importance":4}]}</memory_index>'
    result = parse_index_response(text, {"20260721-100000-abcd"})
    assert result["20260721-100000-abcd"] == ("short", 4)


def test_memory_parser_rejects_unbounded_body() -> None:
    payload = {"operations": [{
        "action": "create", "scope": "project", "category": "reference", "importance": 3,
        "title": "large", "summary": "large", "body": "x" * (64 * 1024 + 1),
    }]}
    with pytest.raises(MemoryFormatError):
        parse_memory_response(f"<memory_update>{json.dumps(payload)}</memory_update>")
