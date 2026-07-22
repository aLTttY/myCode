from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from mycode.types import Message, ToolCall

from .journal import SESSION_ID_RE
from .models import SessionLoadResult, SessionSummary


class SessionLoader:
    def load(self, path: Path, now: datetime | None = None) -> SessionLoadResult:
        records: list[tuple[datetime, Message]] = []
        bad = 0
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            lines = []
            bad = 1
        for line in lines:
            try:
                raw = json.loads(line)
                timestamp, message = self._parse_record(raw)
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                bad += 1
                continue
            records.append((timestamp, message))

        messages = tuple(message for _, message in records)
        prefix = self._valid_prefix(messages)
        truncated = len(messages) - len(prefix)
        summary = self._summary(path, records, bad)
        current = now or datetime.now().astimezone()
        gap = current - summary.last_active_at if summary is not None else None
        return SessionLoadResult(
            summary=summary,
            messages=prefix,
            bad_line_count=bad,
            truncated_message_count=truncated,
            gap=gap,
            needs_time_gap_reminder=bool(gap is not None and gap > timedelta(hours=24)),
        )

    @staticmethod
    def _parse_record(raw: object) -> tuple[datetime, Message]:
        if not isinstance(raw, dict) or set(raw) != {"version", "timestamp", "type", "message"}:
            raise ValueError
        if raw["version"] != 1 or raw["type"] != "message" or not isinstance(raw["timestamp"], str):
            raise ValueError
        timestamp = datetime.fromisoformat(raw["timestamp"])
        if timestamp.tzinfo is None:
            raise ValueError
        data = raw["message"]
        if not isinstance(data, dict) or set(data) != {"role", "content", "tool_calls", "tool_call_id"}:
            raise ValueError
        role = data["role"]
        if role not in {"user", "assistant", "tool"} or not isinstance(data["content"], str):
            raise ValueError
        if not isinstance(data["tool_call_id"], str) or not isinstance(data["tool_calls"], list):
            raise ValueError
        calls: list[ToolCall] = []
        for item in data["tool_calls"]:
            if not isinstance(item, dict) or set(item) != {"id", "name", "arguments"}:
                raise ValueError
            if not isinstance(item["id"], str) or not item["id"] or not isinstance(item["name"], str):
                raise ValueError
            if not isinstance(item["arguments"], dict):
                raise ValueError
            calls.append(ToolCall(id=item["id"], name=item["name"], arguments=item["arguments"]))
        if role != "assistant" and calls:
            raise ValueError
        if role == "tool" and not data["tool_call_id"]:
            raise ValueError
        if role != "tool" and data["tool_call_id"]:
            raise ValueError
        return timestamp, Message(role=role, content=data["content"], tool_calls=tuple(calls), tool_call_id=data["tool_call_id"])

    @staticmethod
    def _valid_prefix(messages: tuple[Message, ...]) -> tuple[Message, ...]:
        index = 0
        while index < len(messages):
            message = messages[index]
            if message.role == "tool":
                return messages[:index]
            if message.role != "assistant" or not message.tool_calls:
                index += 1
                continue
            start = index
            expected = {call.id for call in message.tool_calls}
            if len(expected) != len(message.tool_calls):
                return messages[:start]
            seen: set[str] = set()
            index += 1
            while index < len(messages) and messages[index].role == "tool":
                call_id = messages[index].tool_call_id
                if call_id not in expected or call_id in seen:
                    return messages[:start]
                seen.add(call_id)
                index += 1
            if seen != expected:
                return messages[:start]
        return messages

    @staticmethod
    def _summary(path: Path, records: list[tuple[datetime, Message]], bad: int) -> SessionSummary | None:
        session_id = path.stem
        if not SESSION_ID_RE.fullmatch(session_id) or not records:
            return None
        users = [message.content for _, message in records if message.role == "user"]
        if not users:
            return None
        title = " ".join(users[0].split())[:80]
        times = [timestamp for timestamp, _ in records]
        return SessionSummary(
            session_id=session_id,
            path=path,
            title=title,
            message_count=len(records),
            created_at=min(times),
            last_active_at=max(times),
            bad_line_count=bad,
        )
