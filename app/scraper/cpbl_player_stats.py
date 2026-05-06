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

    return {
        "acnt": acnt,
        "name_zh": name_zh,
        "uniform_no": uniform_no,
        "team": team,
        "position_zh": position_zh,
        "role": role,
        "page_url": page_url,
        "axes": axes,
        "scraped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
