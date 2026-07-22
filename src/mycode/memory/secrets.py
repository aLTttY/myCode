from __future__ import annotations

import re


PLACEHOLDERS = re.compile(r"^(?:\$\{[^}]+\}|<[^>]+>|your[-_][a-z0-9_-]+|\*+|x{6,})$", re.IGNORECASE)
PATTERNS = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE)),
    ("token_prefix", re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{12,}|AKIA[A-Z0-9]{12,})\b")),
    (
        "secret_assignment",
        re.compile(r"(?im)\b(?:api[_-]?key|token|password|passwd|secret|private[_-]?key)\b\s*[:=]\s*['\"]?([^\s'\"]{6,})"),
    ),
)


def find_secret(text: str) -> str | None:
    for code, pattern in PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        if code == "secret_assignment" and PLACEHOLDERS.fullmatch(match.group(1)):
            continue
        return code
    return None
