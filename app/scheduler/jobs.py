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
    today = date.today().isoformat()
    logger.info(f"[08:00] Starting morning job for {today}")

    # Clean up old data
    _cleanup_old_data()

    # Scrape standings + schedule
    standings = await cpbl_standings.scrape_standings()
    games = await cpbl_schedule.scrape_today_schedule()
    scheduled = [g for g in games if g.get("status") == "scheduled"]
    logger.info(f"[08:00] {len(scheduled)} scheduled games")

    if not scheduled:
        return {"games": 0}

    # AI generate odds
    odds_map = generate_odds_for_games(scheduled, standings)

    # Store games with odds
    for game in scheduled:
        gid = game.get("id", "")
        game["odds"] = odds_map.get(gid, {"markets": []})
        game_repo.upsert_game(gid, game)
        logger.info(f"[08:00] {game.get('away_team_name','')} vs {game.get('home_team_name','')}: {len(game['odds'].get('markets',[]))} markets")

    return {"games": len(scheduled)}


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
    """00:00 - Scrape today's results and settle all bets."""
    today = date.today().isoformat()
    logger.info(f"[00:00] Scraping results and settling for {today}")

    # Step 1: Scrape results
    results_updated = await _scrape_and_update_results(today)
    logger.info(f"[00:00] Updated {results_updated} game results")

    # Step 2: Settle all bets
    settle_result = settle_all_games_for_date(today)
    logger.info(f"[00:00] Settlement: {settle_result}")

    return {"results_updated": results_updated, **settle_result}


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
