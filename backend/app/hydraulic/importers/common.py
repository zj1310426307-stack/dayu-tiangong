"""Shared text decoding, token parsing, and identity helpers for importers."""

from __future__ import annotations

import csv
import re
from io import StringIO
from pathlib import Path


def decode_text(content: bytes) -> str:
    """Decode common MIKE/Windows text encodings without silently dropping bytes."""

    for encoding in ("utf-8-sig", "utf-8", "gb18030", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("text file encoding is not UTF-8, GB18030, or Windows-1252")


def clean_scalar(value: str) -> str:
    """Remove comments, trailing delimiters, and balanced string quotes."""

    cleaned = value.split("//", 1)[0].strip().rstrip(",;").strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        return cleaned[1:-1].strip()
    return cleaned


def key_value(block: str, *keys: str, default: str | None = None) -> str | None:
    """Read the first case-insensitive PFS-style key from one section block."""

    for key in keys:
        match = re.search(rf"(?im)^\s*{re.escape(key)}\s*=\s*(.+?)\s*$", block)
        if match:
            return clean_scalar(match.group(1))
    return default


def repeated_values(block: str, *keys: str) -> list[list[str]]:
    """Parse repeated comma-separated PFS values while respecting quoted text."""

    pattern = "|".join(re.escape(key) for key in keys)
    values: list[list[str]] = []
    for match in re.finditer(rf"(?im)^\s*(?:{pattern})\s*=\s*(.+?)\s*$", block):
        line = match.group(1).split("//", 1)[0].strip().rstrip(";")
        row = next(csv.reader(StringIO(line), skipinitialspace=True))
        values.append([clean_scalar(item) for item in row])
    return values


def safe_code(value: str, fallback: str) -> str:
    """Normalize an external identity into a bounded stable business code."""

    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-._")
    return (normalized or fallback)[:64]


def file_identity(filename: str, prefix: str) -> tuple[str, str]:
    """Build deterministic network code and display name from a safe file stem."""

    stem = Path(filename).stem.strip() or prefix
    return safe_code(stem, prefix).upper(), stem[:128]
