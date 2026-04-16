"""Setup LINE Rich Menu for CPBL Betting Bot.
Run once: python scripts/setup_rich_menu.py
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PIL import Image, ImageDraw, ImageFont
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    MessagingApiBlob,
    RichMenuRequest,
    RichMenuSize,
    RichMenuArea,
    RichMenuBounds,
    MessageAction,
)

from app.config import settings

WIDTH = 2500
HEIGHT = 843
COLS = 3
ROWS = 2
CELL_W = WIDTH // COLS
CELL_H = HEIGHT // ROWS

MENU_ITEMS = [
    ("今日賽事", "今日賽事", "#2C3E50"),
    ("我的注單", "我的注單", "#34495E"),
    ("儲值",     "儲值",     "#D35400"),
    ("排行榜",   "排行榜",   "#8E44AD"),
    ("我的戰績", "我的戰績",  "#2471A3"),
    ("球隊戰績", "球隊戰績",  "#1A5276"),
]


def _draw_baseball(draw, cx, cy, r):
    """Draw a baseball icon."""
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline="white", width=4)
    # Stitching lines
    for angle_offset in [-30, 30]:
        points = []
        for t in range(-60, 61, 10):
            rad = math.radians(t + angle_offset)
            x = cx + r * 0.6 * math.cos(rad) + (r * 0.3 if angle_offset > 0 else -r * 0.3)
            y = cy + r * math.sin(rad)
            points.append((x, y))
        if len(points) > 1:
            draw.line(points, fill="white", width=3)


def _draw_ticket(draw, cx, cy, r):
    """Draw a ticket/document icon."""
    x0, y0 = cx - r * 0.7, cy - r
    x1, y1 = cx + r * 0.7, cy + r
    draw.rounded_rectangle([x0, y0, x1, y1], radius=10, outline="white", width=4)
    # Lines on ticket
    for i in range(3):
        ly = y0 + (y1 - y0) * (0.3 + i * 0.2)
        draw.line([x0 + 15, ly, x1 - 15, ly], fill="white", width=3)
    # Tear line
    ty = y0 + (y1 - y0) * 0.2
    for dx in range(int(x0 + 5), int(x1 - 5), 12):
        draw.line([dx, ty, dx + 5, ty], fill="white", width=2)


def _draw_coin(draw, cx, cy, r):
    """Draw a coin/money icon."""
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline="white", width=4)
    draw.ellipse([cx - r + 8, cy - r + 8, cx + r - 8, cy + r - 8], outline="white", width=2)
    # Dollar sign
    draw.text((cx - 10, cy - 22), "$", fill="white",
              font=ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 44))


def _draw_trophy(draw, cx, cy, r):
    """Draw a trophy icon."""
    # Cup body
    draw.rounded_rectangle([cx - r * 0.5, cy - r * 0.8, cx + r * 0.5, cy + r * 0.2],
                           radius=8, outline="white", width=4)
    # Handles
    draw.arc([cx - r * 0.9, cy - r * 0.6, cx - r * 0.3, cy + r * 0.1],
             start=90, end=270, fill="white", width=4)
    draw.arc([cx + r * 0.3, cy - r * 0.6, cx + r * 0.9, cy + r * 0.1],
             start=-90, end=90, fill="white", width=4)
    # Base
    draw.line([cx, cy + r * 0.2, cx, cy + r * 0.6], fill="white", width=4)
    draw.line([cx - r * 0.4, cy + r * 0.6, cx + r * 0.4, cy + r * 0.6], fill="white", width=4)
    draw.rounded_rectangle([cx - r * 0.5, cy + r * 0.6, cx + r * 0.5, cy + r * 0.85],
                           radius=5, outline="white", width=3)


def _draw_chart(draw, cx, cy, r):
    """Draw a bar chart icon."""
    base_y = cy + r * 0.8
    bar_w = r * 0.35
    gap = r * 0.15
    heights = [0.4, 0.8, 0.6, 1.0]
    start_x = cx - (len(heights) * (bar_w + gap) - gap) / 2

    for i, h in enumerate(heights):
        x0 = start_x + i * (bar_w + gap)
        y0 = base_y - r * 1.6 * h
        draw.rounded_rectangle([x0, y0, x0 + bar_w, base_y], radius=5, outline="white", width=3, fill=None)
    # Baseline
    draw.line([start_x - 5, base_y + 3, start_x + len(heights) * (bar_w + gap), base_y + 3],
              fill="white", width=3)


def _draw_standings(draw, cx, cy, r):
    """Draw a standings/ranking list icon."""
    # Three horizontal bars with rank numbers
    for i, (w_ratio, y_off) in enumerate([(0.9, -0.6), (0.7, 0), (0.5, 0.6)]):
        y = cy + r * y_off
        x0 = cx - r * w_ratio / 2
        x1 = cx + r * w_ratio / 2
        draw.rounded_rectangle([x0, y - 8, x1, y + 8], radius=5, outline="white", width=3)
        # Small circle for rank number
        draw.ellipse([x0 - 15, y - 10, x0 + 5, y + 10], fill="white")



ICON_DRAWERS = [
    _draw_baseball,
    _draw_ticket,
    _draw_coin,
    _draw_trophy,
    _draw_chart,
    _draw_standings,
]


def create_rich_menu_image() -> str:
    img = Image.new("RGB", (WIDTH, HEIGHT), "#1B2838")
    draw = ImageDraw.Draw(img)

    font_size = 46
    font = ImageFont.load_default()
    for fp in [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
    ]:
        try:
            font = ImageFont.truetype(fp, font_size)
            print(f"Using font: {fp}")
            break
        except (OSError, IOError):
            continue

    for i, (label, _, color) in enumerate(MENU_ITEMS):
        col = i % COLS
        row = i // COLS
        x0 = col * CELL_W
        y0 = row * CELL_H
        x1 = x0 + CELL_W
        y1 = y0 + CELL_H
        cx = x0 + CELL_W // 2
        cy = y0 + CELL_H // 2

        # Cell background with slight gradient effect (darker at top)
        draw.rounded_rectangle([x0 + 4, y0 + 4, x1 - 4, y1 - 4], radius=15, fill=color)

        # Draw icon (above center)
        icon_cy = cy - 50
        ICON_DRAWERS[i](draw, cx, icon_cy, 50)

        # Draw text (below icon)
        text_y = cy + 30
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        draw.text((cx - tw // 2, text_y), label, fill="#FFFFFF", font=font)

    path = os.path.join(os.path.dirname(__file__), "rich_menu.png")
    img.save(path)
    print(f"Image saved: {path}")
    return path


def setup():
    configuration = Configuration(access_token=settings.line_channel_access_token)

    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        blob_api = MessagingApiBlob(api_client)

        # Delete existing
        existing = api.get_rich_menu_list()
        for rm in existing.richmenus:
            print(f"Deleting old rich menu: {rm.rich_menu_id}")
            api.delete_rich_menu(rm.rich_menu_id)

        # Create
        areas = []
        for i, (label, command, _) in enumerate(MENU_ITEMS):
            col = i % COLS
            row = i // COLS
            areas.append(
                RichMenuArea(
                    bounds=RichMenuBounds(
                        x=col * CELL_W,
                        y=row * CELL_H,
                        width=CELL_W,
                        height=CELL_H,
                    ),
                    action=MessageAction(label=label, text=command),
                )
            )

        rich_menu_id = api.create_rich_menu(
            RichMenuRequest(
                size=RichMenuSize(width=WIDTH, height=HEIGHT),
                selected=True,
                name="CPBL Betting Menu",
                chat_bar_text="選單",
                areas=areas,
            )
        ).rich_menu_id
        print(f"Created rich menu: {rich_menu_id}")

        # Upload image
        image_path = create_rich_menu_image()
        with open(image_path, "rb") as f:
            blob_api.set_rich_menu_image(
                rich_menu_id=rich_menu_id,
                body=f.read(),
                _headers={"Content-Type": "image/png"},
            )
        print("Image uploaded")

        # Set default
        api.set_default_rich_menu(rich_menu_id)
        print("Set as default rich menu! Restart LINE app to see it.")


if __name__ == "__main__":
    setup()
