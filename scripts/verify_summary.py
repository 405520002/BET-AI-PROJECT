"""Verify generate_player_summary end-to-end.

Usage:
    .venv/bin/python scripts/verify_summary.py <acnt> [query]

Example:
    .venv/bin/python scripts/verify_summary.py 0000006888 "上壘率為什麼比去年低"
"""
from __future__ import annotations

import asyncio
import os
import sys

# Ensure project root is on sys.path when run directly from scripts/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.scraper.cpbl_player_stats import fetch_player_advanced_stats
from app.services.player_summary_ai import generate_player_summary


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: verify_summary.py <acnt> [query]", file=sys.stderr)
        sys.exit(1)

    acnt = sys.argv[1]
    query = sys.argv[2] if len(sys.argv) >= 3 else ""

    stats = asyncio.run(fetch_player_advanced_stats(acnt))
    if stats is None:
        print(f"ERROR: fetch_player_advanced_stats returned None for acnt={acnt}", file=sys.stderr)
        sys.exit(1)

    response = generate_player_summary(stats, stats["axes"], query)
    print(response)

    assert response, "Response must be non-empty"
    assert not response.startswith("[AI 摘要產生失敗"), (
        f"Gemini call failed: {response}"
    )
    assert 50 <= len(response) <= 800, (
        f"Response length {len(response)} outside [50, 800]"
    )

    print(f"\n[OK] Response length: {len(response)} chars")


if __name__ == "__main__":
    main()
