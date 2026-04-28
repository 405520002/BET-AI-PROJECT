"""Player name EN↔ZH lookup. Source: app/scraper/player_names.json
Build/refresh via scripts/scrape_player_names.py (run from a TW IP).
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

_DATA_PATH = os.path.join(os.path.dirname(__file__), "player_names.json")
_CACHE: dict[str, str] | None = None
_ACNT_CACHE: dict[str, str] | None = None


def _load() -> dict[str, str]:
    global _CACHE, _ACNT_CACHE
    if _CACHE is not None:
        return _CACHE
    try:
        with open(_DATA_PATH, encoding="utf-8") as f:
            data = json.load(f)
        players = data.get("players", {})
        _CACHE = {k.strip().upper(): v["zh"] for k, v in players.items()}
        _ACNT_CACHE = {
            v["acnt"]: v["zh"] for v in players.values()
            if v.get("acnt") and v.get("zh")
        }
        logger.info(
            f"Loaded {len(_CACHE)} name + {len(_ACNT_CACHE)} acnt CPBL player mappings"
        )
    except FileNotFoundError:
        logger.warning(f"player_names.json not found at {_DATA_PATH}")
        _CACHE = {}
        _ACNT_CACHE = {}
    except Exception as e:
        logger.warning(f"Failed to load player_names.json: {e}")
        _CACHE = {}
        _ACNT_CACHE = {}
    return _CACHE


def to_chinese(en_name: str) -> str:
    """Return official CPBL Chinese name if registered, else the original."""
    if not en_name:
        return en_name
    # Preserve existing Chinese
    if any("一" <= c <= "鿿" for c in en_name):
        return en_name
    m = _load()
    return m.get(en_name.strip().upper(), en_name)


def to_chinese_by_acnt(acnt: str) -> str:
    """Look up the official Chinese name by CPBL player acnt; '' if unknown."""
    if not acnt:
        return ""
    _load()
    return (_ACNT_CACHE or {}).get(acnt.strip(), "")
