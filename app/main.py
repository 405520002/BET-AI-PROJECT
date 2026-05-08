"""FastAPI application entry point with LINE webhook and cron endpoints."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

import asyncio

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse, Response
from linebot.v3.webhook import WebhookParser
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    PostbackEvent,
    FollowEvent,
)

from app.config import settings
from app.line_bot.handler import (
    handle_follow,
    handle_text_message,
    handle_postback,
)
from app.scheduler.jobs import (
    morning_job,
    midday_update,
    midnight_settle,
    send_pending_notifications,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("CPBL Betting Bot starting up")
    # One-shot DB seed: copy app/scraper/player_names.json into db.player_roster
    # the first time the collection is empty. After that, all roster writes
    # come from the daily Wiki refresh, /ingest/roster, or runtime fallback.
    try:
        from app.db import roster_repo
        seeded = roster_repo.seed_from_json_if_empty()
        if seeded:
            logger.info(f"Roster seeded from JSON: {seeded} players")
    except Exception as e:
        logger.warning(f"Roster seed skipped: {e}")

    # Start background notification checker (only in one worker via file lock)
    import os, fcntl
    scheduler = None
    lock_file = None
    try:
        lock_file = open("/tmp/notify_scheduler.lock", "w")
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler(timezone="Asia/Taipei")
        scheduler.add_job(_check_notifications, "interval", seconds=30, id="notify_checker")
        # Daily 04:00 Asia/Taipei: refresh roster from Wikipedia categories.
        # Wikipedia isn't geo-blocked (unlike www.cpbl.com.tw) so this runs
        # autonomously on the VM regardless of region.
        scheduler.add_job(_refresh_wiki_roster, "cron", hour=4, minute=0, id="wiki_roster_refresh")
        # Schedule + announced starters from today.line.me. Replaces the
        # iPhone Shortcut → /ingest/schedule path: today.line.me has the
        # same data but is reachable from non-TW IPs. 07:30 catches CPBL's
        # morning pitcher announcements before morning_job at 08:00; 12:30
        # picks up midday updates.
        scheduler.add_job(_refresh_line_schedule, "cron", hour=7, minute=30, id="line_schedule_morning")
        scheduler.add_job(_refresh_line_schedule, "cron", hour=12, minute=30, id="line_schedule_midday")
        scheduler.start()
        logger.info(
            "Notification checker started (every 30s); Wiki refresh 04:00; "
            "LINE Today schedule refresh 07:30 + 12:30"
        )
    except (IOError, OSError):
        logger.info("Schedulers already running in another worker")
    yield
    if scheduler:
        scheduler.shutdown()
    logger.info("CPBL Betting Bot shutting down")


def _check_notifications():
    """Background job: send due notifications."""
    import asyncio
    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(send_pending_notifications())
        if result.get("notified", 0) > 0:
            logger.info(f"Notifications sent: {result}")
        loop.close()
    except Exception as e:
        logger.error(f"Notification checker error: {e}")


async def _refresh_wiki_roster_async() -> dict:
    """Rebuild player roster via zh.wikipedia.org per-team category sweep.
    Higher-trust seed/shortcut entries are preserved by roster_repo's
    priority logic. Returns a stats dict with scanned/upserted counts."""
    from app.scraper.wiki_lookup import refresh_wiki_roster
    from app.db import roster_repo

    roster = await refresh_wiki_roster()
    records = [
        {"name": name, "acnt": v["acnt"], "team": v["team"]}
        for name, v in roster.items()
    ]
    n = roster_repo.bulk_upsert(records, team="", source="wiki")
    return {
        "scanned": len(records),
        "upserted": n,
        "roster_count": roster_repo.count(),
    }


def _refresh_wiki_roster():
    """Sync wrapper for APScheduler (its worker threads have no running loop,
    so asyncio.run is safe). FastAPI endpoints should await
    _refresh_wiki_roster_async directly to avoid the running-loop conflict."""
    import asyncio
    try:
        result = asyncio.run(_refresh_wiki_roster_async())
        logger.info(
            f"Wiki roster refresh: {result['upserted']}/{result['scanned']} upserted"
        )
    except Exception as e:
        logger.error(f"Wiki roster refresh failed: {e}", exc_info=True)


async def _refresh_line_schedule_async() -> dict:
    """Pull the full-season schedule from today.line.me, upsert each game
    into db.games (preserving any existing odds field), and bump the
    `schedule_last_ingest` cache marker so morning_job's freshness check
    short-circuits the slow box-fallback."""
    from datetime import datetime
    from app.scraper.line_today_schedule import fetch_line_today_schedule
    from app.db import game_repo
    from app.db.client import get_db

    games = await fetch_line_today_schedule()
    if not games:
        return {"status": "no_games", "scanned": 0, "upserted": 0}

    upserted = 0
    pitchers_filled = 0
    for game in games:
        gid = game["id"]
        existing = game_repo.get_game(gid)
        if existing and "odds" in existing:
            game["odds"] = existing["odds"]
        game_repo.upsert_game(gid, game)
        upserted += 1
        if game.get("home_pitcher") or game.get("away_pitcher"):
            pitchers_filled += 1

    get_db()["cache"].update_one(
        {"_id": "schedule_last_ingest"},
        {"$set": {"updated_at": datetime.now(), "games_count": upserted, "source": "line_today"}},
        upsert=True,
    )
    return {"status": "ok", "scanned": len(games), "upserted": upserted, "pitchers_filled": pitchers_filled}


def _refresh_line_schedule():
    """Sync wrapper for APScheduler — see _refresh_wiki_roster for the same
    pattern."""
    import asyncio
    try:
        result = asyncio.run(_refresh_line_schedule_async())
        logger.info(
            f"LINE Today schedule refresh: {result.get('upserted')} games "
            f"({result.get('pitchers_filled')} with announced pitchers)"
        )
    except Exception as e:
        logger.error(f"LINE Today schedule refresh failed: {e}", exc_info=True)


app = FastAPI(title="CPBL Virtual Betting Bot", lifespan=lifespan)
parser = WebhookParser(settings.line_channel_secret)


# --- LINE Webhook ---

@app.post("/webhook")
async def webhook(request: Request):
    """LINE webhook endpoint."""
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()

    try:
        events = parser.parse(body.decode("utf-8"), signature)
    except Exception as e:
        logger.error(f"Webhook parse error: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        try:
            if isinstance(event, FollowEvent):
                handle_follow(event)
            elif isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent):
                handle_text_message(event)
            elif isinstance(event, PostbackEvent):
                handle_postback(event)
        except Exception as e:
            logger.error(f"Error handling event: {e}", exc_info=True)

    return "OK"


# --- Cron Endpoints (called by Cloud Scheduler) ---

def _verify_cron(cron_secret: Optional[str]):
    """Verify the cron request is authorized."""
    if settings.env == "development":
        return  # skip in dev
    if not cron_secret or cron_secret != settings.cron_secret:
        raise HTTPException(status_code=403, detail="Unauthorized")


@app.post("/cron/morning")
async def cron_morning(x_cron_secret: Optional[str] = Header(None)):
    """08:00 - Scrape schedule + AI generate odds."""
    _verify_cron(x_cron_secret)
    result = await morning_job()
    return {"status": "ok", **result}


@app.post("/cron/midday")
async def cron_midday(x_cron_secret: Optional[str] = Header(None)):
    """12:00 - Update game info (pitchers/venue), keep odds."""
    _verify_cron(x_cron_secret)
    result = await midday_update()
    return {"status": "ok", **result}


@app.post("/cron/settle")
async def cron_settle(x_cron_secret: Optional[str] = Header(None)):
    """00:00 - Scrape results + settle bets."""
    _verify_cron(x_cron_secret)
    result = await midnight_settle()
    return {"status": "ok", **result}


@app.post("/cron/notify")
async def cron_notify(x_cron_secret: Optional[str] = Header(None)):
    """Every 1 min - Send due pre-game notifications."""
    _verify_cron(x_cron_secret)
    result = await send_pending_notifications()
    return {"status": "ok", **result}


@app.post("/cron/weekly-awards")
async def cron_weekly_awards(force: bool = False, x_cron_secret: Optional[str] = Header(None)):
    """Monday - push last week's player leaders (HR / AVG / ERA / Errors). Use ?force=1 to override idempotency."""
    _verify_cron(x_cron_secret)
    from app.scheduler.weekly_awards import push_weekly_awards
    result = push_weekly_awards(force=force)
    return result


# === Player Stats Endpoints (cpbl-stat-player-summary) ===

@app.get("/player/summary")
async def player_summary(q: str):
    """Resolve player by zh name, scrape advanced stats, return AI summary + radar URL."""
    from app.scraper.player_lookup import parse_query, find_player_async
    from app.scraper.cpbl_player_stats import fetch_player_advanced_stats
    from app.services.player_summary_ai import generate_player_summary

    name_part, rest = parse_query(q)
    player_meta = await find_player_async(name_part)
    if player_meta is None:
        return JSONResponse({"error": "找不到球員", "query": q}, status_code=404)

    stats = await fetch_player_advanced_stats(player_meta["acnt"])
    if stats is None:
        return JSONResponse({"error": "球員頁面爬取失敗", "acnt": player_meta["acnt"]}, status_code=502)

    summary = await asyncio.to_thread(generate_player_summary, stats, stats["axes"], rest)

    return {
        "player_name": stats["name_zh"],
        "uniform_no": stats["uniform_no"],
        "team": stats["team"],
        "position": stats["position_zh"],
        "role": stats["role"],
        "player_url": stats["page_url"],
        "axes": stats["axes"],
        "summary": summary,
        "radar_image_url": f"/player/radar.png?acnt={stats['acnt']}",
    }


@app.get("/player/radar.png")
async def player_radar(acnt: str):
    """Return cached PNG radar chart for the given player acnt."""
    from app.scraper.cpbl_player_stats import fetch_player_advanced_stats
    from app.services.radar_cache import get_or_render

    stats = await fetch_player_advanced_stats(acnt)
    if stats is None:
        return JSONResponse({"error": "找不到球員"}, status_code=404)

    png = await asyncio.to_thread(get_or_render, stats, stats["axes"])
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "public, max-age=1800"})


# --- Ingest Endpoints (residential-IP relay; HiNet CDN blocks datacenter ASNs on /standings/season) ---

@app.post("/ingest/roster")
async def ingest_roster(
    request: Request,
    team: str = "",
    x_cron_secret: Optional[str] = Header(None),
):
    """Receive raw www.cpbl.com.tw/team?ClubNo=X HTML from a TW-IP residential
    relay (iPhone Shortcut), parse the player anchors, and upsert each entry
    into db.player_roster as source='shortcut' (highest trust)."""
    _verify_cron(x_cron_secret)
    raw = await request.body()
    if not raw:
        raise HTTPException(status_code=400, detail="empty body")
    if not team:
        raise HTTPException(status_code=400, detail="missing 'team' query param")

    html = raw.decode("utf-8", errors="replace")
    from app.scraper.cpbl_team_roster import parse_team_roster
    records = parse_team_roster(html)
    if not records:
        raise HTTPException(
            status_code=400,
            detail="no player anchors parsed (HTML may be a 404 page)",
        )

    from app.db import roster_repo
    n = roster_repo.bulk_upsert(records, team=team, source="shortcut")
    logger.info(f"[ingest/roster] {team}: {n}/{len(records)} upserted via shortcut")
    return {"status": "ok", "team": team, "parsed": len(records), "upserted": n}


@app.post("/cron/refresh-roster")
async def cron_refresh_roster(x_cron_secret: Optional[str] = Header(None)):
    """Manual trigger for the daily Wiki refresh — useful for first-time
    deploys where you don't want to wait until 04:00 the next day. Blocks
    for ~2-3 minutes while ~700 player Wikipedia pages are fetched."""
    _verify_cron(x_cron_secret)
    result = await _refresh_wiki_roster_async()
    return {"status": "ok", **result}


@app.post("/cron/refresh-line-schedule")
async def cron_refresh_line_schedule(x_cron_secret: Optional[str] = Header(None)):
    """Manual trigger for today.line.me schedule scrape. Returns immediately
    after the upsert — single HTTP fetch, ~1-2 seconds."""
    _verify_cron(x_cron_secret)
    result = await _refresh_line_schedule_async()
    return result


@app.post("/ingest/standings")
async def ingest_standings(
    request: Request,
    x_cron_secret: Optional[str] = Header(None),
):
    """Receive raw https://www.cpbl.com.tw/standings/season HTML from a residential
    client (e.g. iPhone Shortcut on cellular), parse it, and refresh the standings cache."""
    _verify_cron(x_cron_secret)
    raw = await request.body()
    if not raw:
        raise HTTPException(status_code=400, detail="empty body")
    html = raw.decode("utf-8", errors="replace")

    from app.scraper.cpbl_standings import _parse_standings_html
    standings = _parse_standings_html(html)
    if not standings or len(standings) < 6:
        raise HTTPException(
            status_code=400,
            detail=f"parsed {len(standings)} teams, expected 6 (HTML may be the 404 page)",
        )

    from app.db.client import get_db
    from datetime import date
    get_db()["cache"].update_one(
        {"_id": "standings"},
        {"$set": {"data": standings, "updated_at": date.today().isoformat()}},
        upsert=True,
    )
    logger.info(f"[ingest] Standings cache updated via residential relay: {len(standings)} teams")
    return {"status": "ok", "teams": len(standings)}


@app.post("/ingest/schedule")
async def ingest_schedule(
    request: Request,
    x_cron_secret: Optional[str] = Header(None),
):
    """Receive raw https://www.cpbl.com.tw/schedule/getgamedatas JSON from a residential
    client (e.g. iPhone Shortcut on cellular), parse it, and upsert games. The
    schedule API is the only path that carries announced starters (HomePitcherAcnt /
    VisitingPitcherAcnt before HomePitcherName / VisitingPitcherName populate);
    /box/getlive — the only path reachable from non-TW datacenter ASNs — does not."""
    import json
    from datetime import datetime

    _verify_cron(x_cron_secret)
    raw = await request.body()
    if not raw:
        raise HTTPException(status_code=400, detail="empty body")

    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid JSON: {e}")

    if not payload.get("Success"):
        raise HTTPException(status_code=400, detail=f"payload Success=False: {payload}")
    games_blob = payload.get("GameDatas")
    if not games_blob:
        raise HTTPException(status_code=400, detail="payload missing GameDatas")
    try:
        game_list = json.loads(games_blob) if isinstance(games_blob, str) else games_blob
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"GameDatas not parseable: {e}")
    if not game_list:
        return {"status": "ok", "games": 0}

    from app.scraper.cpbl_schedule import _parse_games, apply_chinese_names
    first_date = (game_list[0].get("GameDate") or "")[:10]
    year = int(first_date[:4]) if first_date else date.today().year
    month = int(first_date[5:7]) if first_date else date.today().month
    games = apply_chinese_names(_parse_games(game_list, year, month, day=None))

    from app.db import game_repo
    from app.db.client import get_db
    for game in games:
        gid = game.get("id", "")
        existing = game_repo.get_game(gid)
        if existing and "odds" in existing:
            game["odds"] = existing["odds"]
        game_repo.upsert_game(gid, game)

    # Marker the schedulers read to short-circuit their box-fallback scrape.
    get_db()["cache"].update_one(
        {"_id": "schedule_last_ingest"},
        {"$set": {"updated_at": datetime.now(), "games_count": len(games)}},
        upsert=True,
    )

    logger.info(f"[ingest] Schedule upserted via residential relay: {len(games)} games")
    return {"status": "ok", "games": len(games)}


# --- Health Check ---

@app.get("/health")
async def health():
    return {"status": "ok", "service": "cpbl-betting-bot"}


# --- Dev: Manual Test Endpoints ---

if settings.env == "development":
    from datetime import date

    @app.post("/dev/create-test-games")
    async def create_test_games():
        """Create test games with AI-generated odds."""
        from app.db import game_repo
        from app.betting.odds_engine import generate_odds_for_games

        today = date.today().isoformat()

        test_games = [
            {
                "id": f"{today.replace('-', '')}_1",
                "date": today,
                "game_sno": 1,
                "home_team": "ACN",
                "home_team_name": "中信兄弟",
                "away_team": "AAA",
                "away_team_name": "味全龍",
                "venue": "洲際棒球場",
                "game_time": "18:35",
                "home_pitcher": "德保拉",
                "away_pitcher": "王維中",
                "status": "scheduled",
            },
            {
                "id": f"{today.replace('-', '')}_2",
                "date": today,
                "game_sno": 2,
                "home_team": "AJL",
                "home_team_name": "樂天桃猿",
                "away_team": "ADD",
                "away_team_name": "統一7-ELEVEn獅",
                "venue": "桃園棒球場",
                "game_time": "18:35",
                "home_pitcher": "尼乂乂",
                "away_pitcher": "布雷乂",
                "status": "scheduled",
            },
            {
                "id": f"{today.replace('-', '')}_3",
                "date": today,
                "game_sno": 3,
                "home_team": "AEO",
                "home_team_name": "富邦悍將",
                "away_team": "AKP",
                "away_team_name": "台鋼雄鷹",
                "venue": "新莊棒球場",
                "game_time": "18:35",
                "home_pitcher": "邦乂乂",
                "away_pitcher": "鋼乂乂",
                "status": "scheduled",
            },
        ]

        standings = {
            "ACN": {"name": "中信兄弟", "wins": 2, "losses": 10, "win_rate": 0.167, "avg_runs": 3.2, "team_era": "5.80", "recent_10": "2勝8敗"},
            "AAA": {"name": "味全龍", "wins": 8, "losses": 4, "win_rate": 0.667, "avg_runs": 5.1, "team_era": "3.21", "recent_10": "8勝2敗"},
            "AJL": {"name": "樂天桃猿", "wins": 6, "losses": 5, "win_rate": 0.545, "avg_runs": 4.8, "team_era": "3.95", "recent_10": "6勝4敗"},
            "ADD": {"name": "統一7-ELEVEn獅", "wins": 7, "losses": 5, "win_rate": 0.583, "avg_runs": 4.5, "team_era": "3.60", "recent_10": "7勝3敗"},
            "AEO": {"name": "富邦悍將", "wins": 5, "losses": 6, "win_rate": 0.455, "avg_runs": 3.9, "team_era": "4.20", "recent_10": "5勝5敗"},
            "AKP": {"name": "台鋼雄鷹", "wins": 4, "losses": 8, "win_rate": 0.333, "avg_runs": 3.5, "team_era": "4.80", "recent_10": "3勝7敗"},
        }

        # AI 生成賠率
        odds_map = generate_odds_for_games(test_games, standings)

        # 存入 MongoDB
        for game in test_games:
            gid = game["id"]
            game["odds"] = odds_map.get(gid, {"markets": []})
            game_repo.upsert_game(gid, game)

        return {
            "status": "ok",
            "games": [g["id"] for g in test_games],
            "markets_per_game": {g["id"]: len(odds_map.get(g["id"], {}).get("markets", [])) for g in test_games},
        }

    @app.post("/dev/settle-test-game")
    async def settle_test_game(home_score: int = 3, away_score: int = 5):
        """Manually settle the test game."""
        from app.db import game_repo
        from app.betting.settlement import settle_game

        today = date.today().isoformat()
        game_id = f"{today.replace('-', '')}_1"

        game_repo.update_game_result(game_id, home_score, away_score, {
            "first_inning_runs": 1,
            "total_hr": 2,
        })

        result = settle_game(game_id)
        return {"status": "ok", **result}
