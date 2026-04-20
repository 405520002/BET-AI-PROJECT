"""Re-scrape boxscores for recent games and save under games.boxscore.

Usage:
    python scripts/backfill_boxscores.py              # last 7 days
    python scripts/backfill_boxscores.py --days 14    # last N days
    python scripts/backfill_boxscores.py --date 2026-04-15  # single date
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db import game_repo
from app.db.client import get_db
from app.scraper.cpbl_boxscore import scrape_boxscore


async def backfill_date(date_str: str) -> tuple[int, int]:
    db = get_db()
    games = list(db["games"].find({"date": date_str, "status": "final"}))
    print(f"[{date_str}] {len(games)} final games")

    ok = 0
    for g in games:
        gid = g["_id"]
        sno = g.get("game_sno")
        if not sno:
            print(f"  skip {gid}: no game_sno")
            continue
        try:
            bs = await scrape_boxscore(sno)
            if bs:
                game_repo.upsert_game(gid, {"boxscore": bs})
                ok += 1
                print(f"  ✓ {gid} {bs.get('away_team_name','')} {bs.get('away_score')}-{bs.get('home_score')} {bs.get('home_team_name','')}  batters={len(bs.get('batting_summary',[]))}  pitchers={len(bs.get('pitchers',[]))}")
            else:
                print(f"  ✗ {gid}: scrape returned None")
            # CPBL rate-limit politeness
            await asyncio.sleep(random.uniform(1.0, 2.0))
        except Exception as e:
            print(f"  ✗ {gid}: {e}")

    return ok, len(games)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--date", help="single date YYYY-MM-DD")
    args = ap.parse_args()

    if args.date:
        dates = [args.date]
    else:
        today = date.today()
        dates = [(today - timedelta(days=i)).isoformat() for i in range(1, args.days + 1)]

    total_ok = 0
    total = 0
    for d in dates:
        ok, n = await backfill_date(d)
        total_ok += ok
        total += n
    print(f"\nDone: {total_ok}/{total} boxscores saved")


if __name__ == "__main__":
    asyncio.run(main())
