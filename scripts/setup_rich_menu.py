"""Setup LINE Rich Menu with 2 tabs: 賽事 and 我的."""
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
    RichMenuSwitchAction,
    CreateRichMenuAliasRequest,
)

from app.config import settings

WIDTH = 2500
HEIGHT = 1686
COLS = 4
ROWS = 2
TAB_H = 200  # tab bar height
BODY_H = HEIGHT - TAB_H
CELL_W = WIDTH // COLS
CELL_H = BODY_H // (ROWS - 1)  # 1 row for body since tab takes a row

# Actually let's do: top row = tab bar, bottom area = 2x3 grid of buttons
GRID_COLS = 3
GRID_ROWS = 2
GRID_Y = TAB_H
GRID_CELL_W = WIDTH // GRID_COLS
GRID_CELL_H = (HEIGHT - TAB_H) // GRID_ROWS

# Tab 1: 賽事
TAB1_ITEMS = [
    ("今日賽事", "今日賽事", "#2C3E50"),
    ("即時賽事", "即時賽事", "#C0392B"),
    ("近期賽果", "近期賽果", "#34495E"),
    ("球隊戰績", "球隊戰績", "#1A5276"),
    ("未來賽事", "未來賽事", "#616A6B"),
    ("說明",     "說明",     "#7F8C8D"),
]

# Tab 2: 我的
TAB2_ITEMS = [
    ("儲值",     "儲值",     "#D35400"),
    ("我的注單", "我的注單", "#2471A3"),
    ("我的戰績", "我的戰績", "#1E8449"),
    ("排行榜",   "排行榜",   "#8E44AD"),
    ("餘額",     "餘額",     "#2C3E50"),
    ("說明",     "說明",     "#7F8C8D"),
]


def _get_font(size=60):
    for fp in [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
    ]:
        try:
            return ImageFont.truetype(fp, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _draw_text_centered(draw, text, cx, cy, font, fill="white"):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - tw // 2, cy - th // 2), text, fill=fill, font=font)


# === Icon Drawers ===

def _draw_baseball(draw, cx, cy, r):
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline="white", width=5)
    for off in [-30, 30]:
        pts = []
        for t in range(-60, 61, 10):
            rad = math.radians(t + off)
            x = cx + r*0.6*math.cos(rad) + (r*0.3 if off > 0 else -r*0.3)
            y = cy + r*math.sin(rad)
            pts.append((x, y))
        if len(pts) > 1:
            draw.line(pts, fill="white", width=4)

def _draw_live(draw, cx, cy, r):
    points = [(cx-r*0.1,cy-r),(cx-r*0.5,cy+r*0.1),(cx-r*0.05,cy+r*0.1),
              (cx-r*0.3,cy+r),(cx+r*0.5,cy-r*0.2),(cx+r*0.05,cy-r*0.2),(cx+r*0.2,cy-r)]
    draw.polygon(points, fill="white")

def _draw_scoreboard(draw, cx, cy, r):
    draw.rounded_rectangle([cx-r*0.85,cy-r*0.65,cx+r*0.85,cy+r*0.65], radius=10, outline="white", width=5)
    draw.line([cx,cy-r*0.65,cx,cy+r*0.65], fill="white", width=3)
    f = _get_font(int(r*0.8))
    _draw_text_centered(draw, "3", cx-r*0.42, cy, f)
    _draw_text_centered(draw, "5", cx+r*0.42, cy, f)

def _draw_standings(draw, cx, cy, r):
    for w_ratio, y_off in [(0.9,-0.6),(0.7,0),(0.5,0.6)]:
        y = cy + r*y_off
        x0, x1 = cx-r*w_ratio/2, cx+r*w_ratio/2
        draw.rounded_rectangle([x0,y-12,x1,y+12], radius=6, outline="white", width=4)
        draw.ellipse([x0-20,y-14,x0+8,y+14], fill="white")

def _draw_calendar(draw, cx, cy, r):
    draw.rounded_rectangle([cx-r*0.8,cy-r*0.6,cx+r*0.8,cy+r*0.8], radius=8, outline="white", width=5)
    draw.rectangle([cx-r*0.8,cy-r*0.6,cx+r*0.8,cy-r*0.2], fill="white")
    draw.line([cx-r*0.4,cy-r*0.8,cx-r*0.4,cy-r*0.4], fill="white", width=5)
    draw.line([cx+r*0.4,cy-r*0.8,cx+r*0.4,cy-r*0.4], fill="white", width=5)
    for row in range(2):
        for col in range(3):
            dx = cx-r*0.4+col*r*0.4
            dy = cy+r*0.05+row*r*0.35
            draw.ellipse([dx-5,dy-5,dx+5,dy+5], fill="white")

def _draw_help(draw, cx, cy, r):
    draw.ellipse([cx-r,cy-r,cx+r,cy+r], outline="white", width=5)
    f = _get_font(int(r*1.2))
    _draw_text_centered(draw, "?", cx, cy, f)

def _draw_coin(draw, cx, cy, r):
    draw.ellipse([cx-r,cy-r,cx+r,cy+r], outline="white", width=5)
    draw.ellipse([cx-r+10,cy-r+10,cx+r-10,cy+r-10], outline="white", width=3)
    f = _get_font(int(r*1.0))
    _draw_text_centered(draw, "$", cx, cy, f)

def _draw_ticket(draw, cx, cy, r):
    x0, y0, x1, y1 = cx-r*0.7, cy-r, cx+r*0.7, cy+r
    draw.rounded_rectangle([x0,y0,x1,y1], radius=12, outline="white", width=5)
    for i in range(3):
        ly = y0+(y1-y0)*(0.3+i*0.2)
        draw.line([x0+20,ly,x1-20,ly], fill="white", width=4)

def _draw_stats(draw, cx, cy, r):
    draw.arc([cx-r*0.8,cy-r*0.8,cx+r*0.8,cy+r*0.8], 0, 360, fill="white", width=5)
    draw.line([cx,cy,cx+r*0.8,cy], fill="white", width=4)
    draw.line([cx,cy,cx,cy-r*0.8], fill="white", width=4)
    draw.pieslice([cx-r*0.75,cy-r*0.75,cx+r*0.75,cy+r*0.75], 270, 360, fill="white")

def _draw_trophy(draw, cx, cy, r):
    draw.rounded_rectangle([cx-r*0.5,cy-r*0.8,cx+r*0.5,cy+r*0.2], radius=10, outline="white", width=5)
    draw.arc([cx-r*0.9,cy-r*0.6,cx-r*0.3,cy+r*0.1], 90, 270, fill="white", width=5)
    draw.arc([cx+r*0.3,cy-r*0.6,cx+r*0.9,cy+r*0.1], -90, 90, fill="white", width=5)
    draw.line([cx,cy+r*0.2,cx,cy+r*0.6], fill="white", width=5)
    draw.line([cx-r*0.4,cy+r*0.6,cx+r*0.4,cy+r*0.6], fill="white", width=5)

def _draw_history(draw, cx, cy, r):
    # Clock icon
    draw.ellipse([cx-r,cy-r,cx+r,cy+r], outline="white", width=5)
    draw.line([cx,cy,cx,cy-r*0.6], fill="white", width=4)
    draw.line([cx,cy,cx+r*0.5,cy+r*0.2], fill="white", width=4)


TAB1_ICONS = [_draw_baseball, _draw_live, _draw_scoreboard, _draw_standings, _draw_calendar, _draw_help]
def _draw_wallet(draw, cx, cy, r):
    """Wallet icon for 餘額."""
    draw.rounded_rectangle([cx-r*0.85, cy-r*0.6, cx+r*0.85, cy+r*0.6], radius=10, outline="white", width=5)
    draw.rounded_rectangle([cx+r*0.2, cy-r*0.3, cx+r*0.85, cy+r*0.3], radius=8, outline="white", width=4)
    draw.ellipse([cx+r*0.4, cy-8, cx+r*0.55, cy+8], fill="white")

TAB2_ICONS = [_draw_coin, _draw_ticket, _draw_stats, _draw_trophy, _draw_wallet, _draw_help]


def create_menu_image(items, icons, active_tab: int) -> str:
    """Create rich menu image. active_tab: 1 or 2."""
    img = Image.new("RGB", (WIDTH, HEIGHT), "#1B2838")
    draw = ImageDraw.Draw(img)
    font = _get_font(60)
    tab_font = _get_font(50)

    # Draw tab bar
    half_w = WIDTH // 2
    if active_tab == 1:
        draw.rectangle([0, 0, half_w, TAB_H], fill="#2C3E50")
        draw.rectangle([half_w, 0, WIDTH, TAB_H], fill="#0D1117")
        draw.line([0, TAB_H-4, half_w, TAB_H-4], fill="#F39C12", width=6)
    else:
        draw.rectangle([0, 0, half_w, TAB_H], fill="#0D1117")
        draw.rectangle([half_w, 0, WIDTH, TAB_H], fill="#2C3E50")
        draw.line([half_w, TAB_H-4, WIDTH, TAB_H-4], fill="#F39C12", width=6)

    _draw_text_centered(draw, "⚾ 賽事", half_w // 2, TAB_H // 2,
                        tab_font, fill="#FFFFFF" if active_tab == 1 else "#888888")
    _draw_text_centered(draw, "👤 我的", half_w + half_w // 2, TAB_H // 2,
                        tab_font, fill="#FFFFFF" if active_tab == 2 else "#888888")

    # Draw grid buttons
    for i, (label, _, color) in enumerate(items):
        col = i % GRID_COLS
        row = i // GRID_COLS
        x0 = col * GRID_CELL_W
        y0 = GRID_Y + row * GRID_CELL_H
        x1 = x0 + GRID_CELL_W
        y1 = y0 + GRID_CELL_H
        cx = x0 + GRID_CELL_W // 2
        cy = y0 + GRID_CELL_H // 2

        draw.rounded_rectangle([x0+6, y0+6, x1-6, y1-6], radius=20, fill=color)

        # Icon
        icon_cy = cy - 60
        icons[i](draw, cx, icon_cy, 70)

        # Text
        _draw_text_centered(draw, label, cx, cy + 50, font)

    suffix = "tab1" if active_tab == 1 else "tab2"
    path = os.path.join(os.path.dirname(__file__), f"rich_menu_{suffix}.png")
    img.save(path)
    print(f"Image saved: {path}")
    return path


def setup():
    configuration = Configuration(access_token=settings.line_channel_access_token)

    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        blob_api = MessagingApiBlob(api_client)

        # Delete all existing rich menus
        existing = api.get_rich_menu_list()
        for rm in existing.richmenus:
            print(f"Deleting: {rm.rich_menu_id}")
            api.delete_rich_menu(rm.rich_menu_id)

        # Delete existing aliases
        for alias_id in ["tab-games", "tab-mine"]:
            try:
                api.delete_rich_menu_alias(alias_id)
            except Exception:
                pass

        # === Create Tab 1: 賽事 ===
        tab1_areas = []
        from linebot.v3.messaging import PostbackAction
        # Tab switch areas (top bar)
        tab1_areas.append(RichMenuArea(
            bounds=RichMenuBounds(x=0, y=0, width=WIDTH//2, height=TAB_H),
            action=PostbackAction(label="賽事", data="noop"),  # already on this tab, do nothing
        ))
        tab1_areas.append(RichMenuArea(
            bounds=RichMenuBounds(x=WIDTH//2, y=0, width=WIDTH//2, height=TAB_H),
            action=RichMenuSwitchAction(label="我的", rich_menu_alias_id="tab-mine", data="switch-tab2"),
        ))
        # Grid buttons
        for i, (label, command, _) in enumerate(TAB1_ITEMS):
            col = i % GRID_COLS
            row = i // GRID_COLS
            tab1_areas.append(RichMenuArea(
                bounds=RichMenuBounds(
                    x=col * GRID_CELL_W, y=GRID_Y + row * GRID_CELL_H,
                    width=GRID_CELL_W, height=GRID_CELL_H,
                ),
                action=MessageAction(label=label, text=command),
            ))

        tab1_id = api.create_rich_menu(RichMenuRequest(
            size=RichMenuSize(width=WIDTH, height=HEIGHT),
            selected=True,
            name="CPBL - 賽事",
            chat_bar_text="選單",
            areas=tab1_areas,
        )).rich_menu_id
        print(f"Tab1 created: {tab1_id}")

        # Upload image
        img_path = create_menu_image(TAB1_ITEMS, TAB1_ICONS, active_tab=1)
        with open(img_path, "rb") as f:
            blob_api.set_rich_menu_image(tab1_id, body=f.read(), _headers={"Content-Type": "image/png"})

        # === Create Tab 2: 我的 ===
        tab2_areas = []
        tab2_areas.append(RichMenuArea(
            bounds=RichMenuBounds(x=0, y=0, width=WIDTH//2, height=TAB_H),
            action=RichMenuSwitchAction(label="賽事", rich_menu_alias_id="tab-games", data="switch-tab1"),
        ))
        tab2_areas.append(RichMenuArea(
            bounds=RichMenuBounds(x=WIDTH//2, y=0, width=WIDTH//2, height=TAB_H),
            action=PostbackAction(label="我的", data="noop"),  # already on this tab, do nothing
        ))
        for i, (label, command, _) in enumerate(TAB2_ITEMS):
            col = i % GRID_COLS
            row = i // GRID_COLS
            tab2_areas.append(RichMenuArea(
                bounds=RichMenuBounds(
                    x=col * GRID_CELL_W, y=GRID_Y + row * GRID_CELL_H,
                    width=GRID_CELL_W, height=GRID_CELL_H,
                ),
                action=MessageAction(label=label, text=command),
            ))

        tab2_id = api.create_rich_menu(RichMenuRequest(
            size=RichMenuSize(width=WIDTH, height=HEIGHT),
            selected=True,
            name="CPBL - 我的",
            chat_bar_text="選單",
            areas=tab2_areas,
        )).rich_menu_id
        print(f"Tab2 created: {tab2_id}")

        img_path = create_menu_image(TAB2_ITEMS, TAB2_ICONS, active_tab=2)
        with open(img_path, "rb") as f:
            blob_api.set_rich_menu_image(tab2_id, body=f.read(), _headers={"Content-Type": "image/png"})

        # === Create aliases for tab switching ===
        api.create_rich_menu_alias(CreateRichMenuAliasRequest(
            rich_menu_alias_id="tab-games",
            rich_menu_id=tab1_id,
        ))
        api.create_rich_menu_alias(CreateRichMenuAliasRequest(
            rich_menu_alias_id="tab-mine",
            rich_menu_id=tab2_id,
        ))
        print("Aliases created")

        # Set Tab 1 as default
        api.set_default_rich_menu(tab1_id)
        print("Default set to Tab 1 (賽事)")
        print("Done! Restart LINE app.")


if __name__ == "__main__":
    setup()
