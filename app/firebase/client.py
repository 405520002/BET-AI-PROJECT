from __future__ import annotations

from pymongo import MongoClient
from pymongo.database import Database

from app.config import settings

_client: MongoClient = None
_db: Database = None


def get_db() -> Database:
    global _client, _db
    if _db is None:
        _client = MongoClient(settings.mongodb_uri)
        _db = _client[settings.mongodb_db]
    return _db
