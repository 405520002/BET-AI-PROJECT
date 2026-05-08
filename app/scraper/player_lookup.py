"""Player lookup by Chinese name.

Public API:
    parse_query(q)                 -> (name_part, rest)
    find_player(name)              -> {"acnt", "name_zh", "name_en", "team"} | None
    find_player_async(name)        -> async, falls back to Wikipedia + caches the hit
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def parse_query(q: str) -> tuple[str, str]:
    """Split q on the first whitespace character.
    Returns (name_part, rest). If no whitespace, returns (q, "")."""
    parts = q.split(None, 1)
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[0], parts[1])


def _doc_to_legacy(doc: dict | None) -> dict | None:
    if not doc:
        return None
    return {
        "acnt": doc["acnt"],
        "name_zh": doc["_id"],
        "name_en": "",
        "team": doc.get("team", ""),
    }


def find_player(name_part: str) -> Optional[dict]:
    """Synchronous lookup against the DB roster (db.player_roster).
    Exact zh match first, then loose containment per find_fuzzy."""
    needle = (name_part or "").strip()
    if not needle:
        return None
    from app.db import roster_repo
    doc = roster_repo.get(needle)
    if doc is None:
        doc = roster_repo.find_fuzzy(needle)
    return _doc_to_legacy(doc)


async def find_player_async(name_part: str) -> Optional[dict]:
    """Lookup with on-demand Wikipedia fallback. Wraps find_player for the
    common path; on a miss, asks Wikipedia for the acnt, validates it by
    fetching the stats page and matching the title's leading zh name, then
    upserts into the roster as 'wiki_runtime' so the next query short-
    circuits."""
    p = find_player(name_part)
    if p is not None:
        return p

    needle = (name_part or "").strip()
    if not needle:
        return None

    from app.scraper.wiki_lookup import fetch_wiki_acnt
    acnt = await fetch_wiki_acnt(needle)
    if not acnt:
        return None

    # Validate. fetch_player_advanced_stats already has its own LRU cache, so
    # the caller's subsequent fetch reuses this response.
    from app.scraper.cpbl_player_stats import fetch_player_advanced_stats
    stats = await fetch_player_advanced_stats(acnt)
    if not stats:
        logger.info(
            "wiki fallback: %s -> acnt %s but stats fetch returned None", needle, acnt
        )
        return None
    if stats.get("name_zh") != needle:
        logger.warning(
            "wiki fallback: %s mapped to acnt %s but stats title says %s — rejecting",
            needle,
            acnt,
            stats.get("name_zh"),
        )
        return None

    from app.db import roster_repo
    roster_repo.upsert(
        name=needle,
        acnt=acnt,
        team=stats.get("team", ""),
        source="wiki_runtime",
    )
    return {
        "acnt": acnt,
        "name_zh": stats.get("name_zh", needle),
        "name_en": "",
        "team": stats.get("team", ""),
    }


# --- Legacy English→Chinese translation helpers (still used by cpbl_schedule) ---
# These read the static JSON file; the daily Wiki refresh and DB roster don't
# touch the EN side. Schedule/standings English names are uncommon now (zh
# scrapers are primary) but we keep them working for old DB rows.

import json as _json
import os as _os

_DATA_PATH = _os.path.join(_os.path.dirname(__file__), "player_names.json")
_EN_TO_ZH: dict[str, str] | None = None
_ACNT_TO_ZH: dict[str, str] | None = None


def _load_en_maps() -> None:
    global _EN_TO_ZH, _ACNT_TO_ZH
    _EN_TO_ZH = {}
    _ACNT_TO_ZH = {}
    try:
        with open(_DATA_PATH, encoding="utf-8") as f:
            data = _json.load(f)
        for k, v in data.get("players", {}).items():
            zh = (v.get("zh") or "").strip()
            acnt = (v.get("acnt") or "").strip()
            if zh:
                if k:
                    _EN_TO_ZH[k] = zh
                if acnt:
                    _ACNT_TO_ZH[acnt] = zh
    except Exception as e:
        logger.warning("player_lookup: en map load failed: %s", e)


def to_chinese(en_or_zh: str) -> str:
    if _EN_TO_ZH is None:
        _load_en_maps()
    return _EN_TO_ZH.get(en_or_zh, en_or_zh) if _EN_TO_ZH else en_or_zh


def to_chinese_by_acnt(acnt: str) -> str:
    if _ACNT_TO_ZH is None:
        _load_en_maps()
    return _ACNT_TO_ZH.get(acnt, "") if _ACNT_TO_ZH else ""
