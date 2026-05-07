"""Render a player's PR axes as a radar PNG using only Pillow.

Public API:
    render_player_radar(player: dict, axes: list[dict]) -> bytes

Why Pillow-only: matplotlib + numpy add ~50MB and minutes of build time on
the e2-micro VM (numpy/matplotlib both compile C extensions). We only need
a fixed radar layout, so 150 lines of polygon math beats the dependency.
We supersample (render at 2x then downscale with LANCZOS) for smooth edges
without anti-aliasing primitives.
"""
from __future__ import annotations

import io
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_FONT_PATH = str(Path(__file__).parent / "fonts" / "NotoSansTC-Regular.otf")

# Final output size; we render at SCALE x this then downscale.
_OUT_SIZE = 800
_SCALE = 2
_W = _OUT_SIZE * _SCALE
_H = _OUT_SIZE * _SCALE

# Padding inside the canvas. Top has to clear title + subtitle AND the
# topmost axis label (which sits at frac 1.12 above the polygon north tip).
_PAD_TOP = 180 * _SCALE
_PAD_SIDE = 110 * _SCALE
_PAD_BOTTOM = 100 * _SCALE

_RING_VALUES = (25, 50, 75, 100)
_BG = (255, 255, 255)
_GRID = (200, 200, 200)
_GRID_OUTER = (140, 140, 140)
_LABEL = (60, 60, 60)
_TITLE = (30, 30, 30)

# Fill / stroke for the data polygon. Pitchers in red, batters in blue.
_COLOR_BATTER_LINE = (31, 119, 180, 255)
_COLOR_BATTER_FILL = (31, 119, 180, 90)
_COLOR_PITCHER_LINE = (214, 39, 40, 255)
_COLOR_PITCHER_FILL = (214, 39, 40, 90)


def render_player_radar(player: dict, axes: list[dict]) -> bytes:
    """Render a player's PR axes as a radar PNG.

    Args:
        player: Player info dict with keys: name_zh, uniform_no, team,
                position_zh, role.
        axes: List of dicts with 'name' (str) and 'value' (int 0-100).
              Length must be between 4 and 14 (caller's responsibility).

    Returns:
        PNG image bytes.
    """
    n = len(axes)
    values = [max(0, min(100, int(a["value"]))) for a in axes]
    names = [str(a["name"]) for a in axes]

    is_pitcher = player.get("role") == "pitcher"
    line_color = _COLOR_PITCHER_LINE if is_pitcher else _COLOR_BATTER_LINE
    fill_color = _COLOR_PITCHER_FILL if is_pitcher else _COLOR_BATTER_FILL

    # Plot area: a square inscribed inside the padded canvas, centered.
    plot_w = _W - 2 * _PAD_SIDE
    plot_h = _H - _PAD_TOP - _PAD_BOTTOM
    radius = min(plot_w, plot_h) // 2
    cx = _W // 2
    cy = _PAD_TOP + radius

    canvas = Image.new("RGB", (_W, _H), _BG)
    draw = ImageDraw.Draw(canvas, "RGBA")

    # angle 0 points up (north), then clockwise.
    def axis_xy(idx: int, frac: float) -> tuple[float, float]:
        theta = (-math.pi / 2) + (2 * math.pi * idx / n)
        r = radius * frac
        return cx + r * math.cos(theta), cy + r * math.sin(theta)

    # Concentric reference rings (regular polygons connecting axis endpoints).
    for ring in _RING_VALUES:
        frac = ring / 100
        pts = [axis_xy(i, frac) for i in range(n)]
        color = _GRID_OUTER if ring == 100 else _GRID
        draw.line(pts + [pts[0]], fill=color, width=max(1, _SCALE))

    # Radial spokes.
    for i in range(n):
        end = axis_xy(i, 1.0)
        draw.line([(cx, cy), end], fill=_GRID, width=max(1, _SCALE))

    # Data polygon.
    poly = [axis_xy(i, values[i] / 100) for i in range(n)]
    draw.polygon(poly, fill=fill_color, outline=line_color)
    # Re-stroke the outline thicker (polygon outline is 1px).
    draw.line(poly + [poly[0]], fill=line_color, width=3 * _SCALE)
    # Vertex dots.
    dot_r = 4 * _SCALE
    for x, y in poly:
        draw.ellipse(
            (x - dot_r, y - dot_r, x + dot_r, y + dot_r),
            fill=line_color,
        )

    # Ring value labels (on the rightward axis).
    ring_font = _load_font(13 * _SCALE)
    for ring in _RING_VALUES:
        x, y = cx + radius * (ring / 100), cy
        draw.text((x + 4 * _SCALE, y - 8 * _SCALE), str(ring), font=ring_font, fill=_LABEL)

    # Axis labels (slightly outside each axis tip).
    label_font = _load_font(18 * _SCALE)
    for i, name in enumerate(names):
        lx, ly = axis_xy(i, 1.12)
        bbox = draw.textbbox((0, 0), name, font=label_font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text((lx - tw / 2, ly - th / 2), name, font=label_font, fill=_LABEL)

    # Title.
    title_font = _load_font(26 * _SCALE)
    title = (
        f"{player.get('name_zh', '')} #{player.get('uniform_no', '')}"
        f" ({player.get('position_zh', '')}) — 中職百分位 PR"
    )
    bbox = draw.textbbox((0, 0), title, font=title_font)
    tw = bbox[2] - bbox[0]
    draw.text(((_W - tw) / 2, 30 * _SCALE), title, font=title_font, fill=_TITLE)

    # Subtitle (team / role).
    sub_font = _load_font(16 * _SCALE)
    role_zh = "投手" if is_pitcher else "野手"
    subtitle = f"{player.get('team', '')} · {role_zh}"
    bbox = draw.textbbox((0, 0), subtitle, font=sub_font)
    tw = bbox[2] - bbox[0]
    draw.text(((_W - tw) / 2, 70 * _SCALE), subtitle, font=sub_font, fill=_LABEL)

    # Downscale for smoothing.
    out = canvas.resize((_OUT_SIZE, _OUT_SIZE), Image.LANCZOS)

    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _load_font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(_FONT_PATH, size=size)
    except Exception:
        # Last-resort fallback. Won't render CJK correctly but won't crash.
        return ImageFont.load_default()
