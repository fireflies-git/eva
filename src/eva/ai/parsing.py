from __future__ import annotations


def parse_strict_yes_no(response: str) -> bool | None:
    normalized = response.strip().upper()
    if normalized == "YES":
        return True
    if normalized == "NO":
        return False
    return None
