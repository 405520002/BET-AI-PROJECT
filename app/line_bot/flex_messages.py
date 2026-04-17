"""Flex Message builders for LINE Bot UI."""
from __future__ import annotations


def build_game_card(game: dict) -> dict:
    """Build a single game bubble for the carousel."""
    markets = game.get("odds", {}).get("markets", [])
    can_bet = game.get("_can_bet", True)

    # Build market rows
    market_contents = []
    for i, market in enumerate(markets):
        options = market.get("options", [])
        option_buttons = []
        for opt in options:
            if can_bet:
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
            else:
                option_buttons.append({
                    "type": "button",
                    "action": {
                        "type": "message",
                        "label": f"{opt['label']} @{opt['odds']}",
                        "text": "比賽已開始，無法下注",
                    },
                    "style": "secondary",
                    "height": "sm",
                    "margin": "sm",
                    "color": "#CCCCCC",
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
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"CPBL {game.get('date', '')}",
                            "color": "#AAAAAA",
                            "size": "xs",
                            "flex": 3,
                        },
                        *(
                            [{
                                "type": "text",
                                "text": "已封盤",
                                "color": "#E74C3C",
                                "size": "xs",
                                "weight": "bold",
                                "align": "end",
                                "flex": 1,
                            }] if not can_bet else []
                        ),
                    ],
                },
                # Team logos + names
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "lg",
                    "contents": [
                        # Away team
                        {
                            "type": "box",
                            "layout": "vertical",
                            "flex": 2,
                            "alignItems": "center",
                            "contents": [
                                *(
                                    [{
                                        "type": "image",
                                        "url": game.get("away_logo", ""),
                                        "size": "40px",
                                        "aspectMode": "fit",
                                    }] if game.get("away_logo") else []
                                ),
                                {
                                    "type": "text",
                                    "text": game.get("away_team_name", ""),
                                    "color": "#FFFFFF",
                                    "weight": "bold",
                                    "size": "sm",
                                    "align": "center",
                                    "margin": "sm",
                                },
                            ],
                        },
                        # VS
                        {
                            "type": "box",
                            "layout": "vertical",
                            "flex": 1,
                            "justifyContent": "center",
                            "alignItems": "center",
                            "contents": [
                                {
                                    "type": "text",
                                    "text": "VS",
                                    "color": "#F39C12",
                                    "weight": "bold",
                                    "size": "lg",
                                    "align": "center",
                                },
                            ],
                        },
                        # Home team
                        {
                            "type": "box",
                            "layout": "vertical",
                            "flex": 2,
                            "alignItems": "center",
                            "contents": [
                                *(
                                    [{
                                        "type": "image",
                                        "url": game.get("home_logo", ""),
                                        "size": "40px",
                                        "aspectMode": "fit",
                                    }] if game.get("home_logo") else []
                                ),
                                {
                                    "type": "text",
                                    "text": game.get("home_team_name", ""),
                                    "color": "#FFFFFF",
                                    "weight": "bold",
                                    "size": "sm",
                                    "align": "center",
                                    "margin": "sm",
                                },
                            ],
                        },
                    ],
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "margin": "lg",
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
                        "text": "請輸入下注金額或選擇:",
                        "size": "md",
                        "margin": "lg",
                        "weight": "bold",
                    },
                    # Quick amount buttons
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "margin": "lg",
                        "spacing": "sm",
                        "contents": [
                            _quick_bet_button(100),
                            _quick_bet_button(500),
                            _quick_bet_button(1000),
                        ],
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "margin": "sm",
                        "spacing": "sm",
                        "contents": [
                            _quick_bet_button(3000),
                            _quick_bet_button(5000),
                            _quick_bet_button(10000),
                        ],
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


def build_recent_results(games: list[dict]) -> dict:
    """Build recent game results as carousel cards."""
    bubbles = []
    for g in games:
        away_name = g.get("away_team_name", "")
        home_name = g.get("home_team_name", "")
        away_score = g.get("away_score", 0)
        home_score = g.get("home_score", 0)
        game_date = g.get("date", "")
        venue = g.get("venue", "")
        status = g.get("status", "")

        if status == "postponed":
            is_postponed = True
        else:
            is_postponed = False

        # Determine winner
        away_color = "#27AE60" if away_score > home_score else "#CCCCCC"
        home_color = "#27AE60" if home_score > away_score else "#CCCCCC"

        away_logo = g.get("away_logo", "")
        home_logo = g.get("home_logo", "")

        bubble = {
            "type": "bubble",
            "size": "kilo",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#1B2838",
                "paddingAll": "12px",
                "contents": [
                    {
                        "type": "text",
                        "text": f"{game_date}  {venue}",
                        "color": "#999999",
                        "size": "xxs",
                        "align": "center",
                    },
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#1B2838",
                "paddingAll": "15px",
                "contents": [
                    # Score row
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            # Away team
                            {
                                "type": "box",
                                "layout": "vertical",
                                "flex": 3,
                                "alignItems": "center",
                                "contents": [
                                    *(
                                        [{
                                            "type": "image",
                                            "url": away_logo,
                                            "size": "35px",
                                            "aspectMode": "fit",
                                        }] if away_logo else []
                                    ),
                                    {
                                        "type": "text",
                                        "text": away_name,
                                        "color": away_color,
                                        "weight": "bold",
                                        "size": "xs",
                                        "align": "center",
                                        "margin": "sm",
                                    },
                                ],
                            },
                            # Score
                            {
                                "type": "box",
                                "layout": "horizontal",
                                "flex": 3,
                                "justifyContent": "center",
                                "alignItems": "center",
                                "spacing": "sm",
                                "contents": [
                                    {
                                        "type": "text",
                                        "text": "延賽" if is_postponed else str(away_score),
                                        "color": "#F39C12" if is_postponed else away_color,
                                        "weight": "bold",
                                        "size": "xxl" if not is_postponed else "md",
                                        "align": "center",
                                        "flex": 2,
                                    },
                                    {
                                        "type": "text",
                                        "text": "" if is_postponed else ":",
                                        "color": "#888888",
                                        "size": "md",
                                        "align": "center",
                                        "flex": 1,
                                    },
                                    {
                                        "type": "text",
                                        "text": "" if is_postponed else str(home_score),
                                        "color": "#F39C12" if is_postponed else home_color,
                                        "weight": "bold",
                                        "size": "xxl" if not is_postponed else "md",
                                        "align": "center",
                                        "flex": 2,
                                    },
                                ],
                            },
                            # Home team
                            {
                                "type": "box",
                                "layout": "vertical",
                                "flex": 3,
                                "alignItems": "center",
                                "contents": [
                                    *(
                                        [{
                                            "type": "image",
                                            "url": home_logo,
                                            "size": "35px",
                                            "aspectMode": "fit",
                                        }] if home_logo else []
                                    ),
                                    {
                                        "type": "text",
                                        "text": home_name,
                                        "color": home_color,
                                        "weight": "bold",
                                        "size": "xs",
                                        "align": "center",
                                        "margin": "sm",
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
        }

        bubbles.append(bubble)

    return {
        "type": "flex",
        "altText": "近期賽果",
        "contents": {
            "type": "carousel",
            "contents": bubbles[:10],
        },
    }


def build_upcoming_schedule(games_by_date: dict[str, list[dict]]) -> dict:
    """Build upcoming 7-day schedule as carousel, one bubble per date."""
    WEEKDAY_ZH = ["一", "二", "三", "四", "五", "六", "日"]
    bubbles = []

    for date_str, games in sorted(games_by_date.items()):
        # Parse weekday
        from datetime import date as date_cls
        parts = date_str.split("-")
        d = date_cls(int(parts[0]), int(parts[1]), int(parts[2]))
        weekday = WEEKDAY_ZH[d.weekday()]

        game_rows = []
        for g in games:
            away = g.get("away_team_name", "")
            home = g.get("home_team_name", "")
            venue = g.get("venue", "")
            game_time = g.get("game_time", "")

            game_rows.append({
                "type": "box",
                "layout": "horizontal",
                "margin": "lg",
                "contents": [
                    {
                        "type": "box",
                        "layout": "vertical",
                        "flex": 5,
                        "contents": [
                            {
                                "type": "text",
                                "text": f"{away}  vs  {home}",
                                "size": "sm",
                                "weight": "bold",
                                "color": "#333333",
                            },
                            {
                                "type": "text",
                                "text": f"{venue}  {game_time}",
                                "size": "xs",
                                "color": "#888888",
                                "margin": "xs",
                            },
                        ],
                    },
                ],
            })

            # Separator between games
            if g != games[-1]:
                game_rows.append({"type": "separator", "margin": "lg"})

        bubble = {
            "type": "bubble",
            "size": "kilo",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#1B2838",
                "paddingAll": "12px",
                "contents": [
                    {
                        "type": "text",
                        "text": f"{date_str} (週{weekday})",
                        "color": "#FFFFFF",
                        "weight": "bold",
                        "size": "md",
                        "align": "center",
                    },
                    {
                        "type": "text",
                        "text": f"{len(games)} 場比賽",
                        "color": "#AAAAAA",
                        "size": "xs",
                        "align": "center",
                        "margin": "xs",
                    },
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "paddingAll": "12px",
                "contents": game_rows if game_rows else [
                    {"type": "text", "text": "無賽事", "color": "#888888", "size": "sm", "align": "center"}
                ],
            },
        }
        bubbles.append(bubble)

    if not bubbles:
        return {"type": "text", "text": "未來七天沒有賽事"}

    return {
        "type": "flex",
        "altText": "未來七天賽事",
        "contents": {
            "type": "carousel",
            "contents": bubbles[:10],
        },
    }


def build_live_scores(games: list[dict]) -> dict:
    """Build live score cards with inning-by-inning scoreboard."""
    bubbles = []

    for g in games:
        away = g.get("away_team_name", "") or "客隊"
        home = g.get("home_team_name", "") or "主隊"
        away_score = g.get("away_score", 0)
        home_score = g.get("home_score", 0)
        status_text = g.get("status_text", "")
        innings = g.get("innings", {})  # {"away": [0,1,0,...], "home": [0,0,2,...]}

        away_innings = innings.get("away", [])
        home_innings = innings.get("home", [])
        has_innings = len(away_innings) > 0 or len(home_innings) > 0

        # Build scoreboard rows only if we have inning data
        scoreboard_rows = []
        if has_innings:
            max_inn = max(len(away_innings), len(home_innings), 1)

            header_cells = []
            for i in range(1, max_inn + 1):
                header_cells.append({"type": "text", "text": str(i), "size": "xxs", "color": "#999999", "align": "center", "flex": 1})
            header_cells.append({"type": "text", "text": "R", "size": "xxs", "color": "#FFFFFF", "align": "center", "flex": 1, "weight": "bold"})

            away_cells = []
            for i in range(max_inn):
                score = str(away_innings[i]) if i < len(away_innings) else "-"
                away_cells.append({"type": "text", "text": score, "size": "xxs", "color": "#CCCCCC", "align": "center", "flex": 1})
            away_cells.append({"type": "text", "text": str(away_score), "size": "sm", "color": "#FFFFFF", "align": "center", "flex": 1, "weight": "bold"})

            home_cells = []
            for i in range(max_inn):
                score = str(home_innings[i]) if i < len(home_innings) else "-"
                home_cells.append({"type": "text", "text": score, "size": "xxs", "color": "#CCCCCC", "align": "center", "flex": 1})
            home_cells.append({"type": "text", "text": str(home_score), "size": "sm", "color": "#FFFFFF", "align": "center", "flex": 1, "weight": "bold"})

            scoreboard_rows = [
                {"type": "box", "layout": "horizontal", "margin": "md", "contents": [{"type": "text", "text": " ", "size": "xxs", "flex": 3}] + header_cells},
                {"type": "box", "layout": "horizontal", "margin": "sm", "contents": [{"type": "text", "text": away, "size": "xs", "color": "#FFFFFF", "flex": 3, "weight": "bold"}] + away_cells},
                {"type": "box", "layout": "horizontal", "margin": "sm", "contents": [{"type": "text", "text": home, "size": "xs", "color": "#FFFFFF", "flex": 3, "weight": "bold"}] + home_cells},
            ]
        else:
            # Simple score display when no inning data
            scoreboard_rows = [
                {
                    "type": "box", "layout": "horizontal", "margin": "lg",
                    "contents": [
                        {"type": "text", "text": away, "size": "md", "color": "#CCCCCC", "flex": 3, "weight": "bold"},
                        {"type": "text", "text": str(away_score), "size": "xxl", "color": "#FFFFFF", "weight": "bold", "align": "center", "flex": 1},
                        {"type": "text", "text": ":", "size": "lg", "color": "#888888", "align": "center", "flex": 1},
                        {"type": "text", "text": str(home_score), "size": "xxl", "color": "#FFFFFF", "weight": "bold", "align": "center", "flex": 1},
                        {"type": "text", "text": home, "size": "md", "color": "#CCCCCC", "align": "end", "flex": 3, "weight": "bold"},
                    ],
                },
            ]

        # Current at-bat + bases
        current_ab = g.get("current_ab", {})
        batting_side = current_ab.get("batting_side", "")
        pitching_side = "away" if batting_side == "home" else "home"

        current_rows = []
        if current_ab.get("hitter"):
            # Base diamond: ◆=有人 ◇=沒人
            b1 = "◆" if current_ab.get("base1") else "◇"
            b2 = "◆" if current_ab.get("base2") else "◇"
            b3 = "◆" if current_ab.get("base3") else "◇"
            outs = current_ab.get("outs", 0)
            out_dots = "●" * outs + "○" * (3 - outs)
            inning = current_ab.get("inning", 0)
            half = "▲" if batting_side == "away" else "▼"

            current_rows = [
                {
                    "type": "box", "layout": "horizontal", "margin": "md",
                    "contents": [
                        # Bases + outs
                        {"type": "text", "text": f"{half}{inning}局  {b3} {b2} {b1}  {out_dots}", "size": "xs", "color": "#F1C40F", "flex": 4},
                        {"type": "filler", "flex": 1},
                    ],
                },
                {
                    "type": "box", "layout": "horizontal", "margin": "sm",
                    "contents": [
                        {"type": "text", "text": f"⚾ {current_ab.get('pitcher','')}", "size": "xs", "color": "#3498DB", "flex": 3},
                        {"type": "text", "text": "vs", "size": "xxs", "color": "#888888", "align": "center", "flex": 1},
                        {"type": "text", "text": f"🏏 {current_ab['hitter']}", "size": "xs", "color": "#E74C3C", "align": "end", "flex": 3},
                    ],
                },
            ]

        # Pitchers - show both teams, mark current pitcher with 🔴
        pitchers = g.get("pitchers", [])
        pitcher_rows = []

        for side_key, side_label in [("away", "客"), ("home", "主")]:
            side_pitchers = [p for p in pitchers if p.get("team") == side_key]
            if not side_pitchers:
                continue
            pitcher_rows.append({"type": "text", "text": f"[{side_label}]", "size": "xxs", "color": "#888888", "margin": "sm"})
            for p in side_pitchers:
                name = p.get("name", "") or "---"
                is_current = (name == current_ab.get("pitcher", ""))
                dot = "🔴 " if is_current else "    "
                role = f"({p.get('role','')})" if p.get("role") else ""
                speed = f" {p['max_speed']}km" if p.get("max_speed", 0) > 0 else ""
                text = f"{dot}{name}{role} {p.get('ip','')}局 {p.get('k',0)}K {p.get('er',0)}ER"
                pitches = f"      {p.get('pitches',0)}球({p.get('strikes',0)}好{p.get('balls',0)}壞){speed}"
                pitcher_rows.append({"type": "text", "text": text, "size": "xxs", "color": "#FFFFFF" if is_current else "#CCCCCC"})
                pitcher_rows.append({"type": "text", "text": pitches, "size": "xxs", "color": "#888888"})

        # Current batter stats
        batter_rows = []
        if current_ab.get("hitter"):
            hitter_name = current_ab["hitter"]
            batters = g.get("batters", [])
            hitter_data = next((b for b in batters if b.get("name") == hitter_name), None)
            if hitter_data:
                stats = f"{hitter_data.get('hits',0)}/{hitter_data.get('pa',0)}"
                if hitter_data.get("hr", 0) > 0:
                    stats += f" {hitter_data['hr']}轟"
                if hitter_data.get("rbi", 0) > 0:
                    stats += f" {hitter_data['rbi']}打點"
                if hitter_data.get("runs", 0) > 0:
                    stats += f" {hitter_data['runs']}得分"
                batter_rows.append({
                    "type": "box", "layout": "horizontal",
                    "contents": [
                        {"type": "text", "text": f"🏏 {hitter_name}", "size": "xs", "color": "#E74C3C", "flex": 3},
                        {"type": "text", "text": stats, "size": "xs", "color": "#FFFFFF", "align": "end", "flex": 4, "weight": "bold"},
                    ],
                })

        # Weather + audience
        weather = g.get("weather", "")
        audience = g.get("audience", 0)
        info_text = ""
        if weather:
            # Shorten weather
            info_text = weather.split("。")[0] if "。" in weather else weather[:20]
        if audience and audience > 0:
            info_text += f"  👤{audience:,}"

        bubble = {
            "type": "bubble",
            "size": "mega",
            "body": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#1B2838",
                "paddingAll": "12px",
                "contents": [
                    # Status + venue
                    {
                        "type": "box", "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": status_text or "進行中", "size": "xs",
                             "color": "#F39C12" if "進行" in (status_text or "進行中") else "#27AE60", "weight": "bold", "flex": 2},
                            {"type": "text", "text": g.get("venue", "") or " ", "size": "xxs", "color": "#888888", "align": "end", "flex": 3},
                        ],
                    },
                    # Weather + audience
                    *(
                        [{"type": "text", "text": info_text, "size": "xxs", "color": "#666666", "margin": "xs"}]
                        if info_text else []
                    ),
                    {"type": "separator", "margin": "sm", "color": "#333333"},
                    # Score
                    *scoreboard_rows,
                    # Current at-bat
                    *(current_rows if current_rows else []),
                    {"type": "separator", "margin": "sm", "color": "#333333"},
                    # Pitchers
                    *(
                        [{"type": "text", "text": "投手", "size": "xs", "color": "#3498DB", "weight": "bold", "margin": "md"}]
                        + pitcher_rows if pitcher_rows else []
                    ),
                    {"type": "separator", "margin": "sm", "color": "#333333"},
                    # Current batter
                    *(
                        [{"type": "text", "text": "打席中", "size": "xs", "color": "#E74C3C", "weight": "bold", "margin": "md"}]
                        + batter_rows if batter_rows else []
                    ),
                ],
            },
        }
        bubbles.append(bubble)

    return {
        "type": "flex",
        "altText": "即時比分",
        "contents": {
            "type": "carousel",
            "contents": bubbles[:10],
        },
    }


def build_balance(user: dict) -> dict:
    """Build balance overview card."""
    from datetime import date
    today = date.today().isoformat()

    balance = user.get("balance", 0)
    total_deposited = user.get("total_deposited", 0)
    total_wagered = user.get("total_wagered", 0)
    total_won = user.get("total_won", 0)
    total_profit = user.get("total_profit", 0)
    profit_sign = "+" if total_profit >= 0 else ""
    profit_color = "#27AE60" if total_profit >= 0 else "#E74C3C"

    # Only show today's totals if the date matches
    today_deposit = user.get("deposit_today_total", 0) if user.get("deposit_today_date") == today else 0
    today_bet = user.get("bet_today_total", 0) if user.get("bet_today_date") == today else 0

    # 30-day deposit total
    from app.db import tx_repo
    month_deposit = tx_repo.sum_deposits_last_30_days(user.get("id", ""))

    return {
        "type": "flex",
        "altText": "餘額",
        "contents": {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    # Balance header
                    {
                        "type": "text",
                        "text": "帳戶餘額",
                        "size": "sm",
                        "color": "#888888",
                    },
                    {
                        "type": "text",
                        "text": f"${balance:,}",
                        "size": "3xl",
                        "weight": "bold",
                        "color": "#333333",
                        "margin": "sm",
                    },
                    {"type": "separator", "margin": "xl"},
                    # Today's limits
                    {
                        "type": "text",
                        "text": "今日額度",
                        "size": "sm",
                        "color": "#888888",
                        "margin": "xl",
                        "weight": "bold",
                    },
                    _kv_row("今日已儲值", f"{today_deposit:,} / 10,000"),
                    _kv_row("今日已下注", f"{today_bet:,} / 10,000"),
                    _kv_row("30天已儲值", f"{month_deposit:,} / 100,000"),
                    {"type": "separator", "margin": "xl"},
                    # Lifetime stats
                    {
                        "type": "text",
                        "text": "累計紀錄",
                        "size": "sm",
                        "color": "#888888",
                        "margin": "xl",
                        "weight": "bold",
                    },
                    _kv_row("累計儲值", f"{total_deposited:,} 元"),
                    _kv_row("累計下注", f"{total_wagered:,} 元"),
                    _kv_row("累計獎金", f"{total_won:,} 元"),
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "累計損益", "size": "sm", "color": "#888888", "flex": 2},
                            {"type": "text", "text": f"{profit_sign}{total_profit:,} 元",
                             "size": "sm", "color": profit_color, "align": "end", "weight": "bold", "flex": 3},
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
                            "type": "message",
                            "label": "儲值",
                            "text": "儲值",
                        },
                        "style": "primary",
                        "color": "#D35400",
                    },
                    {
                        "type": "button",
                        "action": {
                            "type": "message",
                            "label": "今日賽事",
                            "text": "今日賽事",
                        },
                        "style": "primary",
                        "color": "#2C3E50",
                    },
                ],
            },
        },
    }


def build_insufficient_balance(balance: int, amount: int) -> dict:
    """Build insufficient balance card with deposit button."""
    shortage = amount - balance
    return {
        "type": "flex",
        "altText": "餘額不足",
        "contents": {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "❌ 餘額不足", "weight": "bold", "size": "lg", "color": "#E74C3C"},
                    {"type": "separator", "margin": "lg"},
                    {
                        "type": "box",
                        "layout": "vertical",
                        "margin": "lg",
                        "spacing": "sm",
                        "contents": [
                            _kv_row("目前餘額", f"{balance:,} 元"),
                            _kv_row("下注金額", f"{amount:,} 元"),
                            _kv_row("還差", f"{shortage:,} 元"),
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
                            "type": "message",
                            "label": "去儲值",
                            "text": "儲值",
                        },
                        "style": "primary",
                        "color": "#D35400",
                    },
                    {
                        "type": "button",
                        "action": {
                            "type": "message",
                            "label": "查看餘額",
                            "text": "餘額",
                        },
                        "style": "secondary",
                    },
                ],
            },
        },
    }


def build_help() -> dict:
    """Build help as carousel - one card per feature."""
    features = [
        {
            "title": "🎰 下注規則",
            "command": "今日賽事",
            "color": "#8E44AD",
            "desc": "• 每日下注上限: 10,000\n• 最低下注: 1 元\n• 餘額不足不能下注\n• 儲值每日上限: 10,000\n• 儲值每月上限: 100,000\n• 開賽後封盤\n• 延賽全額退款\n• 每日午夜自動結算\n• 賠率由 AI 動態生成",
        },
        {
            "title": "🏟️ 今日賽事",
            "command": "今日賽事",
            "color": "#2C3E50",
            "desc": "查看今天的 CPBL 比賽，每場有 AI 動態生成的下注盤口。點擊賠率按鈕即可下注。",
        },
        {
            "title": "⚡ 即時賽事",
            "command": "即時賽事",
            "color": "#C0392B",
            "desc": "查看進行中的比賽即時比分，包含逐局分數和投手數據。每 2 分鐘可查詢一次。",
        },
        {
            "title": "📋 近期賽果",
            "command": "近期賽果",
            "color": "#34495E",
            "desc": "查看近 3 天已完成的比賽結果，含比分和球隊 logo。",
        },
        {
            "title": "📅 未來賽事",
            "command": "未來賽事",
            "color": "#616A6B",
            "desc": "查看未來 7 天的賽程表，包含對戰組合、球場和開賽時間。",
        },
        {
            "title": "📊 球隊戰績",
            "command": "球隊戰績",
            "color": "#1A5276",
            "desc": "查看 CPBL 即時排名，含勝敗、勝率、團隊 ERA 和近 10 場戰績。",
        },
        {
            "title": "💰 儲值",
            "command": "儲值",
            "color": "#D35400",
            "desc": "儲值虛擬幣到帳戶。\n• 每日上限: 10,000\n• 每月上限: 100,000",
        },
        {
            "title": "💵 餘額",
            "command": "餘額",
            "color": "#2C3E50",
            "desc": "查看帳戶餘額、今日額度使用狀況、30天儲值額度和累計損益。",
        },
        {
            "title": "📑 我的注單",
            "command": "我的注單",
            "color": "#2471A3",
            "desc": "查看最近的下注紀錄，含結算狀態和結算理由。",
        },
        {
            "title": "🏆 排行榜",
            "command": "排行榜",
            "color": "#8E44AD",
            "desc": "查看獲利 TOP 10 排名、你的排名和莊家獲利。",
        },
    ]

    bubbles = []
    for f in features:
        bubbles.append({
            "type": "bubble",
            "size": "kilo",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": f["color"],
                "paddingAll": "15px",
                "contents": [
                    {"type": "text", "text": f["title"], "color": "#FFFFFF", "weight": "bold", "size": "lg"},
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "paddingAll": "15px",
                "contents": [
                    {"type": "text", "text": f["desc"], "size": "sm", "color": "#555555", "wrap": True},
                ],
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "button",
                        "action": {"type": "message", "label": f["command"], "text": f["command"]},
                        "style": "primary",
                        "color": f["color"],
                        "height": "sm",
                    },
                ],
            },
        })

    return {
        "type": "flex",
        "altText": "使用說明",
        "contents": {
            "type": "carousel",
            "contents": bubbles[:10],
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


def _quick_bet_button(amount: int) -> dict:
    return {
        "type": "button",
        "action": {
            "type": "message",
            "label": f"{amount:,}",
            "text": str(amount),
        },
        "style": "secondary",
        "height": "sm",
        "flex": 1,
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
