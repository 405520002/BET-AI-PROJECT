"""Scrape CPBL daily schedule from cpbl.com.tw API."""
from __future__ import annotations

import json
import logging
import re
from datetime import date

logger = logging.getLogger(__name__)

from app.scraper.http_client import fetch_api

BASE_URL = "https://en.cpbl.com.tw"

TEAM_CODE_MAP = {
    "ACN011": {"code": "ACN", "name": "中信兄弟"},
    "ADD011": {"code": "ADD", "name": "統一7-ELEVEn獅"},
    "AJL011": {"code": "AJL", "name": "樂天桃猿"},
    "AEO011": {"code": "AEO", "name": "富邦悍將"},
    "AAA011": {"code": "AAA", "name": "味全龍"},
    "AKP011": {"code": "AKP", "name": "台鋼雄鷹"},
}

# English name → Chinese name (for en.cpbl.com.tw)
EN_TO_ZH = {
    "Brothers": "中信兄弟",
    "CTBC Brothers": "中信兄弟",
    "U-Lions": "統一7-ELEVEn獅",
    "Uni-Lions": "統一7-ELEVEn獅",
    "Monkeys": "樂天桃猿",
    "Rakuten Monkeys": "樂天桃猿",
    "Guardians": "富邦悍將",
    "Fubon Guardians": "富邦悍將",
    "DRAGONS": "味全龍",
    "Wei Chuan Dragons": "味全龍",
    "Dragons": "味全龍",
    "TSG Hawks": "台鋼雄鷹",
    "Hawks": "台鋼雄鷹",
}


# FieldAbbe → 中文. 2026 球季實際用到的 11 個 code (從 schedule API 全年掃出) + 歷史遺留.
VENUE_MAP = {
    # 2026 主要使用 (按出現頻率)
    "TPD": "台北大巨蛋",            # 富邦悍將主場 (638 場)
    "TYN": "樂天桃園棒球場",        # 樂天桃猿主場 (572 場)
    "XZG": "新莊棒球場",            # 富邦舊主場 (572 場)
    "API": "台南亞太成棒主球場",    # 統一獅新主場 (528 場)
    "INT": "洲際棒球場",            # 中信兄弟主場 (528 場)
    "CCL": "澄清湖棒球場",          # 味全龍主場 (495 場)
    "TMU": "天母棒球場",            # (451 場)
    "CYC": "嘉義市立棒球場",        # (110 場)
    "TTG": "TTG 球場 (待確認)",     # 台鋼副主場 (66 場) - 正式中文名待核對
    "HLN": "花蓮縣棒球場",          # (22 場)
    "DLU": "斗六棒球場",            # (22 場)
    # 歷史遺留 code (保留以防舊資料)
    "LOT": "樂天桃園棒球場",
    "TCD": "洲際棒球場",
    "ICC": "洲際棒球場",
    "TYB": "台南棒球場",
    "HSC": "新竹棒球場",
    "DLG": "斗六棒球場",
    "HLG": "花蓮縣棒球場",
}


def _to_chinese_name(name: str) -> str:
    """Convert English team name to Chinese if needed."""
    if any('\u4e00' <= c <= '\u9fff' for c in name):
        return name
    return EN_TO_ZH.get(name, name)


def _to_chinese_venue(venue: str) -> str:
    """Convert English venue abbreviation to Chinese."""
    if any('\u4e00' <= c <= '\u9fff' for c in venue):
        return venue
    return VENUE_MAP.get(venue, venue)


def apply_chinese_names(games: list[dict]) -> list[dict]:
    """Replace pitcher English names with CPBL-registered Chinese names where available.
    Fallback: keep original English when the player isn't in the mapping.
    Source of truth: app/scraper/player_names.json
    """
    from app.scraper.player_names import to_chinese
    for g in games:
        for field in ("home_pitcher", "away_pitcher"):
            val = g.get(field, "")
            if val and val != "TBD":
                g[field] = to_chinese(val)
    return games


async def scrape_today_schedule() -> list[dict]:
    """Scrape today's CPBL schedule via API."""
    today = date.today()
    return await scrape_schedule_for_date(today.year, today.month, today.day)


async def scrape_schedule_for_date(year: int, month: int, day: int | None = None) -> list[dict]:
    """Scrape CPBL schedule for a given year/month, optionally filter by day."""
    try:
        data = await fetch_api(
            BASE_URL,
            "/schedule",
            "/schedule/getgamedatas",
            {"kindCode": "A", "year": str(year), "month": str(month)},
        )

        if not data or not data.get("Success"):
            logger.error(f"CPBL API returned error: {data}")
            return []

        game_list = json.loads(data["GameDatas"])
        games = _parse_games(game_list, year, month, day)
        games = apply_chinese_names(games)
        return games

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
            "home_team_name": _to_chinese_name(g.get("HomeTeamName", home_info["name"])),
            "away_team": away_info["code"],
            "away_team_name": _to_chinese_name(g.get("VisitingTeamName", away_info["name"])),
            "venue": _to_chinese_venue(g.get("FieldAbbe", "")),
            "game_time": game_time,
            "home_pitcher": g.get("HomePitcherName", "TBD"),
            "away_pitcher": g.get("VisitingPitcherName", "TBD"),
            "home_logo": "https://en.cpbl.com.tw" + g.get("HomeClubSmallImgPath", "") if g.get("HomeClubSmallImgPath") else "",
            "away_logo": "https://en.cpbl.com.tw" + g.get("VisitingClubSmallImgPath", "") if g.get("VisitingClubSmallImgPath") else "",
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
