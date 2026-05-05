"""Verify fetch_player_advanced_stats for a given player acnt.

Usage:
    .venv/bin/python scripts/verify_player_stats.py <acnt>

Example:
    .venv/bin/python scripts/verify_player_stats.py 0000006888
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

# Ensure project root is on sys.path when run directly from scripts/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: verify_player_stats.py <acnt>")
        sys.exit(1)

    acnt = sys.argv[1]
    print(f"Fetching advanced stats for player acnt={acnt} ...")

    from app.scraper.cpbl_player_stats import fetch_player_advanced_stats

    result = asyncio.run(fetch_player_advanced_stats(acnt, bypass_cache=True))

    if result is None:
        print("ERROR: fetch_player_advanced_stats returned None")
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print()
    print(f"axes count : {len(result['axes'])}")
    print(f"name_zh    : {result['name_zh']}")
    print(f"role       : {result['role']}")

    assert len(result["axes"]) >= 4, f"Expected >=4 axes, got {len(result['axes'])}"
    assert result["name_zh"], "name_zh is empty"

    print()
    print("All assertions passed.")


if __name__ == "__main__":
    main()
