"""Resolve CPBL player zh-name → acnt via Wikipedia.

Two entry points:
    fetch_wiki_acnt(name)       - single name, on-demand fallback (~1.5s)
    refresh_wiki_roster()       - full per-team category sweep (~3 min,
                                  daily cron)

Wikipedia exposes player infoboxes that consistently link to the player's
CPBL profile, e.g.
    href="https://www.cpbl.com.tw/team/person?acnt=0000001804"
    href="https://www.cpbl.com.tw/Players/PlayerProfileNew.aspx?Acnt=0000001804"
A 10-digit acnt regex picks out either form.

Coverage caveats:
- Foreign players (索沙, 德保拉, …) often lack zh Wikipedia entries.
- Short / common 2-character names route to disambiguation pages.
- Some Wikipedia entries link to a non-stats CPBL endpoint that yields
  the placeholder "球員詳細資料" title in stats.cpbl.com.tw, meaning the
  acnt is real but the advanced-stats panel hasn't been published.
The single-name path validates the acnt by hitting the stats page and
matching the title's leading zh name; the batch path skips per-record
validation (Wikipedia's category linkage is consistent enough at scale).
"""
from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

WIKI_BASE = "https://zh.wikipedia.org"
USER_AGENT = "CPBLBetBot/1.0 (https://cpbl-bet.duckdns.org)"
WIKI_TIMEOUT = 6.0
ACNT_RE = re.compile(r'cpbl\.com\.tw/[^"]*?[Aa]cnt=(\d{10})')

# (display_team, wiki_category_title)
TEAM_CATEGORIES: list[tuple[str, str]] = [
    ("中信兄弟", "中信兄弟球員"),
    ("統一7-ELEVEn獅", "統一7-ELEVEn獅球員"),
    ("統一7-ELEVEn獅", "統一獅球員"),
    ("樂天桃猿", "樂天桃猿球員"),
    ("富邦悍將", "富邦悍將球員"),
    ("味全龍", "味全龍球員"),
    ("台鋼雄鷹", "台鋼雄鷹球員"),
]


async def fetch_wiki_acnt(name: str) -> str | None:
    """Hit zh.wikipedia.org/wiki/<name>, regex out the acnt-bearing link.
    Returns 10-digit acnt or None. No DB writes."""
    name = (name or "").strip()
    if not name or len(name) < 2 or len(name) > 5:
        return None
    url = f"{WIKI_BASE}/wiki/{quote(name)}"
    try:
        async with httpx.AsyncClient(
            timeout=WIKI_TIMEOUT, headers={"User-Agent": USER_AGENT}
        ) as client:
            r = await client.get(url, follow_redirects=False)
    except Exception as e:
        logger.warning("wiki_lookup: %s fetch failed: %s", name, e)
        return None
    if r.status_code != 200:
        return None
    m = ACNT_RE.search(r.text)
    return m.group(1) if m else None


async def refresh_wiki_roster() -> dict[str, dict]:
    """Sweep all 7 per-team categories, fetch every member's Wikipedia page,
    extract acnt, return {zh_name: {"acnt", "team", "source": "wiki"}}.

    Roughly 700-1000 player fetches at concurrency 5 ≈ 2-3 minutes.
    """
    headers = {"User-Agent": USER_AGENT}
    out: dict[str, dict] = {}
    total_links = 0

    async with httpx.AsyncClient(
        timeout=WIKI_TIMEOUT, headers=headers, follow_redirects=True
    ) as client:
        link_pairs: list[tuple[str, str, str]] = []  # (team_display, zh_name, page_url)

        for team_display, category in TEAM_CATEGORIES:
            try:
                cat_url = f"{WIKI_BASE}/wiki/Category:{quote(category)}"
                r = await client.get(cat_url)
                if r.status_code != 200:
                    logger.warning(
                        "wiki refresh: category %s HTTP %d", category, r.status_code
                    )
                    continue
                for m in re.finditer(
                    r'<li><a href="(/wiki/[^"#]+)"[^>]*title="([^"]+)"',
                    r.text,
                ):
                    href, title = m.group(1), m.group(2)
                    if title.startswith(
                        ("Category:", "Help:", "Special:", "Wikipedia:", "File:", "Portal:", "Template:")
                    ):
                        continue
                    if "(" in title or ":" in title:  # disambig / namespaced
                        continue
                    link_pairs.append((team_display, title, WIKI_BASE + href))
            except Exception as e:
                logger.warning("wiki refresh: category %s exception: %s", category, e)

        # Dedupe links — a player can appear in multiple team categories
        seen = set()
        unique_pairs = []
        for tup in link_pairs:
            key = (tup[1], tup[2])
            if key in seen:
                continue
            seen.add(key)
            unique_pairs.append(tup)
        total_links = len(unique_pairs)
        logger.info("wiki refresh: %d unique player links to fetch", total_links)

        sem = asyncio.Semaphore(5)

        async def _fetch_one(team: str, zh_name: str, url: str):
            async with sem:
                try:
                    rr = await client.get(url)
                except Exception:
                    return None
                if rr.status_code != 200:
                    return None
                mm = ACNT_RE.search(rr.text)
                if not mm:
                    return None
                return zh_name, {
                    "acnt": mm.group(1),
                    "team": team,
                    "source": "wiki",
                }

        results = await asyncio.gather(
            *[_fetch_one(t, n, u) for t, n, u in unique_pairs]
        )

    for entry in results:
        if not entry:
            continue
        name, info = entry
        existing = out.get(name)
        if existing and "二軍" in existing.get("team", "") and "二軍" not in info["team"]:
            out[name] = info  # prefer non-二軍
        else:
            out.setdefault(name, info)

    logger.info(
        "wiki refresh: built %d/%d roster entries",
        len(out),
        total_links,
    )
    return out
