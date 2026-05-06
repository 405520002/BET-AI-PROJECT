import time
from app.services.radar_chart import render_player_radar

_RADAR_CACHE: dict[str, tuple[float, bytes]] = {}
TTL_SECONDS = 1800

def get_or_render(player: dict, axes: list) -> bytes:
    acnt = player["acnt"]
    now = time.time()
    cached = _RADAR_CACHE.get(acnt)
    if cached and (now - cached[0]) < TTL_SECONDS:
        return cached[1]
    png = render_player_radar(player, axes)
    _RADAR_CACHE[acnt] = (now, png)
    return png
