from __future__ import annotations

from datetime import datetime, timedelta

from app.db.client import get_db


COLLECTION = "transactions"


def create_transaction(tx_data: dict) -> str:
    db = get_db()
    tx_data["created_at"] = datetime.now()
    result = db[COLLECTION].insert_one(tx_data)
    return str(result.inserted_id)


def get_user_deposits_since(user_id: str, since: datetime) -> list[dict]:
    db = get_db()
    cursor = db[COLLECTION].find({
        "user_id": user_id,
        "type": "deposit",
        "created_at": {"$gte": since},
    })
    results = []
    for doc in cursor:
        doc["id"] = str(doc["_id"])
        results.append(doc)
    return results


def sum_deposits_last_30_days(user_id: str) -> int:
    since = datetime.now() - timedelta(days=30)
    deposits = get_user_deposits_since(user_id, since)
    return sum(d["amount"] for d in deposits)


def get_user_transactions(user_id: str, limit: int = 20) -> list[dict]:
    db = get_db()
    cursor = (
        db[COLLECTION]
        .find({"user_id": user_id})
        .sort("created_at", -1)
        .limit(limit)
    )
    results = []
    for doc in cursor:
        doc["id"] = str(doc["_id"])
        results.append(doc)
    return results
