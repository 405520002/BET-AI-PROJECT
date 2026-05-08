"""Scrape CPBL schedule + announced starters from today.line.me.

Why: www.cpbl.com.tw/schedule/getgamedatas (the only CPBL endpoint that
carries announced SPs) is HiNet-CDN geo-blocked from non-TW datacenter
ASNs, so the VM cannot reach it directly. today.line.me is NOT geo-
blocked and serves the same data plus zh team/pitcher names already
populated, hydrated as JSON inside __NEXT_DATA__.

Public API:
    fetch_line_today_schedule(season=...) -> list[dict]
        Returns the full season's games in our internal format
        (same shape as cpbl_schedule._parse_games).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone, timedelta

import httpx

logger = logging.getLogger(__name__)

DEFAULT_SEASON = "CPBL-2026-oB"
SCHEDULE_URL = "https://today.line.me/tw/v3/baseball/seasons/{season}/schedule"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)

_TPE = timezone(timedelta(hours=8))

# zh team name → our CPBL team code
_TEAM_NAME_TO_CODE = {
    "中信兄弟": "ACN",
    "統一7-ELEVEn獅": "ADD",
    "樂天桃猿": "AJL",
    "富邦悍將": "AEO",
    "味全龍": "AAA",
    "台鋼雄鷹": "AKP",
}

# LINE Today uses formal/長 stadium names; map to the short names already
# stored in DB by the box-fallback path so downstream Flex cards render
# consistently.
_VENUE_NORMALIZE = {
    "臺北大巨蛋": "台北大巨蛋",
    "新北市立新莊棒球場": "新莊棒球場",
    "亞太國際棒球訓練中心-主球場": "台南亞太成棒主球場",
    "臺中市洲際棒球場": "洲際棒球場",
    "臺北市立天母棒球場": "天母棒球場",
    "花蓮縣立德興棒球場": "花蓮縣棒球場",
    # already in canonical short form; keep identity to make this map authoritative
    "樂天桃園棒球場": "樂天桃園棒球場",
    "澄清湖棒球場": "澄清湖棒球場",
    "嘉義市立棒球場": "嘉義市立棒球場",
    "斗六棒球場": "斗六棒球場",
    "臺東棒球村第一棒球場": "臺東棒球村第一棒球場",
}

_STATUS_MAP = {
    "SCHEDULED": "scheduled",
    "FINISHED": "final",
    "POSTPONED": "postponed",
}


async def fetch_line_today_schedule(season: str = DEFAULT_SEASON) -> list[dict]:
    """Fetch full-season schedule from today.line.me, return parsed games.

    Output shape matches cpbl_schedule._parse_games — same id format
    (`{YYYYMMDD}_{game_sno}`), same fields. Empty list on any failure;
    callers should fall back to whatever they were doing before."""
    url = SCHEDULE_URL.format(season=season)
    try:
        async with httpx.AsyncClient(
            timeout=15.0, headers={"User-Agent": _USER_AGENT}, follow_redirects=True
        ) as client:
            r = await client.get(url)
    except Exception as e:
        logger.warning("line_today: fetch failed: %s", e)
        return []
    if r.status_code != 200:
        logger.warning("line_today: HTTP %d", r.status_code)
        return []

    m = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', r.text, flags=re.DOTALL
    )
    if not m:
        logger.warning("line_today: __NEXT_DATA__ script tag missing")
        return []
    try:
        next_data = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        logger.warning("line_today: __NEXT_DATA__ parse failed: %s", e)
        return []

    fallback = (
        next_data.get("props", {}).get("pageProps", {}).get("fallback", {})
    )
    sched_keys = [k for k in fallback if "competition_schedule" in k]
    if not sched_keys:
        logger.warning("line_today: no competition_schedule key in fallback")
        return []
    raw_games = fallback[sched_keys[0]]
    if not isinstance(raw_games, list):
        logger.warning("line_today: schedule payload not a list")
        return []

    out: list[dict] = []
    for g in raw_games:
        parsed = _parse_one(g)
        if parsed:
            out.append(parsed)
    logger.info("line_today: parsed %d / %d games", len(out), len(raw_games))
    return out


def _parse_one(g: dict) -> dict | None:
    try:
        sched_at = g.get("scheduledStartAt") or g.get("startAt") or ""
        if not sched_at:
            return None
        # ISO 8601 UTC ("2026-05-08T10:35:00Z") → Taipei date / time
        dt_utc = datetime.strptime(sched_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        dt_tpe = dt_utc.astimezone(_TPE)
        date_str = dt_tpe.strftime("%Y-%m-%d")
        time_str = dt_tpe.strftime("%H:%M")

        seq = g.get("seq", 0) or 0
        if not seq:
            return None

        away_name = g.get("away", {}).get("name", "")
        home_name = g.get("home", {}).get("name", "")
        away_code = _TEAM_NAME_TO_CODE.get(away_name, away_name)
        home_code = _TEAM_NAME_TO_CODE.get(home_name, home_name)

        status_raw = g.get("status", "")
        status = _STATUS_MAP.get(status_raw, "scheduled")

        venue_raw = g.get("stadium", "")
        venue = _VENUE_NORMALIZE.get(venue_raw, venue_raw)

        record = {
            "id": f"{date_str.replace('-', '')}_{seq}",
            "date": date_str,
            "game_sno": seq,
            "home_team": home_code,
            "home_team_name": home_name,
            "away_team": away_code,
            "away_team_name": away_name,
            "venue": venue,
            "game_time": time_str,
            "home_logo": "",
            "away_logo": "",
            "status": status,
        }

        # Announced starters — only set when LINE has them, so a $set upsert
        # doesn't clobber a pitcher already populated by /ingest/schedule.
        away_sp = (g.get("awayScheduledSP") or {}).get("name") or ""
        home_sp = (g.get("homeScheduledSP") or {}).get("name") or ""
        if away_sp:
            record["away_pitcher"] = away_sp.strip()
        if home_sp:
            record["home_pitcher"] = home_sp.strip()

        if status == "final":
            record["home_score"] = g.get("homeRuns", 0) or 0
            record["away_score"] = g.get("awayRuns", 0) or 0
            if record["home_score"] != record["away_score"]:
                record["winner"] = (
                    "home" if record["home_score"] > record["away_score"] else "away"
                )

        return record
    except Exception as e:
        logger.warning("line_today: parse error on game seq=%s: %s", g.get("seq"), e)
        return None
