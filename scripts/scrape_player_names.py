"""Scrape CPBL rosters (all 6 teams, EN+ZH) and rebuild app/scraper/player_names.json.

Must run from a TW IP (www.cpbl.com.tw blocks/404s most sub-pages for overseas requests).
Typical refresh cadence: whenever a new foreign pitcher signs (weekly/monthly).

    python scripts/scrape_player_names.py
"""
from __future__ import annotations

import json
import os
import re
import time

import httpx
from bs4 import BeautifulSoup

CLUBS = {
    "ACN": "中信兄弟",
    "ADD": "統一7-ELEVEn獅",
    "AJL": "樂天桃猿",
    "AEO": "富邦悍將",
    "AAA": "味全龍",
    "AKP": "台鋼雄鷹",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
}

OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "app", "scraper", "player_names.json")


def scrape_roster(base: str, club: str) -> dict[str, str]:
    """Return {acnt: name} from a team roster page."""
    with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as c:
        c.get(base + "/")
        r = c.get(f"{base}/team?ClubNo={club}", headers={"Referer": base + "/"})
        if r.status_code != 200:
            return {}
        soup = BeautifulSoup(r.text, "html.parser")
        d: dict[str, str] = {}
        for a in soup.find_all("a", href=re.compile(r"team/person\?Acnt=")):
            m = re.search(r"Acnt=(\w+)", a.get("href", ""))
            name = a.get_text(strip=True)
            if m and name:
                d[m.group(1)] = name
        return d


def main() -> None:
    # en.cpbl.com.tw is no longer reachable (HTTP 500); we keep the existing
    # English→Chinese mapping in player_names.json untouched. This script now
    # only refreshes the Chinese side and leaves stale English keys alone so
    # apply_chinese_names() in cpbl_schedule still translates legacy English
    # pitcher names found in older API responses or DB rows.
    mapping: dict[str, dict] = {}
    for club, club_name in CLUBS.items():
        print(f"-- {club} {club_name}")
        zh = scrape_roster("https://www.cpbl.com.tw", club)
        time.sleep(0.5)
        # Use Chinese name as both key and zh value so callers asking for a
        # Chinese name still get the canonical record.
        for acnt, zh_name in zh.items():
            mapping[zh_name] = {"zh": zh_name, "team": club_name, "acnt": acnt}
        print(f"   ZH={len(zh)}")

    out = {
        "updated_at": time.strftime("%Y-%m-%d"),
        "players": mapping,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nSaved {len(mapping)} players to {OUT_PATH}")


if __name__ == "__main__":
    main()
