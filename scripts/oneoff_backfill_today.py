"""Backfill today's scheduled games into db.games + cache via /box/getlive bypass.

Usage (inside app container):
    python /app/oneoff_backfill_today.py YYYY-MM-DD seed_sno
"""
import asyncio, json, re, sys
from app.scraper.http_client import get_cpbl_session, _ajax_headers, _browser_headers
from app.scraper.cpbl_standings import TEAM_NAME_NORMALIZE
from app.db import game_repo
from app.db.client import get_db

BASE = "https://www.cpbl.com.tw"


async def main():
    if len(sys.argv) != 3:
        print("usage: oneoff_backfill_today.py YYYY-MM-DD seed_sno")
        sys.exit(2)
    target_date = sys.argv[1]
    seed_sno = int(sys.argv[2])
    year = int(target_date.split("-")[0])

    client, _ = await get_cpbl_session(BASE)
    try:
        page_url = f"{BASE}/box/index?gameSno={seed_sno}&year={year}&kindCode=A"
        page_r = await client.get(page_url, headers=_browser_headers(referer=BASE + "/"))
        m = re.search(r"RequestVerificationToken:\s*'([A-Za-z0-9_\-:]+)'", page_r.text)
        if not m:
            m = re.search(r'__RequestVerificationToken.*?value="([^"]+)"', page_r.text)
        token = m.group(1)
        ajax_h = _ajax_headers(page_url, token)
        api_r = await client.post(
            f"{BASE}/box/getlive",
            data={"gameSno": str(seed_sno), "year": str(year), "kindCode": "A"},
            headers=ajax_h,
        )
        d = api_r.json()
        games = json.loads(d["GameDetailJson"])
    finally:
        await client.aclose()

    print(f"Got {len(games)} games from /box/getlive")

    today_games_for_cache = []
    for g in games:
        gd = (g.get("GameDateTimeS") or "")[:10]
        if gd != target_date:
            continue
        sno = g["GameSno"]
        away = g.get("VisitingTeamName", "")
        home = g.get("HomeTeamName", "")
        gid = f"{target_date.replace('-', '')}_{sno}"

        s_int = g.get("GameStatus")
        chi = g.get("GameStatusChi", "")
        if s_int == 3 or "比賽結束" in chi:
            status = "final"
        elif "延" in chi or "保留" in chi or "取消" in chi:
            status = "postponed"
        else:
            status = "scheduled"

        doc = {
            "id": gid,
            "date": target_date,
            "game_sno": sno,
            "home_team": TEAM_NAME_NORMALIZE.get(home, ""),
            "home_team_name": home,
            "away_team": TEAM_NAME_NORMALIZE.get(away, ""),
            "away_team_name": away,
            "venue": g.get("FieldAbbe", ""),
            "game_time": (g.get("GameDateTimeS") or "")[11:16],
            "home_pitcher": g.get("HomePitcherName") or "",
            "away_pitcher": g.get("VisitingPitcherName") or "",
            "home_logo": "",
            "away_logo": "",
            "status": status,
        }
        if status == "final":
            doc["home_score"] = g.get("HomeTotalScore", 0)
            doc["away_score"] = g.get("VisitingTotalScore", 0)
        game_repo.upsert_game(gid, doc)
        print(f"  upserted sno={sno} {away}@{home} venue={doc['venue']} time={doc['game_time']} status={status}")

        today_games_for_cache.append({
            "away_team_name": away,
            "home_team_name": home,
            "venue": doc["venue"],
            "game_time": doc["game_time"],
        })

    db = get_db()
    cache = db["cache"].find_one({"_id": "upcoming_schedule"}) or {"data": {}}
    cache_data = cache.get("data", {})
    cache_data[target_date] = today_games_for_cache
    db["cache"].update_one(
        {"_id": "upcoming_schedule"},
        {"$set": {"data": cache_data, "updated_at": target_date}},
        upsert=True,
    )
    print(f"Updated upcoming_schedule cache for {target_date}: {len(today_games_for_cache)} games")

if __name__ == "__main__":
    asyncio.run(main())
