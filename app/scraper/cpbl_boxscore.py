"""Scrape CPBL box score details for settlement."""
from __future__ import annotations

import json
import logging
import re

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://www.cpbl.com.tw"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Accept-Language": "zh-TW,zh;q=0.9",
    "Referer": f"{BASE_URL}/box",
}


async def scrape_boxscore(game_sno: int, year: int = 2026) -> dict | None:
    """Scrape detailed box score for a game.
    Returns dict with: home_score, away_score, innings, total_hr,
    first_inning_runs, pitchers, batting, etc.
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Get verification token
            r = await client.get(
                f"{BASE_URL}/box/index?gameSno={game_sno}&year={year}&kindCode=A",
                headers=HEADERS,
                follow_redirects=True,
            )
            match = re.search(r'__RequestVerificationToken.*?value="([^"]+)"', r.text)
            if not match:
                match = re.search(r"RequestVerificationToken.*?'([^']+)'", r.text)
            token = match.group(1) if match else ""

            # Fetch box score data
            api_headers = {
                **HEADERS,
                "RequestVerificationToken": token,
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded",
            }

            r2 = await client.post(
                f"{BASE_URL}/box/getlive",
                data={"gameSno": str(game_sno), "year": str(year), "kindCode": "A"},
                headers=api_headers,
                cookies=dict(r.cookies),
                follow_redirects=True,
            )
            r2.raise_for_status()

        data = r2.json()
        if not data.get("Success"):
            return None

        return _parse_boxscore(data)

    except Exception as e:
        logger.error(f"Failed to scrape boxscore for game {game_sno}: {e}")
        return None


def _parse_boxscore(data: dict) -> dict:
    """Parse box score API response into structured result."""
    result = {
        "home_score": 0,
        "away_score": 0,
        "innings": [],
        "total_hr": 0,
        "first_inning_runs": 0,
        "home_team_name": "",
        "away_team_name": "",
        "pitchers": [],
        "batting_summary": [],
        "winning_margin": 0,
        "raw_text": "",  # For AI fallback
    }

    # Game detail
    gd_list = json.loads(data.get("GameDetailJson", "[]"))
    if gd_list:
        gd = gd_list[0] if isinstance(gd_list, list) else gd_list
        result["home_score"] = gd.get("HomeTotalScore", 0) or 0
        result["away_score"] = gd.get("VisitingTotalScore", 0) or 0
        result["home_team_name"] = gd.get("HomeTeamName", "")
        result["away_team_name"] = gd.get("VisitingTeamName", "")
        result["winning_margin"] = abs(result["home_score"] - result["away_score"])

    # Scoreboard (逐局比分)
    sb_list = json.loads(data.get("ScoreboardJson", "[]"))
    home_innings = {}
    away_innings = {}
    for item in sb_list:
        inning = item.get("Inning", 0)
        score = item.get("Score", 0) or 0
        vh_type = item.get("VisitingHomeType", 0)  # 1=away, 2=home
        if vh_type == 1:
            away_innings[inning] = score
        elif vh_type == 2:
            home_innings[inning] = score

    # First inning runs
    first_away = away_innings.get(1, 0)
    first_home = home_innings.get(1, 0)
    result["first_inning_runs"] = first_away + first_home

    # Batting stats (HR count)
    batting_list = json.loads(data.get("BattingJson", "[]"))
    total_hr = 0
    for b in batting_list:
        hr = b.get("HomeRunCnt", 0) or 0
        total_hr += hr
        if hr > 0 or (b.get("HittingCnt", 0) or 0) > 0:
            result["batting_summary"].append({
                "name": b.get("HitterName", ""),
                "team": "home" if b.get("VisitingHomeType") == 2 else "away",
                "hits": b.get("HittingCnt", 0) or 0,
                "hr": hr,
                "rbi": b.get("RunBattedInCnt", 0) or 0,
            })
    result["total_hr"] = total_hr

    # Pitching stats
    pitching_list = json.loads(data.get("PitchingJson", "[]"))
    for p in pitching_list:
        ip_full = p.get("InningPitchedCnt", 0) or 0
        ip_frac = p.get("InningPitchedDiv3Cnt", 0) or 0
        result["pitchers"].append({
            "name": p.get("PitcherName", ""),
            "team": "home" if p.get("VisitingHomeType") == 2 else "away",
            "ip": f"{ip_full}.{ip_frac}",
            "strikeouts": p.get("StrikeOutCnt", 0) or 0,
            "earned_runs": p.get("EarnedRunCnt", 0) or 0,
            "hits_allowed": p.get("HittingCnt", 0) or 0,
            "walks": p.get("BasesOnBallsCnt", 0) or 0,
        })

    # Build raw text summary for AI
    lines = [
        f"{result['away_team_name']} {result['away_score']} : {result['home_score']} {result['home_team_name']}",
        f"首局得分: {result['first_inning_runs']} (客{first_away} 主{first_home})",
        f"全壘打: {result['total_hr']}",
        f"勝分差: {result['winning_margin']}",
    ]
    for p in result["pitchers"]:
        side = "主" if p["team"] == "home" else "客"
        lines.append(f"  {side} {p['name']}: {p['ip']}局 {p['strikeouts']}K {p['earned_runs']}ER")
    result["raw_text"] = "\n".join(lines)

    return result
