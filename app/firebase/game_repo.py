from __future__ import annotations

from datetime import datetime

from app.firebase.client import get_db


COLLECTION = "games"


def upsert_game(game_id: str, data: dict):
    db = get_db()
    data["_id"] = game_id
    data["updated_at"] = datetime.now()
    db[COLLECTION].update_one({"_id": game_id}, {"$set": data}, upsert=True)


def get_game(game_id: str) -> dict | None:
    db = get_db()
    doc = db[COLLECTION].find_one({"_id": game_id})
    if doc:
        doc["id"] = doc["_id"]
    return doc


def get_games_by_date(date_str: str) -> list[dict]:
    db = get_db()
    cursor = db[COLLECTION].find({"date": date_str})
    results = []
    for doc in cursor:
        doc["id"] = doc["_id"]
        results.append(doc)
    return results


def update_game_status(game_id: str, status: str, extra: dict | None = None):
    db = get_db()
    data = {"status": status, "updated_at": datetime.now()}
    if extra:
        data.update(extra)
    db[COLLECTION].update_one({"_id": game_id}, {"$set": data})


def update_game_result(game_id: str, home_score: int, away_score: int, result_details: dict | None = None):
    db = get_db()
    winner = "home" if home_score > away_score else "away"
    data = {
        "home_score": home_score,
        "away_score": away_score,
        "winner": winner,
        "status": "final",
        "settled_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    if result_details:
        data["result_details"] = result_details
    db[COLLECTION].update_one({"_id": game_id}, {"$set": data})
