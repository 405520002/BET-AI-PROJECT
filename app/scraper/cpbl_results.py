"""Scrape CPBL game results - reuses schedule API since it includes scores."""
from __future__ import annotations

import logging
from datetime import date

from app.scraper.cpbl_schedule import scrape_schedule_for_date

logger = logging.getLogger(__name__)


async def scrape_game_results(target_date: str) -> list[dict]:
    """Get game results for a given date.
    Returns list of dicts with: game_sno, home_score, away_score, status.
    """
    parts = target_date.split("-")
    year, month, day = int(parts[0]), int(parts[1]), int(parts[2])

    games = await scrape_schedule_for_date(year, month, day)

    results = []
    for g in games:
        if g["status"] == "final":
            results.append({
                "game_sno": g["game_sno"],
                "home_score": g.get("home_score", 0),
                "away_score": g.get("away_score", 0),
                "status": "final",
                "result_details": {},
            })
        elif g["status"] == "postponed":
            results.append({
                "game_sno": g["game_sno"],
                "home_score": 0,
                "away_score": 0,
                "status": "postponed",
                "result_details": {},
            })

    return results
