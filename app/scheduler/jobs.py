"""Scheduled jobs for daily scraping and settlement."""
import logging
from datetime import date, timedelta

from app.scraper import cpbl_schedule, cpbl_results, cpbl_standings
from app.betting.odds_engine import generate_odds_for_games
from app.betting.settlement import settle_all_games_for_date
from app.firebase import game_repo

logger = logging.getLogger(__name__)


async def scrape_and_generate_odds():
    """Morning job: scrape today's schedule, generate odds, store in Firebase.
    Triggered at 08:00 or via /cron/scrape-schedule.
    """
    today = date.today().isoformat()
    logger.info(f"[CRON] Scraping schedule for {today}")

    # 1. Scrape standings
    standings = await cpbl_standings.scrape_standings()
    logger.info(f"Got standings for {len(standings)} teams")

    # 2. Scrape today's schedule
    games = await cpbl_schedule.scrape_today_schedule()
    logger.info(f"Found {len(games)} games for today")

    if not games:
        logger.info("No games today")
        return {"games": 0}

    # 3. Generate odds via Claude API
    odds_map = generate_odds_for_games(games, standings)

    # 4. Store games with odds in Firebase
    for game in games:
        gid = game.get("id", "")
        game_odds = odds_map.get(gid, {"markets": []})
        game["odds"] = game_odds
        game_repo.upsert_game(gid, game)
        logger.info(f"Stored game {gid} with {len(game_odds.get('markets', []))} markets")

    return {"games": len(games)}


async def scrape_results():
    """Evening job: scrape today's game results.
    Triggered at 22:30 or via /cron/scrape-results.
    """
    today = date.today().isoformat()
    logger.info(f"[CRON] Scraping results for {today}")

    # Get today's games from Firebase
    games = game_repo.get_games_by_date(today)
    if not games:
        logger.info("No games to check results for")
        return {"updated": 0}

    # Scrape results
    results = await cpbl_results.scrape_game_results(today)
    logger.info(f"Got {len(results)} results")

    updated = 0
    for result in results:
        sno = result.get("game_sno")
        # Match by game_sno
        matching_game = None
        for g in games:
            if g.get("game_sno") == sno:
                matching_game = g
                break

        if not matching_game:
            continue

        if result["status"] == "postponed":
            game_repo.update_game_status(matching_game["id"], "postponed")
        elif result["status"] == "final":
            game_repo.update_game_result(
                matching_game["id"],
                result["home_score"],
                result["away_score"],
                result.get("result_details"),
            )
        updated += 1

    return {"updated": updated}


async def settle_today():
    """Midnight job: settle today's completed games.
    Triggered at 00:00 or via /cron/settle.
    """
    # Settle yesterday's games (since it's now past midnight)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    logger.info(f"[CRON] Settling games for {yesterday}")

    result = settle_all_games_for_date(yesterday)
    logger.info(f"Settlement result: {result}")
    return result
