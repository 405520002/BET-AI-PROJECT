"""Player lookup by Chinese name.

Public API:
    parse_query(q)    -> (name_part, rest)
    find_player(name) -> {"acnt", "name_zh", "name_en", "team"} | None
"""
from __future__ import annotations

import json
import os
from typing import Optional

_DATA_PATH = os.path.join(os.path.dirname(__file__), "player_names.json")

# Module-level constant: built once at import time.
# List of dicts with keys: acnt, name_zh, name_en, team
_ROSTER: list[dict] | None = None


def _get_roster() -> list[dict]:
    global _ROSTER
    if _ROSTER is not None:
        return _ROSTER
    try:
        with open(_DATA_PATH, encoding="utf-8") as f:
            data = json.load(f)
        players = data.get("players", {})
        _ROSTER = [
            {
                "acnt": v["acnt"],
                "name_zh": v.get("zh", "").strip(),
                "name_en": k,
                "team": v.get("team", ""),
            }
            for k, v in players.items()
            if v.get("acnt") and v.get("zh")
        ]
    except Exception:
        _ROSTER = []
    return _ROSTER


def parse_query(q: str) -> tuple[str, str]:
    """Split q on the first whitespace character.

    Returns (name_part, rest).  If there is no whitespace, returns (q, "").
    """
    parts = q.split(None, 1)
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[0], parts[1])


def find_player(name_part: str) -> Optional[dict]:
    """Look up a CPBL player by Chinese name (name-portion only).

    Matching priority (first that yields at least one candidate wins):
      (a) exact zh == name_part
      (b) zh contains name_part  AND  len(name_part) >= 2
      (c) name_part contains zh   AND  len(zh) >= 2

    On multiple matches, prefer entries whose team does NOT contain "二軍".
    Returns {"acnt", "name_zh", "name_en", "team"} or None.
    """
    roster = _get_roster()
    needle = name_part.strip()
    if not needle:
        return None

    candidates: list[dict] = []

    # (a) exact match
    exact = [p for p in roster if p["name_zh"] == needle]
    if exact:
        candidates = exact
    else:
        # (b) zh contains name_part
        if len(needle) >= 2:
            contains = [p for p in roster if needle in p["name_zh"]]
            if contains:
                candidates = contains

        # (c) name_part contains zh
        if not candidates:
            sub = [p for p in roster if len(p["name_zh"]) >= 2 and p["name_zh"] in needle]
            if sub:
                candidates = sub

    if not candidates:
        return None

    # Prefer non-二軍 entries
    primary = [p for p in candidates if "二軍" not in p["team"]]
    return (primary or candidates)[0]
