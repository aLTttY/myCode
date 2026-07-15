from __future__ import annotations

import re


_COMMAND_BOUNDARY = r"(?:^|[;&|]\s*)"
_PREFIX = r"(?:sudo\s+)?"
_EXECUTABLE_PATH = r"(?:[^\s;&|]*/)?"
_CATASTROPHIC_REMOVE_TARGET = (
    r"(?:/(?:\*|\.\*)?|~/?|\$HOME(?:/\*)?|/root/?|/(?:home|Users)/(?:[^/\s;&|]+|\*)/?)"
)

BLACKLIST_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in (
        rf"{_COMMAND_BOUNDARY}{_PREFIX}{_EXECUTABLE_PATH}rm\s+(?=[^;&|\n]*-[A-Za-z]*r)(?=[^;&|\n]*-[A-Za-z]*f)[^;&|\n]*(?:\s|^){_CATASTROPHIC_REMOVE_TARGET}(?:\s|$|[;&|])",
        rf"{_COMMAND_BOUNDARY}{_PREFIX}{_EXECUTABLE_PATH}find\s+(?:/|~|\$HOME)\s+[^;&|\n]*-delete\b",
        rf"{_COMMAND_BOUNDARY}{_PREFIX}{_EXECUTABLE_PATH}(?:mkfs(?:\.[A-Za-z0-9_+-]+)?|fdisk|parted)\b[^;&|\n]*(?:/dev/)",
        rf"{_COMMAND_BOUNDARY}{_PREFIX}{_EXECUTABLE_PATH}diskutil\s+(?:eraseDisk|eraseVolume|partitionDisk)\b",
        rf"{_COMMAND_BOUNDARY}{_PREFIX}{_EXECUTABLE_PATH}dd\b[^;&|\n]*\bof\s*=\s*/dev/(?:disk|rdisk|sd|nvme)",
        rf"{_COMMAND_BOUNDARY}{_PREFIX}{_EXECUTABLE_PATH}(?:chmod|chown)\b(?=[^;&|\n]*\s-(?:[A-Za-z]*R|R[A-Za-z]*)(?:\s|$))[^;&|\n]*\s/(?:etc|usr|bin|sbin|System|Library)?(?:\s|$|[;&|])",
        rf"{_COMMAND_BOUNDARY}{_PREFIX}{_EXECUTABLE_PATH}(?:shutdown|reboot|halt|poweroff)\b",
        r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;?\s*:",
    )
)


def normalize_command(command: str) -> str:
    return " ".join(command.split())


def is_blacklisted(command: str) -> bool:
    candidates = (command, normalize_command(command))
    return any(pattern.search(candidate) for pattern in BLACKLIST_PATTERNS for candidate in candidates)
