"""Parse www.cpbl.com.tw/team?ClubNo=X HTML into [{name, acnt}].

Same regex/BeautifulSoup logic as scripts/scrape_player_names.py — factored
out here so /ingest/roster can reuse it on raw HTML POSTed by the iPhone
Shortcut from a TW IP (CPBL geo-blocks www.* from datacenter ASNs).
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup


_ACNT_HREF_RE = re.compile(r"team/person\?Acnt=", re.IGNORECASE)
_ACNT_VALUE_RE = re.compile(r"Acnt=(\w+)", re.IGNORECASE)


def parse_team_roster(html: str) -> list[dict]:
    """Return [{name, acnt}] from a CPBL team page. Empty list on parse miss
    (e.g. caller posted a 404 page or a different URL)."""
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[dict] = []
    for a in soup.find_all("a", href=_ACNT_HREF_RE):
        m = _ACNT_VALUE_RE.search(a.get("href", ""))
        name = a.get_text(strip=True)
        if m and name:
            out.append({"name": name, "acnt": m.group(1)})
    return out
