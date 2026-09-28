"""User rules shared by reset and signup: handles and emails (§4, §6, D8)."""
from __future__ import annotations

import re

HANDLE_RE = re.compile(r"[a-z0-9_]{1,20}")
_NOT_HANDLE_CHAR = re.compile(r"[^a-z0-9_]")
HANDLE_MAX = 20
PASSWORD_MIN = 8


def email_key(email: str) -> str:
    """Emails are unique and looked up case-insensitively (D8)."""
    return email.lower()


def is_valid_email(email: str) -> bool:
    """`local@domain`: exactly one `@`, both parts non-empty, no whitespace (D8)."""
    local, at, domain = email.partition("@")
    return (bool(at) and bool(local) and bool(domain) and "@" not in domain
            and not any(c.isspace() for c in email))


def derive_handle(email: str) -> str:
    """The signup handle (S1-MOD-4): the local part, lowercased, every character outside
    [a-z0-9_] replaced with `_`, truncated to 20 characters."""
    local = email.partition("@")[0]
    return _NOT_HANDLE_CHAR.sub("_", local.lower())[:HANDLE_MAX]
