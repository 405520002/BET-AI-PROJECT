"""Whitelist of LINE user IDs allowed to use the bot.

Collection: `whitelist`
Document: { _id: <line_user_id>, display_name: str, added_at: datetime }

Empty collection = allow everyone (backward compatible).
"""
from __future__ import annotations

from datetime import datetime

from app.db.client import get_db


COLLECTION = "whitelist"


def is_whitelisted(line_user_id: str) -> bool:
    db = get_db()
    if db[COLLECTION].estimated_document_count() == 0:
        return True
    return db[COLLECTION].find_one({"_id": line_user_id}) is not None


def add(line_user_id: str, display_name: str = "") -> None:
    db = get_db()
    db[COLLECTION].update_one(
        {"_id": line_user_id},
        {
            "$set": {"display_name": display_name},
            "$setOnInsert": {"added_at": datetime.now()},
        },
        upsert=True,
    )


def remove(line_user_id: str) -> bool:
    db = get_db()
    return db[COLLECTION].delete_one({"_id": line_user_id}).deleted_count > 0


def list_all() -> list[dict]:
    db = get_db()
    return [
        {"id": d["_id"], **{k: v for k, v in d.items() if k != "_id"}}
        for d in db[COLLECTION].find()
    ]
