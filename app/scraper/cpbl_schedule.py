"""Scrape CPBL daily schedule from cpbl.com.tw API."""
from __future__ import annotations

import json
import logging
import re
from datetime import date

logger = logging.getLogger(__name__)

from app.scraper.http_client import fetch_api

BASE_URL = "https://www.cpbl.com.tw"

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


def _resolve_pitcher(name: str | None, acnt: str | None) -> str:
    """Resolve the announced starter. Pre-game CPBL fills Acnt before Name; we
    look the acnt up against player_names.json so the bot shows a real name
    instead of blank as soon as the announcement is published."""
    name = (name or "").strip()
    if name:
        return name
    acnt = (acnt or "").strip()
    if acnt:
        from app.scraper.player_names import to_chinese_by_acnt
        return to_chinese_by_acnt(acnt)
    return ""


async def scrape_today_schedule() -> list[dict]:
    """Scrape today's CPBL schedule via API."""
    today = date.today()
    return await scrape_schedule_for_date(today.year, today.month, today.day)


async def scrape_schedule_for_date(year: int, month: int, day: int | None = None) -> list[dict]:
    """Build a month's schedule via iterative /box/getlive discovery.

    /schedule/getgamedatas is permanently 404'd from non-TW datacenter ASNs
    (HiNet CDN path-block), so we don't try it from the VM. To populate
    announced starting pitchers (the fields /box/getlive doesn't carry),
    POST raw schedule JSON to /ingest/schedule from a TW-residential relay;
    the schedulers short-circuit to read from DB when a recent ingest exists.
    """
    return await _scrape_via_box_fallback(year, month, day)


async def _scrape_via_box_fallback(year: int, month: int, day: int | None = None) -> list[dict]:
    """Iteratively discover a month's games via /box/getlive when the schedule
    API is blocked. /box/getlive returns ALL games for the day a queried
    gameSno belongs to, so we walk gameSno forward day-by-day until we hit
    a date past the target month."""
    from app.scraper.http_client import get_cpbl_session, _ajax_headers, _browser_headers
    from app.db.client import get_db

    from datetime import date as _date, timedelta as _td

    db = get_db()
    target_prefix = f"{year}-{month:02d}-"

    # Seed from a recent-window max(game_sno), not the all-time max for the
    # year — /ingest/schedule writes future-month games (CPBL pre-publishes
    # the full season), and an all-time-max seed lands in those future months,
    # making the forward walk exit on the first iteration with 0 games.
    today = _date.today()
    latest = db["games"].find_one(
        {
            "date": {
                "$gte": (today - _td(days=7)).isoformat(),
                "$lte": (today + _td(days=2)).isoformat(),
            },
            "game_sno": {"$gt": 0},
        },
        sort=[("game_sno", -1)],
    )
    if not latest:
        logger.warning("[box-fallback] no seed game_sno in db.games (today±window); cannot fall back")
        return []
    seed_sno = max(1, (latest.get("game_sno") or 0) - 10)
    logger.info(f"[box-fallback] seeding from sno={seed_sno} for {year}-{month:02d}")

    games_out: list[dict] = []
    seen_snos: set[int] = set()
    sno = seed_sno
    misses = 0
    safety = 60

    client, _ = await get_cpbl_session(BASE_URL)
    try:
        page_url = f"{BASE_URL}/box/index?gameSno={sno}&year={year}&kindCode=A"
        page_r = await client.get(page_url, headers=_browser_headers(referer=BASE_URL + "/"))
        m = re.search(r"RequestVerificationToken:\s*'([A-Za-z0-9_\-:]+)'", page_r.text)
        if not m:
            m = re.search(r'__RequestVerificationToken.*?value="([^"]+)"', page_r.text)
        token = m.group(1) if m else ""
        if not token:
            logger.error("[box-fallback] could not obtain token from /box/index")
            return []

        ajax_h = _ajax_headers(page_url, token)

        while safety > 0 and misses < 5:
            safety -= 1
            try:
                api_r = await client.post(
                    f"{BASE_URL}/box/getlive",
                    data={"gameSno": str(sno), "year": str(year), "kindCode": "A"},
                    headers=ajax_h,
                )
                d = api_r.json()
            except Exception as e:
                logger.warning(f"[box-fallback] /box/getlive sno={sno} failed: {e}")
                misses += 1
                sno += 1
                continue

            if not d.get("Success"):
                misses += 1
                sno += 1
                continue

            day_games = json.loads(d.get("GameDetailJson") or "[]")
            if not day_games:
                misses += 1
                sno += 1
                continue

            anchor_date = (day_games[0].get("GameDateTimeS") or "")[:10]
            if anchor_date and anchor_date > f"{year}-{month:02d}-31":
                break

            added = False
            for g in day_games:
                gs = g.get("GameSno")
                if gs in seen_snos:
                    continue
                seen_snos.add(gs)
                gd = (g.get("GameDateTimeS") or "")[:10]
                if not gd.startswith(target_prefix):
                    continue
                games_out.append(_box_game_to_dict(g, gd))
                added = True

            max_sno = max((g.get("GameSno", sno) for g in day_games), default=sno)
            misses = 0 if added else (misses + 1)
            sno = max_sno + 1
    finally:
        await client.aclose()

    if day is not None:
        target_day = f"{year}-{month:02d}-{day:02d}"
        games_out = [g for g in games_out if g["date"] == target_day]

    logger.info(f"[box-fallback] returning {len(games_out)} games")
    return apply_chinese_names(games_out)


def _box_game_to_dict(g: dict, game_date: str) -> dict:
    """Convert one /box/getlive GameDetailJson entry to our schedule shape."""
    sno = g.get("GameSno", 0)
    home_name = g.get("HomeTeamName", "")
    away_name = g.get("VisitingTeamName", "")
    home_code_raw = g.get("HomeTeamCode", "")
    away_code_raw = g.get("VisitingTeamCode", "")
    home_info = TEAM_CODE_MAP.get(home_code_raw, {"code": home_code_raw, "name": home_name})
    away_info = TEAM_CODE_MAP.get(away_code_raw, {"code": away_code_raw, "name": away_name})

    s_int = g.get("GameStatus")
    chi = g.get("GameStatusChi", "")
    if s_int == 3 or "比賽結束" in chi:
        status = "final"
    elif "延" in chi or "保留" in chi or "取消" in chi:
        status = "postponed"
    else:
        status = "scheduled"

    home_logo_path = g.get("HomeClubSmallImgPath") or ""
    away_logo_path = g.get("VisitingClubSmallImgPath") or ""
    out: dict = {
        "id": f"{game_date.replace('-', '')}_{sno}",
        "date": game_date,
        "game_sno": sno,
        "home_team": home_info["code"],
        "home_team_name": _to_chinese_name(home_name),
        "away_team": away_info["code"],
        "away_team_name": _to_chinese_name(away_name),
        "venue": _to_chinese_venue(g.get("FieldAbbe", "")),
        "game_time": (g.get("GameDateTimeS") or "")[11:16] or "18:35",
        "home_logo": (BASE_URL + home_logo_path) if home_logo_path else "",
        "away_logo": (BASE_URL + away_logo_path) if away_logo_path else "",
        "status": status,
    }
    # /box/getlive does not carry the announced starter — only set the field
    # when we actually have one, so a follow-up ingest with real data is not
    # overwritten by a Mongo $set with empty string.
    home_pitcher = _resolve_pitcher(g.get("HomePitcherName"), g.get("HomePitcherAcnt"))
    away_pitcher = _resolve_pitcher(g.get("VisitingPitcherName"), g.get("VisitingPitcherAcnt"))
    if home_pitcher:
        out["home_pitcher"] = home_pitcher
    if away_pitcher:
        out["away_pitcher"] = away_pitcher
    if status == "final":
        out["home_score"] = g.get("HomeTotalScore", 0) or 0
        out["away_score"] = g.get("VisitingTotalScore", 0) or 0
    return out


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
            "home_logo": "https://www.cpbl.com.tw" + g.get("HomeClubSmallImgPath", "") if g.get("HomeClubSmallImgPath") else "",
            "away_logo": "https://www.cpbl.com.tw" + g.get("VisitingClubSmallImgPath", "") if g.get("VisitingClubSmallImgPath") else "",
            "status": status,
        }
        # CPBL fills PitcherAcnt before PitcherName for announced starters; only
        # set the field when we actually have one so $set upserts won't overwrite
        # a previously-ingested name with an empty string.
        home_pitcher = _resolve_pitcher(g.get("HomePitcherName"), g.get("HomePitcherAcnt"))
        away_pitcher = _resolve_pitcher(g.get("VisitingPitcherName"), g.get("VisitingPitcherAcnt"))
        if home_pitcher:
            game["home_pitcher"] = home_pitcher
        if away_pitcher:
            game["away_pitcher"] = away_pitcher

        # If game is finished, include scores
        if status == "final":
            game["home_score"] = g.get("HomeScore", 0)
            game["away_score"] = g.get("VisitingScore", 0)
            game["winner"] = "home" if game["home_score"] > game["away_score"] else "away"

        games.append(game)

    games.sort(key=lambda x: x["game_sno"])
    return games
