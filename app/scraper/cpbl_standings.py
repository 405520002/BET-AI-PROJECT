"""Scrape CPBL team standings from cpbl.com.tw."""
from __future__ import annotations

import logging
import re

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

STANDINGS_URL = "https://www.cpbl.com.tw/standings/season"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Accept-Language": "zh-TW,zh;q=0.9",
    "Referer": "https://www.cpbl.com.tw/",
}

TEAM_NAME_NORMALIZE = {
    "中信兄弟": "ACN",
    "兄弟": "ACN",
    "統一7-ELEVEn獅": "ADD",
    "統一獅": "ADD",
    "統一": "ADD",
    "樂天桃猿": "AJL",
    "樂天": "AJL",
    "富邦悍將": "AEO",
    "悍將": "AEO",
    "富邦": "AEO",
    "味全龍": "AAA",
    "味全": "AAA",
    "台鋼雄鷹": "AKP",
    "台鋼": "AKP",
    # English names (en.cpbl.com.tw)
    "Brothers": "ACN",
    "CTBC Brothers": "ACN",
    "U-Lions": "ADD",
    "Uni-Lions": "ADD",
    "Monkeys": "AJL",
    "Rakuten Monkeys": "AJL",
    "Guardians": "AEO",
    "Fubon Guardians": "AEO",
    "DRAGONS": "AAA",
    "Dragons": "AAA",
    "Wei Chuan Dragons": "AAA",
    "TSG Hawks": "AKP",
    "Hawks": "AKP",
}

TEAM_FULL_NAMES = {
    "ACN": "中信兄弟",
    "ADD": "統一7-ELEVEn獅",
    "AJL": "樂天桃猿",
    "AEO": "富邦悍將",
    "AAA": "味全龍",
    "AKP": "台鋼雄鷹",
}


async def scrape_standings() -> dict:
    """Scrape current CPBL standings."""
    from app.scraper.http_client import fetch_page
    try:
        html = await fetch_page("https://www.cpbl.com.tw", "/standings/season")
        if not html:
            return _default_standings()
    except Exception as e:
        logger.error(f"Failed to fetch CPBL standings: {e}")
        return _default_standings()

    standings = _parse_standings_html(html)
    if not standings:
        logger.warning("Could not parse standings, using defaults")
        return _default_standings()

    return standings


def _parse_standings_html(html: str) -> dict:
    """Parse standings HTML.
    Table 0 = team standings: 排名球隊, 出賽數, 勝-和-敗, 勝率, ..., 近十場戰績
    Table 1 = team pitching: 球隊, 出賽數, ..., 防禦率
    """
    soup = BeautifulSoup(html, "html.parser")
    standings = {}

    tables = soup.select("table")
    if not tables:
        return standings

    # Parse Table 0: standings
    rows = tables[0].select("tr")[1:]  # skip header
    for row in rows:
        cells = row.select("td")
        if len(cells) < 6:
            continue

        team_text = cells[0].get_text(strip=True)
        team_code = None
        for name, code in TEAM_NAME_NORMALIZE.items():
            if name in team_text:
                team_code = code
                break

        if not team_code:
            continue

        try:
            # cells[1] = 出賽數, cells[2] = "勝-和-敗", cells[3] = 勝率
            record_text = cells[2].get_text(strip=True)  # e.g. "8-0-4"
            record_parts = record_text.split("-")
            wins = int(record_parts[0])
            ties = int(record_parts[1]) if len(record_parts) > 2 else 0
            losses = int(record_parts[-1])

            win_rate_text = cells[3].get_text(strip=True)
            try:
                win_rate = float(win_rate_text)
            except ValueError:
                win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0.500

            # 近十場戰績 is the last column
            recent_10 = cells[-1].get_text(strip=True) if len(cells) > 10 else "N/A"

            standings[team_code] = {
                "name": TEAM_FULL_NAMES.get(team_code, team_text),
                "code": team_code,
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "win_rate": round(win_rate, 3),
                "avg_runs": 4.5,
                "team_era": "N/A",
                "recent_10": recent_10,
            }
        except (ValueError, IndexError) as e:
            logger.warning(f"Failed to parse standings row for {team_code}: {e}")

    # Parse Table 1: pitching stats (for ERA)
    if len(tables) > 1:
        rows = tables[1].select("tr")[1:]
        for row in rows:
            cells = row.select("td")
            if len(cells) < 5:
                continue

            team_text = cells[0].get_text(strip=True)
            team_code = None
            for name, code in TEAM_NAME_NORMALIZE.items():
                if name in team_text:
                    team_code = code
                    break

            if team_code and team_code in standings:
                # Last column is ERA
                era_text = cells[-1].get_text(strip=True)
                standings[team_code]["team_era"] = era_text

    return standings


def _default_standings() -> dict:
    return {
        code: {
            "name": name,
            "code": code,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.500,
            "avg_runs": 4.5,
            "team_era": "N/A",
            "recent_10": "N/A",
        }
        for code, name in TEAM_FULL_NAMES.items()
    }
