"""Shared validation for portable Agent Skill directory names."""

from __future__ import annotations

import re
from typing import Any


MAX_SKILL_NAME_LENGTH = 64
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


def validate_skill_name(value: Any, label: str = "Skill name") -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    if len(value) > MAX_SKILL_NAME_LENGTH:
        raise ValueError(
            f"{label} exceeds {MAX_SKILL_NAME_LENGTH} characters: {value!r}"
        )
    if not NAME_RE.fullmatch(value):
        raise ValueError(f"{label} must be lowercase hyphen-case: {value!r}")
    if value in WINDOWS_RESERVED_NAMES:
        raise ValueError(f"{label} is a reserved Windows device name: {value!r}")
    return value
