"""Flex Message builders for LINE Bot UI."""
from __future__ import annotations


def build_game_card(game: dict) -> dict:
    """Build a single game bubble for the carousel."""
    markets = game.get("odds", {}).get("markets", [])

    # Build market rows
    market_contents = []
    for i, market in enumerate(markets):
        options = market.get("options", [])
        option_buttons = []
        for opt in options:
            option_buttons.append({
                "type": "button",
                "action": {
                    "type": "postback",
                    "label": f"{opt['label']} @{opt['odds']}",
                    "data": f"bet|{game['id']}|{i}|{opt['label']}|{opt['odds']}",
                    "displayText": f"下注: {opt['label']} @{opt['odds']}",
                },
                "style": "primary",
                "height": "sm",
                "margin": "sm",
                "color": "#4A90D9",
            })

        market_contents.append({
            "type": "box",
            "layout": "vertical",
            "margin": "lg",
            "contents": [
                {
                    "type": "text",
                    "text": market.get("name", ""),
                    "weight": "bold",
                    "size": "sm",
                    "color": "#333333",
                },
                *(
                    [{
                        "type": "text",
                        "text": market.get("description", ""),
                        "size": "xs",
                        "color": "#888888",
                        "wrap": True,
                    }] if market.get("description") else []
                ),
                *option_buttons,
            ],
        })

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1B2838",
            "paddingAll": "15px",
            "contents": [
                {
                    "type": "text",
                    "text": f"CPBL {game.get('date', '')}",
                    "color": "#AAAAAA",
                    "size": "xs",
                },
                {
                    "type": "text",
                    "text": f"{game.get('away_team_name', '')}  VS  {game.get('home_team_name', '')}",
                    "color": "#FFFFFF",
                    "weight": "bold",
                    "size": "lg",
                    "margin": "sm",
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "md",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"📍 {game.get('venue', '')}",
                            "color": "#CCCCCC",
                            "size": "xs",
                            "flex": 1,
                        },
                        {
                            "type": "text",
                            "text": f"⏰ {game.get('game_time', '')}",
                            "color": "#CCCCCC",
                            "size": "xs",
                            "flex": 1,
                            "align": "end",
                        },
                    ],
                },
                {
                    "type": "text",
                    "text": f"先發: {game.get('away_pitcher', 'TBD')} vs {game.get('home_pitcher', 'TBD')}",
                    "color": "#CCCCCC",
                    "size": "xs",
                    "margin": "sm",
                },
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "15px",
            "contents": market_contents if market_contents else [
                {"type": "text", "text": "尚無可下注玩法", "color": "#888888", "size": "sm"}
            ],
        },
    }


def build_games_carousel(games: list[dict]) -> dict:
    """Build carousel of game cards."""
    bubbles = [build_game_card(g) for g in games]
    return {
        "type": "flex",
        "altText": "今日賽事",
        "contents": {
            "type": "carousel",
            "contents": bubbles[:10],  # LINE carousel max 10 bubbles
        },
    }


def build_bet_confirm(game: dict, market_name: str, selection: str, odds: float, user_balance: int) -> dict:
    """Build bet confirmation bubble."""
    return {
        "type": "flex",
        "altText": "確認下注",
        "contents": {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "確認下注", "weight": "bold", "size": "xl"},
                    {"type": "separator", "margin": "lg"},
                    {
                        "type": "box",
                        "layout": "vertical",
                        "margin": "lg",
                        "spacing": "sm",
                        "contents": [
                            _kv_row("比賽", f"{game.get('away_team_name', '')} vs {game.get('home_team_name', '')}"),
                            _kv_row("玩法", market_name),
                            _kv_row("選擇", selection),
                            _kv_row("賠率", str(odds)),
                        ],
                    },
                    {"type": "separator", "margin": "lg"},
                    {
                        "type": "text",
                        "text": f"目前餘額: {user_balance:,} 元",
                        "size": "sm",
                        "color": "#888888",
                        "margin": "lg",
                    },
                    {
                        "type": "text",
                        "text": "請輸入下注金額:",
                        "size": "md",
                        "margin": "lg",
                        "weight": "bold",
                    },
                ],
            },
        },
    }


def build_bet_final_confirm(game: dict, market_name: str, selection: str, odds: float, amount: int) -> dict:
    """Build final confirm/cancel for a bet."""
    potential = round(amount * odds)
    return {
        "type": "flex",
        "altText": "確認下注",
        "contents": {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "下注確認", "weight": "bold", "size": "xl"},
                    {"type": "separator", "margin": "lg"},
                    {
                        "type": "box",
                        "layout": "vertical",
                        "margin": "lg",
                        "spacing": "sm",
                        "contents": [
                            _kv_row("比賽", f"{game.get('away_team_name', '')} vs {game.get('home_team_name', '')}"),
                            _kv_row("玩法", market_name),
                            _kv_row("選擇", selection),
                            _kv_row("賠率", str(odds)),
                            _kv_row("金額", f"{amount:,} 元"),
                            _kv_row("預計獎金", f"{potential:,} 元"),
                        ],
                    },
                ],
            },
            "footer": {
                "type": "box",
                "layout": "horizontal",
                "spacing": "md",
                "contents": [
                    {
                        "type": "button",
                        "action": {
                            "type": "postback",
                            "label": "確認下注",
                            "data": "confirm_bet",
                        },
                        "style": "primary",
                        "color": "#27AE60",
                    },
                    {
                        "type": "button",
                        "action": {
                            "type": "postback",
                            "label": "取消",
                            "data": "cancel_bet",
                        },
                        "style": "secondary",
                    },
                ],
            },
        },
    }


def build_deposit_menu(user: dict) -> dict:
    """Build deposit menu bubble."""
    today_total = user.get("deposit_today_total", 0)
    return {
        "type": "flex",
        "altText": "儲值",
        "contents": {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "儲值虛擬幣", "weight": "bold", "size": "xl"},
                    {"type": "separator", "margin": "lg"},
                    {
                        "type": "box",
                        "layout": "vertical",
                        "margin": "lg",
                        "spacing": "sm",
                        "contents": [
                            _kv_row("目前餘額", f"{user.get('balance', 0):,} 元"),
                            _kv_row("今日已儲值", f"{today_total:,} / 10,000 元"),
                        ],
                    },
                ],
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "spacing": "sm",
                        "contents": [
                            _deposit_button(1000),
                            _deposit_button(3000),
                        ],
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "spacing": "sm",
                        "contents": [
                            _deposit_button(5000),
                            _deposit_button(10000),
                        ],
                    },
                    {
                        "type": "button",
                        "action": {
                            "type": "postback",
                            "label": "自訂金額",
                            "data": "deposit_custom",
                            "displayText": "自訂儲值金額",
                        },
                        "style": "secondary",
                        "margin": "sm",
                    },
                ],
            },
        },
    }


def build_stats(user: dict, recent_bets: list[dict]) -> dict:
    """Build personal stats bubble."""
    total_bets = user.get("total_wagered", 0)
    total_won = user.get("total_won", 0)
    profit = user.get("total_profit", 0)
    profit_sign = "+" if profit >= 0 else ""
    profit_color = "#27AE60" if profit >= 0 else "#E74C3C"

    # Count wins from recent bets
    won_count = sum(1 for b in recent_bets if b.get("status") == "won")
    total_count = sum(1 for b in recent_bets if b.get("status") in ("won", "lost"))
    win_rate = f"{won_count / total_count * 100:.1f}%" if total_count > 0 else "N/A"

    bet_rows = []
    for b in recent_bets[:5]:
        status = b.get("status", "pending")
        icon = {"won": "✅", "lost": "❌", "pending": "⏳", "refunded": "🔄"}.get(status, "?")
        p = b.get("profit", 0)
        bet_rows.append({
            "type": "text",
            "text": f"{icon} {b.get('selection', '')} {'+' if p >= 0 else ''}{p:,}",
            "size": "sm",
            "color": "#555555",
        })

    return {
        "type": "flex",
        "altText": "我的戰績",
        "contents": {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "我的戰績", "weight": "bold", "size": "xl"},
                    {"type": "separator", "margin": "lg"},
                    {
                        "type": "box",
                        "layout": "vertical",
                        "margin": "lg",
                        "spacing": "sm",
                        "contents": [
                            _kv_row("餘額", f"{user.get('balance', 0):,} 元"),
                            _kv_row("總下注次數", f"{total_count} 注"),
                            _kv_row("勝率", win_rate),
                            {
                                "type": "box",
                                "layout": "horizontal",
                                "contents": [
                                    {"type": "text", "text": "總獲利", "size": "sm", "color": "#888888", "flex": 2},
                                    {"type": "text", "text": f"{profit_sign}{profit:,} 元", "size": "sm", "color": profit_color, "align": "end", "flex": 3},
                                ],
                            },
                        ],
                    },
                    {"type": "separator", "margin": "lg"},
                    {"type": "text", "text": "最近紀錄", "weight": "bold", "size": "sm", "margin": "lg"},
                    *(bet_rows if bet_rows else [{"type": "text", "text": "尚無紀錄", "size": "sm", "color": "#888888"}]),
                ],
            },
        },
    }


def build_leaderboard(rankings: list[dict], user: dict, house_profit: int) -> dict:
    """Build leaderboard bubble."""
    rows = []
    for i, r in enumerate(rankings[:10]):
        medal = {0: "🥇", 1: "🥈", 2: "🥉"}.get(i, f"{i+1}.")
        p = r.get("total_profit", 0)
        rows.append({
            "type": "text",
            "text": f"{medal} {r.get('display_name', '???')}  {'+' if p >= 0 else ''}{p:,} 元",
            "size": "sm",
            "color": "#333333",
        })

    user_profit = user.get("total_profit", 0)

    return {
        "type": "flex",
        "altText": "排行榜",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "獲利排行榜 TOP 10", "weight": "bold", "size": "xl"},
                    {"type": "separator", "margin": "lg"},
                    {
                        "type": "box",
                        "layout": "vertical",
                        "margin": "lg",
                        "spacing": "sm",
                        "contents": rows if rows else [{"type": "text", "text": "尚無資料", "size": "sm", "color": "#888888"}],
                    },
                    {"type": "separator", "margin": "lg"},
                    {
                        "type": "text",
                        "text": f"你的獲利: {'+' if user_profit >= 0 else ''}{user_profit:,} 元",
                        "size": "sm",
                        "color": "#4A90D9",
                        "margin": "lg",
                        "weight": "bold",
                    },
                    {
                        "type": "text",
                        "text": f"🏠 莊家獲利: {house_profit:,} 元",
                        "size": "sm",
                        "color": "#888888",
                        "margin": "sm",
                    },
                ],
            },
        },
    }


def build_my_bets(bets: list[dict]) -> dict:
    """Build bet history as Flex Message carousel."""
    STATUS_CONFIG = {
        "won":      {"icon": "✅", "label": "贏", "color": "#27AE60", "bg": "#E8F8F0"},
        "lost":     {"icon": "❌", "label": "輸", "color": "#E74C3C", "bg": "#FDEDEC"},
        "pending":  {"icon": "⏳", "label": "待結算", "color": "#F39C12", "bg": "#FEF5E7"},
        "refunded": {"icon": "🔄", "label": "退款", "color": "#3498DB", "bg": "#EBF5FB"},
    }

    bubbles = []
    for b in bets:
        status = b.get("status", "pending")
        cfg = STATUS_CONFIG.get(status, STATUS_CONFIG["pending"])
        profit = b.get("profit", 0)
        profit_text = f"+{profit:,}" if profit > 0 else f"{profit:,}"
        reason = b.get("settlement_reason", "")

        body_contents = [
            # Status badge
            {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": f"{cfg['icon']} {cfg['label']}", "size": "sm",
                             "color": cfg["color"], "weight": "bold"},
                        ],
                        "backgroundColor": cfg["bg"],
                        "cornerRadius": "md",
                        "paddingAll": "5px",
                        "paddingStart": "10px",
                        "paddingEnd": "10px",
                    },
                    {"type": "filler"},
                    {"type": "text", "text": f"{b.get('amount', 0):,} 元", "size": "sm",
                     "color": "#555555", "align": "end", "weight": "bold"},
                ],
            },
            # Market name
            {
                "type": "text",
                "text": b.get("market_name", ""),
                "weight": "bold",
                "size": "md",
                "margin": "lg",
                "wrap": True,
            },
            # Selection + odds
            {
                "type": "text",
                "text": f"{b.get('selection', '')}  @{b.get('odds', 0)}",
                "size": "sm",
                "color": "#666666",
                "margin": "sm",
            },
            {"type": "separator", "margin": "lg"},
        ]

        # Payout row (only for settled bets)
        if status in ("won", "lost"):
            body_contents.append({
                "type": "box",
                "layout": "horizontal",
                "margin": "lg",
                "contents": [
                    {"type": "text", "text": "損益", "size": "sm", "color": "#888888", "flex": 1},
                    {"type": "text", "text": profit_text + " 元", "size": "sm",
                     "color": cfg["color"], "align": "end", "weight": "bold", "flex": 2},
                ],
            })

        if status == "won":
            body_contents.append({
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": "獎金", "size": "sm", "color": "#888888", "flex": 1},
                    {"type": "text", "text": f"{b.get('payout', 0):,} 元", "size": "sm",
                     "color": "#333333", "align": "end", "flex": 2},
                ],
            })

        # Settlement reason
        if reason:
            body_contents.append({
                "type": "box",
                "layout": "vertical",
                "margin": "lg",
                "backgroundColor": "#F5F6FA",
                "cornerRadius": "md",
                "paddingAll": "10px",
                "contents": [
                    {"type": "text", "text": "結算依據", "size": "xxs", "color": "#888888"},
                    {"type": "text", "text": reason, "size": "sm", "color": "#333333",
                     "wrap": True, "margin": "sm"},
                ],
            })

        bubbles.append({
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "paddingAll": "15px",
                "contents": body_contents,
            },
        })

    return {
        "type": "flex",
        "altText": "我的注單",
        "contents": {
            "type": "carousel",
            "contents": bubbles[:10],
        },
    }


def build_standings(standings: dict) -> dict:
    """Build CPBL standings as Flex Message."""
    # Sort by win_rate descending
    sorted_teams = sorted(standings.values(), key=lambda t: t.get("win_rate", 0), reverse=True)

    RANK_COLORS = ["#FFD700", "#C0C0C0", "#CD7F32", "#555555", "#555555", "#555555"]

    team_rows = []
    for i, team in enumerate(sorted_teams):
        wins = team.get("wins", 0)
        losses = team.get("losses", 0)
        ties = team.get("ties", 0)
        wr = team.get("win_rate", 0)
        era = team.get("team_era", "N/A")
        recent = team.get("recent_10", "N/A")
        rank_color = RANK_COLORS[i] if i < len(RANK_COLORS) else "#555555"

        team_rows.append({
            "type": "box",
            "layout": "vertical",
            "margin": "lg",
            "contents": [
                # Rank + Team name
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "vertical",
                            "contents": [
                                {"type": "text", "text": str(i + 1), "size": "lg",
                                 "weight": "bold", "color": "#FFFFFF", "align": "center"},
                            ],
                            "width": "30px",
                            "height": "30px",
                            "backgroundColor": rank_color,
                            "cornerRadius": "50px",
                            "justifyContent": "center",
                            "alignItems": "center",
                        },
                        {"type": "text", "text": team.get("name", ""), "weight": "bold",
                         "size": "md", "margin": "md", "gravity": "center"},
                    ],
                },
                # Stats row
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "sm",
                    "paddingStart": "42px",
                    "contents": [
                        {"type": "text", "text": f"{wins}勝{losses}敗{f'{ties}和' if ties else ''}",
                         "size": "sm", "color": "#666666", "flex": 3},
                        {"type": "text", "text": f".{int(wr * 1000):03d}" if wr < 1 else "1.000",
                         "size": "sm", "color": "#333333", "weight": "bold", "flex": 2, "align": "center"},
                        {"type": "text", "text": f"ERA {era}",
                         "size": "xs", "color": "#888888", "flex": 2, "align": "end"},
                    ],
                },
                # Recent 10
                {
                    "type": "box",
                    "layout": "horizontal",
                    "paddingStart": "42px",
                    "contents": [
                        {"type": "text", "text": f"近10場: {recent}",
                         "size": "xs", "color": "#999999"},
                    ],
                },
            ],
        })

        # Add separator between teams (not after last)
        if i < len(sorted_teams) - 1:
            team_rows.append({"type": "separator", "margin": "lg"})

    return {
        "type": "flex",
        "altText": "CPBL 球隊戰績",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#1B2838",
                "paddingAll": "15px",
                "contents": [
                    {"type": "text", "text": "⚾ CPBL 2026 球隊戰績", "color": "#FFFFFF",
                     "weight": "bold", "size": "lg"},
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "paddingAll": "15px",
                "contents": team_rows,
            },
        },
    }


def build_success_message(text: str) -> dict:
    """Simple success text message."""
    return {"type": "text", "text": f"✅ {text}"}


def build_error_message(text: str) -> dict:
    """Simple error text message."""
    return {"type": "text", "text": f"❌ {text}"}


# --- helpers ---

def _kv_row(key: str, value: str) -> dict:
    return {
        "type": "box",
        "layout": "horizontal",
        "contents": [
            {"type": "text", "text": key, "size": "sm", "color": "#888888", "flex": 2},
            {"type": "text", "text": value, "size": "sm", "color": "#333333", "align": "end", "flex": 3},
        ],
    }


def _deposit_button(amount: int) -> dict:
    return {
        "type": "button",
        "action": {
            "type": "postback",
            "label": f"{amount:,} 元",
            "data": f"deposit|{amount}",
            "displayText": f"儲值 {amount:,} 元",
        },
        "style": "primary",
        "color": "#F39C12",
        "flex": 1,
    }
