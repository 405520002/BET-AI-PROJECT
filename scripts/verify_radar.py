"""Verify radar chart generation for a CPBL player.

Usage:
    python scripts/verify_radar.py <acnt>

Example:
    python scripts/verify_radar.py 0000006888
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.scraper.cpbl_player_stats import fetch_player_advanced_stats
from app.services.radar_chart import render_player_radar

_PNG_MAGIC = b'\x89PNG\r\n\x1a\n'


async def main(acnt: str) -> None:
    stats = await fetch_player_advanced_stats(acnt)
    if stats is None:
        print(f"ERROR: Could not fetch stats for player {acnt}")
        sys.exit(1)

    png_bytes = render_player_radar(stats, stats["axes"])

    out_path = Path(f"/tmp/radar_{acnt}.png")
    out_path.write_bytes(png_bytes)

    size = len(png_bytes)
    assert size > 10000, f"File too small: {size} bytes (expected > 10000)"
    assert png_bytes[:8] == _PNG_MAGIC, f"Not a valid PNG: magic bytes {png_bytes[:8]!r}"

    print(f"OK {out_path} {size}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/verify_radar.py <acnt>")
        sys.exit(1)

    asyncio.run(main(sys.argv[1]))
