"""One-off: settle 2026-04-24 by going around the blocked schedule API.

The schedule scraper (/schedule/getgamedatas) is blocked from VM IP, so
midnight_settle's normal path fails to fetch yesterday's final games.
But /box/getlive (POST) IS reachable and returns the entire day's games
when called for any gameSno that belongs to that day.

This script:
  1. Fetches one /box/getlive (using a known sno in the target day's
     range) to get the full day's GameDetailJson.
  2. Upserts each game into db.games with status=final + scores.
  3. Runs scrape_boxscore on each sno to build the per-game boxscore dict.
  4. Calls settle_all_games_for_date with that boxscore dict.
  5. Calls _push_post_game_analysis to push LINE messages.

Usage (run inside the app container):
    python scripts/oneoff_settle_via_box.py 2026-04-24 56
where 56 is any known game_sno from that day (we know snos 56-58 are 04-24).
"""
import asyncio
import json
import sys
import logging
from datetime import datetime

import httpx

from app.db.client import get_db
from app.db import game_repo
from app.scraper.http_client import get_cpbl_session, _ajax_headers, _browser_headers
from app.scraper.cpbl_boxscore import scrape_boxscore
from app.betting.settlement import settle_all_games_for_date
from app.scheduler.jobs import _push_post_game_analysis


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("oneoff_settle")

BASE_URL = "https://www.cpbl.com.tw"


async def fetch_day_games_via_boxlive(seed_sno: int, year: int) -> list[dict]:
    """Use /box/getlive bypass to fetch all games of the day that seed_sno belongs to."""
    import re
    client, _ = await get_cpbl_session(BASE_URL)
    try:
        page_url = f"{BASE_URL}/box/index?gameSno={seed_sno}&year={year}&kindCode=A"
        page_r = await client.get(page_url, headers=_browser_headers(referer=BASE_URL + "/"))
        page_r.raise_for_status()

        match = re.search(r"RequestVerificationToken:\s*'([A-Za-z0-9_\-:]+)'", page_r.text)
        if not match:
            match = re.search(r'__RequestVerificationToken.*?value="([^"]+)"', page_r.text)
        token = match.group(1) if match else ""
        if not token:
            raise RuntimeError("could not find token on /box/index")

        ajax_h = _ajax_headers(page_url, token)
        api_r = await client.post(
            f"{BASE_URL}/box/getlive",
            data={"gameSno": str(seed_sno), "year": str(year), "kindCode": "A"},
            headers=ajax_h,
        )
        api_r.raise_for_status()
        d = api_r.json()
        if not d.get("Success"):
            raise RuntimeError(f"/box/getlive Success=false: {d}")
        return json.loads(d["GameDetailJson"])
    finally:
        await client.aclose()


def _team_code_from_name(name: str) -> str:
    from app.scraper.cpbl_standings import TEAM_NAME_NORMALIZE
    return TEAM_NAME_NORMALIZE.get(name, "")


async def main():
    if len(sys.argv) != 3:
        print("usage: oneoff_settle_via_box.py YYYY-MM-DD seed_sno", file=sys.stderr)
        sys.exit(2)

    target_date = sys.argv[1]
    seed_sno = int(sys.argv[2])
    year = int(target_date.split("-")[0])

    logger.info(f"=== Fetching games for {target_date} via /box/getlive (seed sno={seed_sno}) ===")
    raw_games = await fetch_day_games_via_boxlive(seed_sno, year)
    logger.info(f"Got {len(raw_games)} games from /box/getlive")

    # Filter to games on the target date
    day_games = [g for g in raw_games if (g.get("GameDateTimeS") or "")[:10] == target_date]
    logger.info(f"Filtered to {len(day_games)} games on {target_date}")
    if not day_games:
        logger.error("No games on target date — abort")
        sys.exit(1)

    # Upsert each into db.games with status=final + scores
    final_games = []
    for g in day_games:
        sno = g.get("GameSno")
        away_name = g.get("VisitingTeamName", "")
        home_name = g.get("HomeTeamName", "")
        status_chi = g.get("GameStatusChi", "")

        # Map GameStatus int → our string
        status_int = g.get("GameStatus")
        if status_int == 3 or "比賽結束" in status_chi:
            status = "final"
        elif "延" in status_chi or "保留" in status_chi or "取消" in status_chi:
            status = "postponed"
        else:
            logger.info(f"  sno={sno} not finished (status={status_chi}), skipping")
            continue

        game_id = f"{target_date.replace('-','')}_{sno}"
        game_doc = {
            "id": game_id,
            "date": target_date,
            "game_sno": sno,
            "home_team": _team_code_from_name(home_name),
            "home_team_name": home_name,
            "away_team": _team_code_from_name(away_name),
            "away_team_name": away_name,
            "venue": g.get("FieldAbbe", ""),
            "game_time": (g.get("GameDateTimeS") or "")[11:16],
            "home_score": g.get("HomeTotalScore", 0),
            "away_score": g.get("VisitingTotalScore", 0),
            "status": status,
        }
        game_repo.upsert_game(game_id, game_doc)
        final_games.append(game_doc)
        logger.info(f"  upserted sno={sno} {away_name}@{home_name} {game_doc['away_score']}-{game_doc['home_score']} status={status}")

    # Fetch boxscores for each final game
    logger.info(f"=== Fetching boxscores for {len(final_games)} games ===")
    boxscores = {}
    import asyncio as _asyncio
    import random
    for g in final_games:
        if g["status"] != "final":
            continue
        sno = g["game_sno"]
        try:
            bs = await scrape_boxscore(sno, year)
            if bs:
                boxscores[g["id"]] = bs
                game_repo.upsert_game(g["id"], {"boxscore": bs})
                logger.info(f"  boxscore sno={sno}: HR={bs.get('total_hr',0)}, 1st={bs.get('first_inning_runs',0)}")
            else:
                logger.warning(f"  boxscore sno={sno}: returned None")
        except Exception as e:
            logger.error(f"  boxscore sno={sno} failed: {e}")
        await _asyncio.sleep(random.uniform(1, 2))

    logger.info(f"=== Got {len(boxscores)} boxscores; running settlement ===")

    # Run settlement
    settle_result = settle_all_games_for_date(target_date, boxscores)
    logger.info(f"settle_all_games_for_date result: {settle_result}")

    # Push post-game analysis (LINE notifications)
    db = get_db()
    push_key = f"post_game_pushed_{target_date}"
    already_pushed = db["cache"].find_one({"_id": push_key})
    if boxscores and not already_pushed:
        logger.info("=== Pushing post-game analysis to LINE ===")
        _push_post_game_analysis(target_date, boxscores, final_games)
        db["cache"].update_one({"_id": push_key}, {"$set": {"pushed": True}}, upsert=True)
    else:
        logger.info(f"post-game push skipped (already_pushed={bool(already_pushed)}, boxscores={len(boxscores)})")

    print("\n=== DONE ===")
    print(f"games_processed: {settle_result.get('games_processed')}")
    print(f"total_settled: {settle_result.get('total_settled')}")
    print(f"total_payout: {settle_result.get('total_payout')}")


if __name__ == "__main__":
    asyncio.run(main())
