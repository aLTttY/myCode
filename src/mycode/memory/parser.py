from __future__ import annotations

import json
import re
from datetime import datetime

import yaml

from .models import MemoryDecision, MemoryNote, MemoryOperation


NOTE_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
MAX_TITLE_CHARS = 200
MAX_SUMMARY_CHARS = 1_000
MAX_BODY_CHARS = 64 * 1024
CATEGORIES = {"user_preference", "correction_feedback", "project_knowledge", "reference"}
SCOPES = {"user", "project"}


class MemoryFormatError(Exception):
    pass


def parse_memory_response(text: str, known_ids: dict[str, set[str]] | None = None) -> MemoryDecision:
    opening = "<memory_update>"
    closing = "</memory_update>"
    if text.count(opening) != 1 or text.count(closing) != 1:
        raise MemoryFormatError("记忆响应缺少唯一标记。")
    start = text.index(opening) + len(opening)
    end = text.index(closing)
    if start > end or text[: text.index(opening)].strip() or text[end + len(closing) :].strip():
        raise MemoryFormatError("记忆响应包含标记外内容。")
    try:
        raw = json.loads(text[start:end])
    except json.JSONDecodeError as exc:
        raise MemoryFormatError("记忆响应不是合法 JSON。") from exc
    if not isinstance(raw, dict) or set(raw) != {"operations"} or not isinstance(raw["operations"], list):
        raise MemoryFormatError("记忆响应顶层结构非法。")
    operations: list[MemoryOperation] = []
    for item in raw["operations"]:
        if not isinstance(item, dict) or not isinstance(item.get("action"), str):
            raise MemoryFormatError("记忆操作结构非法。")
        action = item["action"]
        if action == "ignore":
            if not set(item).issubset({"action", "reason"}):
                raise MemoryFormatError("ignore 操作字段非法。")
            operations.append(MemoryOperation(action="ignore", reason=str(item.get("reason", ""))))
            continue
        required = {"action", "scope", "category", "importance", "title", "summary", "body"}
        allowed = required | {"target_id"}
        if action not in {"create", "update"} or set(item) - allowed or not required.issubset(item):
            raise MemoryFormatError("记忆写入操作字段非法。")
        scope = item["scope"]
        category = item["category"]
        importance = item["importance"]
        if scope not in SCOPES or category not in CATEGORIES or isinstance(importance, bool) or not isinstance(importance, int) or not 1 <= importance <= 5:
            raise MemoryFormatError("记忆分类、作用域或重要度非法。")
        for field in ("title", "summary", "body"):
            if not isinstance(item[field], str) or not item[field].strip():
                raise MemoryFormatError(f"记忆字段 {field} 不能为空。")
        if len(item["title"]) > MAX_TITLE_CHARS or len(item["summary"]) > MAX_SUMMARY_CHARS or len(item["body"]) > MAX_BODY_CHARS:
            raise MemoryFormatError("记忆候选超过单项大小限制。")
        target_id = item.get("target_id", "")
        if action == "update":
            if not isinstance(target_id, str) or not NOTE_ID_RE.fullmatch(target_id):
                raise MemoryFormatError("update 目标 ID 非法。")
            if known_ids is not None and target_id not in known_ids.get(scope, set()):
                raise MemoryFormatError("update 目标不在对应作用域。")
        elif target_id:
            raise MemoryFormatError("create 不能指定目标 ID。")
        operations.append(
            MemoryOperation(
                action=action,
                scope=scope,
                category=category,
                importance=importance,
                title=item["title"].strip(),
                summary=" ".join(item["summary"].split()),
                body=item["body"].strip(),
                target_id=target_id,
            )
        )
    return MemoryDecision(tuple(operations))


def parse_index_response(text: str, expected_ids: set[str]) -> dict[str, tuple[str, int]]:
    opening = "<memory_index>"
    closing = "</memory_index>"
    if text.count(opening) != 1 or text.count(closing) != 1:
        raise MemoryFormatError("索引响应缺少唯一标记。")
    start = text.index(opening) + len(opening)
    end = text.index(closing)
    if text[: text.index(opening)].strip() or text[end + len(closing) :].strip():
        raise MemoryFormatError("索引响应包含标记外内容。")
    try:
        raw = json.loads(text[start:end])
    except json.JSONDecodeError as exc:
        raise MemoryFormatError("索引响应不是合法 JSON。") from exc
    if not isinstance(raw, dict) or set(raw) != {"entries"} or not isinstance(raw["entries"], list):
        raise MemoryFormatError("索引响应顶层结构非法。")
    result: dict[str, tuple[str, int]] = {}
    for item in raw["entries"]:
        if not isinstance(item, dict) or set(item) != {"id", "summary", "importance"}:
            raise MemoryFormatError("索引条目结构非法。")
        note_id, summary, importance = item["id"], item["summary"], item["importance"]
        if not isinstance(note_id, str) or note_id in result or note_id not in expected_ids:
            raise MemoryFormatError("索引响应包含未知或重复 ID。")
        if not isinstance(summary, str) or not summary.strip() or "\n" in summary:
            raise MemoryFormatError("索引摘要必须是非空单行文本。")
        if isinstance(importance, bool) or not isinstance(importance, int) or not 1 <= importance <= 5:
            raise MemoryFormatError("索引重要度非法。")
        result[note_id] = (" ".join(summary.split()), importance)
    if set(result) != expected_ids:
        raise MemoryFormatError("索引响应没有覆盖全部 ID。")
    return result


def render_note(note: MemoryNote) -> str:
    metadata = {
        "id": note.id,
        "category": note.category,
        "scope": note.scope,
        "importance": note.importance,
        "created_at": note.created_at.isoformat(),
        "updated_at": note.updated_at.isoformat(),
        "source_session": note.source_session,
    }
    frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{frontmatter}\n---\n# {note.title}\n\n{note.summary}\n\n{note.body.rstrip()}\n"


def parse_note(text: str) -> MemoryNote:
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise MemoryFormatError("笔记缺少 frontmatter。")
    end = text.index("\n---\n", 4)
    try:
        metadata = yaml.safe_load(text[4:end])
    except yaml.YAMLError as exc:
        raise MemoryFormatError("笔记 frontmatter 非法。") from exc
    required = {"id", "category", "scope", "importance", "created_at", "updated_at", "source_session"}
    if not isinstance(metadata, dict) or set(metadata) != required:
        raise MemoryFormatError("笔记 frontmatter 字段非法。")
    body_text = text[end + 5 :].strip()
    parts = body_text.split("\n\n", 2)
    if len(parts) < 3 or not parts[0].startswith("# "):
        raise MemoryFormatError("笔记正文结构非法。")
    note_id = metadata["id"]
    category = metadata["category"]
    scope = metadata["scope"]
    importance = metadata["importance"]
    if not isinstance(note_id, str) or not NOTE_ID_RE.fullmatch(note_id):
        raise MemoryFormatError("笔记 ID 非法。")
    if category not in CATEGORIES or scope not in SCOPES:
        raise MemoryFormatError("笔记分类或作用域非法。")
    if isinstance(importance, bool) or not isinstance(importance, int) or not 1 <= importance <= 5:
        raise MemoryFormatError("笔记重要度非法。")
    source_session = metadata["source_session"]
    if not isinstance(source_session, str) or not NOTE_ID_RE.fullmatch(source_session):
        raise MemoryFormatError("笔记来源会话 ID 非法。")
    try:
        created = datetime.fromisoformat(str(metadata["created_at"]))
        updated = datetime.fromisoformat(str(metadata["updated_at"]))
    except ValueError as exc:
        raise MemoryFormatError("笔记时间非法。") from exc
    if created.tzinfo is None or updated.tzinfo is None:
        raise MemoryFormatError("笔记时间必须带时区。")
    return MemoryNote(
        id=note_id,
        category=category,
        scope=scope,
        importance=importance,
        created_at=created,
        updated_at=updated,
        source_session=source_session,
        title=parts[0][2:].strip(),
        summary=" ".join(parts[1].split()),
        body=parts[2].strip(),
    )
