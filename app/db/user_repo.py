from __future__ import annotations

from datetime import datetime, date

from app.db.client import get_db


COLLECTION = "users"


def get_or_create_user(line_user_id: str, display_name: str = "") -> dict:
    db = get_db()
    user = db[COLLECTION].find_one({"_id": line_user_id})

    if user:
        user["id"] = user["_id"]
        return user

    today = date.today().isoformat()
    user_data = {
        "_id": line_user_id,
        "display_name": display_name,
        "balance": 0,
        "total_deposited": 0,
        "total_wagered": 0,
        "total_won": 0,
        "total_profit": 0,
        "deposit_today_total": 0,
        "deposit_today_date": today,
        "deposit_30d_total": 0,
        "bet_today_total": 0,
        "bet_today_date": today,
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    db[COLLECTION].insert_one(user_data)
    user_data["id"] = line_user_id
    return user_data


def get_user(line_user_id: str) -> dict | None:
    db = get_db()
    user = db[COLLECTION].find_one({"_id": line_user_id})
    if user:
        user["id"] = user["_id"]
    return user


def update_user(line_user_id: str, data: dict):
    db = get_db()
    data["updated_at"] = datetime.now()
    db[COLLECTION].update_one({"_id": line_user_id}, {"$set": data})


def get_top_users_by_profit(limit: int = 10) -> list[dict]:
    db = get_db()
    cursor = db[COLLECTION].find().sort("total_profit", -1).limit(limit)
    results = []
    for doc in cursor:
        doc["id"] = doc["_id"]
        results.append(doc)
    return results
