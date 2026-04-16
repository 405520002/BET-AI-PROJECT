from __future__ import annotations

from datetime import datetime
from bson import ObjectId

from app.firebase.client import get_db


COLLECTION = "bets"


def create_bet(bet_data: dict) -> str:
    db = get_db()
    bet_data["created_at"] = datetime.now()
    bet_data["updated_at"] = datetime.now()
    result = db[COLLECTION].insert_one(bet_data)
    return str(result.inserted_id)


def get_bet(bet_id: str) -> dict | None:
    db = get_db()
    doc = db[COLLECTION].find_one({"_id": ObjectId(bet_id)})
    if doc:
        doc["id"] = str(doc["_id"])
    return doc


def get_bets_by_game(game_id: str, status: str | None = None) -> list[dict]:
    db = get_db()
    query = {"game_id": game_id}
    if status:
        query["status"] = status
    cursor = db[COLLECTION].find(query)
    results = []
    for doc in cursor:
        doc["id"] = str(doc["_id"])
        results.append(doc)
    return results


def get_user_bets(user_id: str, limit: int = 10) -> list[dict]:
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


def get_user_bets_by_date(user_id: str, date_str: str) -> list[dict]:
    db = get_db()
    cursor = db[COLLECTION].find({"user_id": user_id, "game_date": date_str})
    results = []
    for doc in cursor:
        doc["id"] = str(doc["_id"])
        results.append(doc)
    return results


def update_bet(bet_id: str, data: dict):
    db = get_db()
    data["updated_at"] = datetime.now()
    db[COLLECTION].update_one({"_id": ObjectId(bet_id)}, {"$set": data})
