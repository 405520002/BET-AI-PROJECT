"""Game results for a given date.

Sources from today.line.me. The previous implementation went through
cpbl_schedule.scrape_schedule_for_date, which hits www.cpbl.com.tw/box/*
— that path is HiNet-CDN geo-blocked from non-TW datacenter ASNs and
returns 404 from the GCP us-west1 VM, so the 00:00 settlement job was
silently seeing zero finals every night and leaving every bet pending.
"""
from __future__ import annotations

import logging

from app.scraper.line_today_schedule import fetch_line_today_schedule

logger = logging.getLogger(__name__)


async def scrape_game_results(target_date: str) -> list[dict]:
    """Return finished + postponed games for `target_date` (YYYY-MM-DD).

    Output items: {game_sno, home_score, away_score, status, result_details}.
    """
    games = await fetch_line_today_schedule()

    results: list[dict] = []
    for g in games:
        if g.get("date") != target_date:
            continue
        status = g.get("status")
        if status == "final":
            results.append({
                "game_sno": g["game_sno"],
                "home_score": g.get("home_score", 0),
                "away_score": g.get("away_score", 0),
                "status": "final",
                "result_details": {},
            })
        elif status == "postponed":
            results.append({
                "game_sno": g["game_sno"],
                "home_score": 0,
                "away_score": 0,
                "status": "postponed",
                "result_details": {},
            })

    return results
