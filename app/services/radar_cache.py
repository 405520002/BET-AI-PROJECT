"""Bounded TTL cache for rendered radar PNG bytes."""
from __future__ import annotations

import time
from collections import OrderedDict

from app.services.radar_chart import render_player_radar

TTL_SECONDS = 1800
MAX_ENTRIES = 64  # bound cache to prevent memory growth from probing

# Bounded LRU: acnt -> (timestamp, png_bytes)
_RADAR_CACHE: "OrderedDict[str, tuple[float, bytes]]" = OrderedDict()


def get_or_render(player: dict, axes: list) -> bytes:
    acnt = player["acnt"]
    now = time.monotonic()
    cached = _RADAR_CACHE.get(acnt)
    if cached and (now - cached[0]) < TTL_SECONDS:
        _RADAR_CACHE.move_to_end(acnt)
        return cached[1]
    png = render_player_radar(player, axes)
    _RADAR_CACHE[acnt] = (now, png)
    _RADAR_CACHE.move_to_end(acnt)
    while len(_RADAR_CACHE) > MAX_ENTRIES:
        _RADAR_CACHE.popitem(last=False)
    return png
