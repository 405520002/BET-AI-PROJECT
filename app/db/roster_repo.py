"""Player roster store backed by MongoDB.

Schema (collection: player_roster):
    _id:        zh_name (Chinese name)
    acnt:       10-digit CPBL player account
    team:       Chinese team name (may be empty for runtime-cached entries)
    source:     "seed" | "wiki" | "shortcut" | "wiki_runtime"
    updated_at: datetime

The JSON file at app/scraper/player_names.json acts as a one-time seed when
the collection is first empty. After that all writes go to the DB so the
daily Wiki refresh and the iPhone-Shortcut /ingest/roster don't have to
fight a tracked file.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Iterable

from app.db.client import get_db

logger = logging.getLogger(__name__)

_SEED_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "scraper", "player_names.json"
)

# Higher = more authoritative. Lower-priority writes don't clobber higher.
_PRIORITY = {"wiki_runtime": 0, "wiki": 1, "seed": 2, "shortcut": 3}


def _coll():
    return get_db()["player_roster"]


def get(name: str) -> dict | None:
    """Exact lookup by zh name."""
    return _coll().find_one({"_id": name.strip()})


def find_fuzzy(name: str) -> dict | None:
    """Loose lookup mirroring the legacy player_lookup matching priority:
       (b) DB _id contains needle  AND  len(needle) >= 2
       (c) needle contains DB _id  AND  len(_id) >= 2
    Prefers non-二軍 entries on tie. Used as a fallback after exact `get`.
    """
    needle = name.strip()
    if not needle or len(needle) < 2:
        return None
    coll = _coll()

    rx = re.escape(needle)
    candidates = list(coll.find({"_id": {"$regex": rx}}, limit=20))
    if not candidates:
        candidates = [
            d for d in coll.find({}, projection={"_id": 1, "acnt": 1, "team": 1})
            if len(d["_id"]) >= 2 and d["_id"] in needle
        ]
    if not candidates:
        return None
    primary = [d for d in candidates if "二軍" not in (d.get("team") or "")]
    return (primary or candidates)[0]


def upsert(name: str, acnt: str, team: str, source: str) -> None:
    name = name.strip()
    if not name or not acnt:
        return
    existing = _coll().find_one({"_id": name})
    incoming = _PRIORITY.get(source, 0)
    if existing and _PRIORITY.get(existing.get("source", ""), 0) > incoming:
        return  # higher-trust value already there; don't downgrade
    _coll().update_one(
        {"_id": name},
        {
            "$set": {
                "acnt": acnt,
                "team": team or "",
                "source": source,
                "updated_at": datetime.utcnow(),
            }
        },
        upsert=True,
    )


def bulk_upsert(records: Iterable[dict], team: str, source: str) -> int:
    """Upsert a batch of {name, acnt, team?} records. Returns rows written.
    Existing higher-trust sources are preserved (see _PRIORITY)."""
    coll = _coll()
    now = datetime.utcnow()
    incoming_priority = _PRIORITY.get(source, 0)
    n = 0
    for rec in records:
        name = (rec.get("name") or "").strip()
        acnt = (rec.get("acnt") or "").strip()
        rec_team = (rec.get("team") or team or "").strip()
        if not name or not acnt:
            continue
        existing = coll.find_one({"_id": name}, projection={"source": 1})
        if existing and _PRIORITY.get(existing.get("source", ""), 0) > incoming_priority:
            continue
        coll.update_one(
            {"_id": name},
            {
                "$set": {
                    "acnt": acnt,
                    "team": rec_team,
                    "source": source,
                    "updated_at": now,
                }
            },
            upsert=True,
        )
        n += 1
    return n


def count() -> int:
    return _coll().count_documents({})


def seed_from_json_if_empty() -> int:
    """One-time bootstrap. Returns rows seeded (0 if collection was non-empty
    or file missing)."""
    try:
        if count() > 0:
            return 0
    except Exception as e:
        logger.warning("roster_repo: count failed: %s", e)
        return 0
    if not os.path.exists(_SEED_PATH):
        logger.warning("roster_repo: seed file missing at %s", _SEED_PATH)
        return 0
    try:
        with open(_SEED_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning("roster_repo: seed parse failed: %s", e)
        return 0
    players = data.get("players", {})
    records: list[dict] = []
    for v in players.values():
        zh = (v.get("zh") or "").strip()
        acnt = (v.get("acnt") or "").strip()
        team = (v.get("team") or "").strip()
        if not zh or not acnt:
            continue
        records.append({"name": zh, "acnt": acnt, "team": team})
    n = bulk_upsert(records, team="", source="seed")
    logger.info("roster_repo: seeded %d players from %s", n, _SEED_PATH)
    return n
