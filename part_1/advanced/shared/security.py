"""Small secret-safe rendering helpers for localhost teaching APIs."""

from __future__ import annotations

import os
import re
from typing import Any


_CREDENTIAL_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\b" + "tvly" + r"-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\be2b_[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)(https?://[^:/\s]+:)[^@/\s]+(@)"),
    re.compile(r"\b([A-Za-z][A-Za-z0-9_$#-]*/)[^@\s]+(@[^\s]+)"),
)


def redact_runtime_secrets(value: Any) -> str:
    """Return bounded diagnostic text with credential-shaped values removed."""

    rendered = str(value or "")
    for name, secret in os.environ.items():
        if not secret or len(secret) < 8:
            continue
        if any(marker in name.upper() for marker in ("KEY", "TOKEN", "PASSWORD", "PWD", "SECRET")):
            rendered = rendered.replace(secret, "<redacted>")
    for pattern in _CREDENTIAL_PATTERNS:
        if pattern.groups == 2:
            rendered = pattern.sub(r"\1<redacted>\2", rendered)
        else:
            rendered = pattern.sub("<redacted>", rendered)
    return rendered[:800]


def public_error(exc: BaseException) -> str:
    """Normalize an exception for a browser response without dropping its type."""

    return f"{type(exc).__name__}: {redact_runtime_secrets(exc)}"
