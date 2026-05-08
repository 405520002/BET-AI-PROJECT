"""Scrape a CPBL player's advanced-stats page from stats.cpbl.com.tw.

Public API:
    fetch_player_advanced_stats(acnt, bypass_cache=False) -> dict | None
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections import OrderedDict
from datetime import datetime, timezone
from urllib.parse import unquote

import httpx

logger = logging.getLogger(__name__)

_STATS_BASE = "https://stats.cpbl.com.tw"
_TTL = 600  # seconds
_CACHE_MAX = 128  # bound cache to prevent memory growth from probing
_ACNT_RE = re.compile(r"^\d{10}$")

# Bounded LRU cache: acnt -> (timestamp, result_dict)
_CACHE: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept-Encoding": "gzip, deflate",
}


async def fetch_player_advanced_stats(acnt: str, bypass_cache: bool = False) -> dict | None:
    """Fetch and parse advanced stats for a CPBL player.

    Args:
        acnt: The player account number (e.g. "0000006888").
        bypass_cache: If True, skip cache lookup and force a fresh fetch.

    Returns:
        Structured dict on success, None on failure (incl. malformed acnt).
    """
    if not _ACNT_RE.match(acnt):
        logger.warning("Rejected malformed acnt: %r", acnt[:32])
        return None

    now = time.monotonic()

    # Cache check (LRU: move-to-end on hit)
    if not bypass_cache and acnt in _CACHE:
        ts, cached = _CACHE[acnt]
        if now - ts < _TTL:
            _CACHE.move_to_end(acnt)
            logger.debug("Cache hit for player %s", acnt)
            return cached

    url = f"{_STATS_BASE}/players/{acnt}"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=_HEADERS)
    except Exception as exc:
        logger.warning("HTTP request failed for player %s: %s", acnt, exc)
        return None

    if resp.status_code != 200:
        logger.warning("Non-200 response for player %s: %s", acnt, resp.status_code)
        return None

    html = resp.text
    result = _parse_player_page(html, acnt, url)
    if result is None:
        return None

    _CACHE[acnt] = (time.monotonic(), result)
    _CACHE.move_to_end(acnt)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return result


def _parse_player_page(html: str, acnt: str, page_url: str) -> dict | None:
    """Parse the player stats page HTML and return a structured dict."""

    # --- Title parsing (required) ---
    title_m = re.search(
        r"<title>(.+?) #(\d+) - (.+?) \| 中華職棒進階數據</title>", html
    )
    if not title_m:
        logger.warning("Title regex did not match for player %s", acnt)
        return None

    name_zh = title_m.group(1).strip()
    uniform_no = title_m.group(2)
    team = title_m.group(3).strip()

    # --- Description meta (position) ---
    desc_m = re.search(r'<meta name="description" content="([^"]+)"', html)
    position_zh = "未知"
    if desc_m:
        parts = [s.strip() for s in desc_m.group(1).split(" | ")]
        if len(parts) >= 2:
            position_zh = parts[1]

    role = "pitcher" if position_zh == "投手" else "batter"

    # --- Axes: Primary — JSON-LD ---
    axes: list[dict] = []
    m = re.search(
        r'<script type="application/ld\+json">(.+?)</script>', html, flags=re.DOTALL
    )
    if m:
        try:
            ld = json.loads(m.group(1))
            props = ld.get("additionalProperty") or []
            if not props and "@graph" in ld:
                for node in ld["@graph"]:
                    props = node.get("additionalProperty") or props
                    if props:
                        break
            for p in props:
                if (
                    isinstance(p, dict)
                    and p.get("unitText") == "百分位 (PR)"
                    and p.get("name", "").endswith("中職百分位")
                ):
                    axes.append(
                        {
                            "name": p["name"].replace(" 中職百分位", "").strip(),
                            "value": int(p["value"]),
                        }
                    )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            logger.warning("JSON-LD parse error for player %s: %s", acnt, exc)

    # --- Axes: Fallback — regex on raw HTML ---
    if not axes:
        matches = re.findall(
            r'"@type":"PropertyValue","name":"([^"]+) 中職百分位","value":(\d+),'
            r'"minValue":0,"maxValue":100,"unitText":"百分位 \(PR\)"',
            html,
        )
        axes = [{"name": n, "value": int(v)} for n, v in matches]
        if axes:
            logger.debug("Used HTML regex fallback for axes on player %s", acnt)

    if len(axes) < 4:
        logger.warning(
            "Insufficient axes (%d < 4) for player %s (%s)", len(axes), acnt, name_zh
        )
        return None

    axes = _apply_role_view(role, axes)

    return {
        "acnt": acnt,
        "name_zh": name_zh,
        "uniform_no": uniform_no,
        "team": team,
        "position_zh": position_zh,
        "role": role,
        "page_url": page_url,
        "axes": axes,
        "profile": _parse_profile(html, team),
        "scraped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# Bio labels rendered on the page as <p>{label}</p><p>{value}</p>. The css class
# is emotion-generated (`css-7lrzga` / `css-nrf6mu`) and stable for a given
# build, but we match label-content rather than class hash so a stats.cpbl
# rebuild that re-rolls the hashes does not silently drop the whole bio.
_PROFILE_LABELS = {
    "身高(cm)": "height_cm",
    "體重(kg)": "weight_kg",
    "年齡": "age",
    "學歷": "school",
    "生日": "birthday",
    "原名": "original_name",
}

_THROW_BAT_CHAR_ZH = {"R": "右", "L": "左", "S": "雙"}


def _decode_throws_bats(code: str) -> str:
    """`投打習慣: R` / `RR` / `RL` → 右投右打 / 右投左打.

    The meta description on stats.cpbl.com.tw collapses to a single letter when
    throw and bat are the same hand (e.g. `R` for 右投右打). Two letters means
    throw-then-bat.
    """
    if len(code) == 1 and code in _THROW_BAT_CHAR_ZH:
        side = _THROW_BAT_CHAR_ZH[code]
        return f"{side}投{side}打"
    if len(code) == 2:
        t = _THROW_BAT_CHAR_ZH.get(code[0], code[0])
        b = _THROW_BAT_CHAR_ZH.get(code[1], code[1])
        return f"{t}投{b}打"
    return code


def _parse_profile(html: str, team: str) -> dict:
    """Extract bio + photo + team logo from the player page.

    Most fields come from <meta og:image> / <meta description> (cleanest, no
    Next.js image proxy), with the rest from the `<p>label</p><p>value</p>`
    pairs in the player-brief block. Returns empty dict on a fully unmatched
    page rather than failing — the caller still gets stats/axes.
    """
    profile: dict = {}

    m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
    if m:
        profile["photo_url"] = unquote(m.group(1))

    m = re.search(r"投打習慣:\s*([A-Za-z]+)", html)
    if m:
        code = m.group(1)
        profile["throws_bats_code"] = code
        profile["throws_bats"] = _decode_throws_bats(code)

    for label, key in _PROFILE_LABELS.items():
        m = re.search(
            r"<p[^>]*>" + re.escape(label) + r"</p>\s*<p[^>]*>([^<]+)</p>", html
        )
        if m:
            profile[key] = m.group(1).strip()

    # Team logo: prefer the canonical 6-team map shared with the schedule
    # ingest. Trying to alt="..."-match the page is unreliable: CPBL never
    # uploaded the Rakuten Monkeys / 台鋼雄鷹 logos to their file_pool, so
    # the page silently falls back to a 6-team banner / monochrome stub.
    if team:
        from app.scraper.line_today_schedule import (
            _TEAM_NAME_TO_CODE,
            _TEAM_LOGO_URL,
        )
        # Minor-league players carry "{team}二軍" in the title; treat them as
        # the parent club for logo purposes.
        team_key = team[:-2] if team.endswith("二軍") else team
        code = _TEAM_NAME_TO_CODE.get(team_key)
        if code and code in _TEAM_LOGO_URL:
            profile["team_logo_url"] = _TEAM_LOGO_URL[code]

    return profile


# Pitcher axis labels coming out of stats.cpbl.com.tw are batter-side stats
# (CPBL's advanced page only publishes opposing-batter axes for pitchers, not
# pitcher axes like ERA/WHIP). The bare label "打擊率" on a pitcher's chart is
# misleading — what's actually plotted is opponent BA against him. Prefix with
# "被" so the label reads "被打擊率" and invert the percentile so the radar
# stays "bigger polygon = better player" regardless of role.
_PITCHER_OPPOSING_RELABEL = {
    "加權上壘率": "被加權上壘率",
    "打擊率": "被打擊率",
    "長打率": "被長打率",
    "純長打率": "被純長打率",
    "上壘率": "被上壘率",
    "出色擊球數": "被出色擊球數",
    "出色擊球%": "被出色擊球%",
    "擊球初速 Avg": "被擊球初速 Avg",
    "擊球初速 Max": "被擊球初速 Max",
    "強擊球率": "被強擊球率",
}
# 三振%, 揮空%, 追打% measure batter behavior the pitcher *induces* — higher
# raw value already means a better pitcher, so don't invert. 保送% is the
# walk rate against him, lower raw is better → invert.
_PITCHER_INVERT_NAMES = set(_PITCHER_OPPOSING_RELABEL.keys()) | {"保送%"}


def _apply_role_view(role: str, axes: list[dict]) -> list[dict]:
    """Rewrite axes for the player's role.

    Batter: identity (CPBL's PR is already 'higher = better').
    Pitcher: relabel opposing-batter stats with "被" prefix and invert PR
             so the radar reads consistently across roles.
    """
    if role != "pitcher":
        return axes
    out: list[dict] = []
    for a in axes:
        name = a["name"]
        value = a["value"]
        new_name = _PITCHER_OPPOSING_RELABEL.get(name, name)
        if name in _PITCHER_INVERT_NAMES:
            value = 100 - value
        out.append({"name": new_name, "value": value})
    return out
