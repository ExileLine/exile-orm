"""SQL helper utilities."""

from __future__ import annotations


def quote_identifier(name: str) -> str:
    escaped = name.replace('"', '""')
    return f'"{escaped}"'

