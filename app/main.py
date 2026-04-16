"""FastAPI application entry point with LINE webhook and cron endpoints."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Header
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
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("CPBL Betting Bot starting up")
    yield
    logger.info("CPBL Betting Bot shutting down")


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
