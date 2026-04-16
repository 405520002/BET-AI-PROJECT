"""Scrape CPBL daily schedule from cpbl.com.tw API."""
from __future__ import annotations

import json
import logging
import re
from datetime import date

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://www.cpbl.com.tw"
SCHEDULE_PAGE = f"{BASE_URL}/schedule"
SCHEDULE_API = f"{BASE_URL}/schedule/getgamedatas"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Accept-Language": "zh-TW,zh;q=0.9",
    "Referer": f"{BASE_URL}/schedule",
}

TEAM_CODE_MAP = {
    "ACN011": {"code": "ACN", "name": "中信兄弟"},
    "ADD011": {"code": "ADD", "name": "統一7-ELEVEn獅"},
    "AJL011": {"code": "AJL", "name": "樂天桃猿"},
    "AEO011": {"code": "AEO", "name": "富邦悍將"},
    "AAA011": {"code": "AAA", "name": "味全龍"},
    "AKP011": {"code": "AKP", "name": "台鋼雄鷹"},
}


async def _get_verification_token() -> str:
    """Get RequestVerificationToken from schedule page."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(SCHEDULE_PAGE, headers=HEADERS, follow_redirects=True)
        r.raise_for_status()
        match = re.search(r"RequestVerificationToken.*?'([^']+)'", r.text)
        return match.group(1) if match else ""


async def scrape_today_schedule() -> list[dict]:
    """Scrape today's CPBL schedule via API.
    Returns list of game dicts.
    """
    today = date.today()
    return await scrape_schedule_for_date(today.year, today.month, today.day)


async def scrape_schedule_for_date(year: int, month: int, day: int | None = None) -> list[dict]:
    """Scrape CPBL schedule for a given year/month, optionally filter by day."""
    try:
        token = await _get_verification_token()

        api_headers = {
            **HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
            "RequestVerificationToken": token,
            "X-Requested-With": "XMLHttpRequest",
        }

        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                SCHEDULE_API,
                data={"kindCode": "A", "year": str(year), "month": str(month)},
                headers=api_headers,
                follow_redirects=True,
            )
            r.raise_for_status()

        data = r.json()
        if not data.get("Success"):
            logger.error(f"CPBL API returned error: {data}")
            return []

        game_list = json.loads(data["GameDatas"])
        return _parse_games(game_list, year, month, day)

    except Exception as e:
        logger.error(f"Failed to scrape CPBL schedule: {e}")
        return []


def _parse_games(game_list: list[dict], year: int, month: int, day: int | None = None) -> list[dict]:
    """Parse CPBL API game data into our format."""
    games = []
    target_date = f"{year}-{month:02d}-{day:02d}" if day else None

    for g in game_list:
        game_date_raw = g.get("GameDate", "")  # "2026-04-16T00:00:00"
        game_date = game_date_raw[:10]  # "2026-04-16"

        if target_date and game_date != target_date:
            continue

        game_sno = g.get("GameSno", 0)
        is_postponed = g.get("IsGameStop", "0") == "1"
        present_status = g.get("PresentStatus", 0)
        # PresentStatus: 0=未開始, 1=已結束, 2=進行中

        # Team info
        home_code_raw = g.get("HomeTeamCode", "")
        away_code_raw = g.get("VisitingTeamCode", "")
        home_info = TEAM_CODE_MAP.get(home_code_raw, {"code": home_code_raw, "name": g.get("HomeTeamName", "")})
        away_info = TEAM_CODE_MAP.get(away_code_raw, {"code": away_code_raw, "name": g.get("VisitingTeamName", "")})

        # Status - PresentStatus=1 means "exists", not "completed"
        # Determine actual status from scores and game time
        home_score = g.get("HomeScore", 0) or 0
        away_score = g.get("VisitingScore", 0) or 0
        has_scores = (home_score > 0 or away_score > 0)
        game_end_time = g.get("GameDateTimeE", "")  # empty if not played yet

        if is_postponed:
            status = "postponed"
        elif has_scores and game_end_time:
            status = "final"
        elif not game_end_time and not has_scores:
            status = "scheduled"
        else:
            status = "scheduled"

        # Game time
        game_time_raw = g.get("GameDateTimeS", "")  # "2026-04-16T18:35:00"
        game_time = game_time_raw[11:16] if len(game_time_raw) > 15 else "18:35"

        game = {
            "id": f"{game_date.replace('-', '')}_{game_sno}",
            "date": game_date,
            "game_sno": game_sno,
            "home_team": home_info["code"],
            "home_team_name": g.get("HomeTeamName", home_info["name"]),
            "away_team": away_info["code"],
            "away_team_name": g.get("VisitingTeamName", away_info["name"]),
            "venue": g.get("FieldAbbe", ""),
            "game_time": game_time,
            "home_pitcher": g.get("HomePitcherName", "TBD"),
            "away_pitcher": g.get("VisitingPitcherName", "TBD"),
            "status": status,
        }

        # If game is finished, include scores
        if status == "final":
            game["home_score"] = g.get("HomeScore", 0)
            game["away_score"] = g.get("VisitingScore", 0)
            game["winner"] = "home" if game["home_score"] > game["away_score"] else "away"

        games.append(game)

    games.sort(key=lambda x: x["game_sno"])
    return games
