"""Scheduled jobs for daily scraping and settlement.

Daily flow:
  08:00  morning_job()
         1. Clean up 30-day old data
         2. Scrape today's schedule
         3. AI generate odds
         4. Store games + odds in MongoDB

  12:00  midday_update()
         1. Re-scrape today's schedule (update pitcher/venue/time changes)
         2. Update game info but keep existing odds

  00:00  midnight_settle()
         1. Scrape today's game results
         2. Settle all bets
"""
import logging
from datetime import date, timedelta

from app.scraper import cpbl_schedule, cpbl_results, cpbl_standings
from app.betting.odds_engine import generate_odds_for_games
from app.betting.settlement import settle_all_games_for_date
from app.db import game_repo
from app.db.client import get_db

logger = logging.getLogger(__name__)


async def morning_job():
    """08:00 - Scrape schedule + AI generate odds."""
    today_obj = date.today()
    today_str = today_obj.isoformat()
    logger.info(f"[08:00] Starting morning job for {today_str}")

    # Clean up old data
    _cleanup_old_data()

    db = get_db()

    # Check if we have recent results in DB
    recent_count = db["games"].count_documents({
        "status": {"$in": ["final", "postponed"]},
        "date": {"$gte": (today_obj - timedelta(days=10)).isoformat()},
    })
    logger.info(f"[08:00] Recent finished games in DB: {recent_count}")

    # If less than 5 recent results, backfill from CPBL
    if recent_count < 5:
        logger.info("[08:00] Backfilling recent results...")
        await _backfill_recent_results(today_obj)

    # Scrape standings
    standings = await cpbl_standings.scrape_standings()

    # Cache standings in DB for LINE bot
    db["cache"].update_one(
        {"_id": "standings"},
        {"$set": {"data": standings, "updated_at": today_str}},
        upsert=True,
    )

    # Scrape this month's schedule (and next month if near end of month)
    import time, random
    all_games = []
    all_games += await cpbl_schedule.scrape_schedule_for_date(today_obj.year, today_obj.month)
    if today_obj.day >= 25:
        time.sleep(random.uniform(1, 2))
        next_month = today_obj.replace(day=28) + timedelta(days=4)
        all_games += await cpbl_schedule.scrape_schedule_for_date(next_month.year, next_month.month)

    # Store finished games
    finished = [g for g in all_games if g.get("status") in ("final", "postponed")]
    for game in finished:
        game_repo.upsert_game(game["id"], game)
    logger.info(f"[08:00] Stored {len(finished)} finished games")

    # Cache upcoming 7-day schedule
    seven_days_later = (today_obj + timedelta(days=7)).isoformat()
    upcoming = [g for g in all_games if g.get("status") == "scheduled" and today_str <= g.get("date", "") <= seven_days_later]
    games_by_date = {}
    for g in upcoming:
        d = g.get("date", "")
        if d not in games_by_date:
            games_by_date[d] = []
        games_by_date[d].append({
            "away_team_name": g.get("away_team_name", ""),
            "home_team_name": g.get("home_team_name", ""),
            "venue": g.get("venue", ""),
            "game_time": g.get("game_time", ""),
        })
    db["cache"].update_one(
        {"_id": "upcoming_schedule"},
        {"$set": {"data": games_by_date, "updated_at": today_str}},
        upsert=True,
    )
    logger.info(f"[08:00] Cached {len(upcoming)} upcoming games for {len(games_by_date)} days")

    # Store today's scheduled games with AI odds
    scheduled = [g for g in all_games if g.get("status") == "scheduled" and g.get("date") == today_str]
    logger.info(f"[08:00] {len(scheduled)} scheduled games today")

    if not scheduled:
        return {"games": 0, "finished_stored": len(finished)}

    odds_map = generate_odds_for_games(scheduled, standings)

    for game in scheduled:
        gid = game.get("id", "")
        game["odds"] = odds_map.get(gid, {"markets": []})
        game_repo.upsert_game(gid, game)
        logger.info(f"[08:00] {game.get('away_team_name','')} vs {game.get('home_team_name','')}: {len(game['odds'].get('markets',[]))} markets")

    return {"games": len(scheduled), "finished_stored": len(finished)}


async def midday_update():
    """12:00 - Re-scrape schedule to update game info (pitchers/venue/time), keep existing odds."""
    today = date.today().isoformat()
    logger.info(f"[12:00] Updating game info for {today}")

    games = await cpbl_schedule.scrape_today_schedule()
    scheduled = [g for g in games if g.get("status") == "scheduled"]
    updated = 0

    for game in scheduled:
        gid = game.get("id", "")
        existing = game_repo.get_game(gid)

        if existing:
            # Keep existing odds, only update game info
            game["odds"] = existing.get("odds", {"markets": []})
            game_repo.upsert_game(gid, game)
            logger.info(f"[12:00] Updated info: {game.get('away_team_name','')} vs {game.get('home_team_name','')}")
        else:
            # New game that wasn't in 08:00 scrape, use fallback odds
            from app.betting.odds_fallback import generate_fallback_odds
            standings = await cpbl_standings.scrape_standings()
            game["odds"] = generate_fallback_odds(game, standings)
            game_repo.upsert_game(gid, game)
            logger.info(f"[12:00] New game added: {gid}")
        updated += 1

    return {"updated": updated}


async def midnight_settle():
    """00:00 - Scrape today's results + boxscores and settle all bets."""
    from app.scraper.cpbl_boxscore import scrape_boxscore
    import time
    import random

    today = date.today().isoformat()
    logger.info(f"[00:00] Scraping results and settling for {today}")

    # Step 1: Scrape basic results (updates game status to final/postponed)
    results_updated = await _scrape_and_update_results(today)
    logger.info(f"[00:00] Updated {results_updated} game results")

    # Step 2: Scrape boxscores for completed games
    games = game_repo.get_games_by_date(today)
    final_games = [g for g in games if g.get("status") == "final"]
    boxscores = {}

    for game in final_games:
        game_sno = game.get("game_sno")
        if not game_sno:
            continue
        try:
            time.sleep(random.uniform(1, 2))
            bs = await scrape_boxscore(game_sno)
            if bs:
                boxscores[game["id"]] = bs
                logger.info(f"[00:00] Boxscore {game['id']}: {bs.get('away_score',0)}-{bs.get('home_score',0)}, HR:{bs.get('total_hr',0)}, 1st:{bs.get('first_inning_runs',0)}")
        except Exception as e:
            logger.warning(f"[00:00] Boxscore failed for {game['id']}: {e}")

    logger.info(f"[00:00] Got {len(boxscores)} boxscores")

    # Step 3: Settle all bets (with boxscores for custom bets)
    settle_result = settle_all_games_for_date(today, boxscores)
    logger.info(f"[00:00] Settlement: {settle_result}")

    return {"results_updated": results_updated, "boxscores": len(boxscores), **settle_result}


# === Helpers ===

async def _scrape_and_update_results(date_str: str) -> int:
    """Scrape game results and update MongoDB."""
    games = game_repo.get_games_by_date(date_str)
    if not games:
        return 0

    pending_games = [g for g in games if g.get("status") not in ("final", "postponed")]
    if not pending_games:
        return 0

    results = await cpbl_results.scrape_game_results(date_str)
    updated = 0

    for result in results:
        sno = result.get("game_sno")
        matching_game = None
        for g in pending_games:
            if g.get("game_sno") == sno:
                matching_game = g
                break

        if not matching_game:
            continue

        if result["status"] == "postponed":
            game_repo.update_game_status(matching_game["id"], "postponed")
            logger.info(f"Game {matching_game['id']} postponed")
        elif result["status"] == "final":
            game_repo.update_game_result(
                matching_game["id"],
                result["home_score"],
                result["away_score"],
                result.get("result_details"),
            )
            logger.info(f"Game {matching_game['id']} final: {result['away_score']}-{result['home_score']}")
        updated += 1

    return updated


def _cleanup_old_data():
    """Remove games, bets, and transactions older than 30 days."""
    from datetime import datetime
    cutoff = datetime.now() - timedelta(days=30)
    cutoff_date_str = (date.today() - timedelta(days=30)).isoformat()
    db = get_db()

    r1 = db["games"].delete_many({"date": {"$lt": cutoff_date_str}})
    r2 = db["bets"].delete_many({"created_at": {"$lt": cutoff}})
    r3 = db["transactions"].delete_many({"created_at": {"$lt": cutoff}})

    total = r1.deleted_count + r2.deleted_count + r3.deleted_count
    if total > 0:
        logger.info(f"[CLEANUP] Deleted {r1.deleted_count} games, {r2.deleted_count} bets, {r3.deleted_count} tx")


async def _backfill_recent_results(today_obj):
    """Backfill recent finished games from CPBL when DB is empty/sparse.
    Scrapes current month and previous month to get ~10 days of results.
    """
    import time
    import random

    stored = 0
    months_to_scrape = [(today_obj.year, today_obj.month)]

    # Also scrape previous month if we're early in the month
    if today_obj.day <= 10:
        prev = today_obj.replace(day=1) - timedelta(days=1)
        months_to_scrape.append((prev.year, prev.month))

    for year, month in months_to_scrape:
        logger.info(f"[BACKFILL] Scraping {year}-{month:02d}")
        try:
            games = await cpbl_schedule.scrape_schedule_for_date(year, month)
            finished = [g for g in games if g.get("status") in ("final", "postponed")]
            for game in finished:
                game_repo.upsert_game(game["id"], game)
                stored += 1
            logger.info(f"[BACKFILL] {year}-{month:02d}: {len(finished)} finished games stored")
            # Random delay between months
            time.sleep(random.uniform(1, 3))
        except Exception as e:
            logger.error(f"[BACKFILL] Failed for {year}-{month:02d}: {e}")

    logger.info(f"[BACKFILL] Total stored: {stored} games")
