"""LINE Bot webhook handler with conversation state machine."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    FlexMessage,
    FlexContainer,
    TextMessage,
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    PostbackEvent,
    FollowEvent,
)

from app.config import settings
from app.db import user_repo, game_repo, bet_repo
from app.betting import bet_service
from app.line_bot.commands import parse_text_command, parse_postback
from app.line_bot import flex_messages

logger = logging.getLogger(__name__)

# In-memory conversation state
_user_states: dict[str, dict] = {}

configuration = Configuration(access_token=settings.line_channel_access_token)


def _get_api() -> MessagingApi:
    return MessagingApi(ApiClient(configuration))


def _reply(reply_token: str, messages: list):
    """Send reply messages."""
    api = _get_api()
    line_messages = []
    for msg in messages:
        if isinstance(msg, dict):
            if msg.get("type") == "flex":
                line_messages.append(
                    FlexMessage(
                        alt_text=msg.get("altText", "訊息"),
                        contents=FlexContainer.from_dict(msg["contents"]),
                    )
                )
            elif msg.get("type") == "text":
                line_messages.append(TextMessage(text=msg["text"]))
        elif isinstance(msg, str):
            line_messages.append(TextMessage(text=msg))

    if line_messages:
        api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=line_messages[:5],  # LINE max 5 messages per reply
            )
        )


def _set_state(user_id: str, state: str, context: dict | None = None):
    _user_states[user_id] = {
        "state": state,
        "context": context or {},
        "expires_at": datetime.now() + timedelta(minutes=10),
    }


def _get_state(user_id: str) -> dict | None:
    s = _user_states.get(user_id)
    if s and s.get("expires_at", datetime.min) > datetime.now():
        return s
    _user_states.pop(user_id, None)
    return None


def _clear_state(user_id: str):
    _user_states.pop(user_id, None)


# --- Event Handlers ---

def handle_follow(event: FollowEvent):
    """User adds the bot as friend."""
    user_id = event.source.user_id
    api = _get_api()
    try:
        profile = api.get_profile(user_id)
        display_name = profile.display_name
    except Exception:
        display_name = "玩家"

    user_repo.get_or_create_user(user_id, display_name)
    _reply(event.reply_token, [
        f"歡迎 {display_name} 加入 CPBL 虛擬下注！⚾\n\n"
        "這是一個中華職棒虛擬投注平台，\n"
        "賠率由 AI 根據每日數據動態生成！\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📌 指令列表\n"
        "━━━━━━━━━━━━━━━\n"
        "🏟️ 今日賽事 - 查看比賽和下注\n"
        "💰 儲值 - 儲值虛擬幣\n"
        "📊 我的戰績 - 查看個人紀錄\n"
        "🏆 排行榜 - 獲利排行 TOP 10\n"
        "📋 我的注單 - 查看下注紀錄\n"
        "❓ 說明 - 完整使用說明\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📌 規則\n"
        "━━━━━━━━━━━━━━━\n"
        "• 儲值上限: 每日 10,000 / 30天 100,000\n"
        "• 下注上限: 每日 10,000，最低 1 元\n"
        "• 餘額不足不能下注\n"
        "• 延賽全額退款\n"
        "• 每日午夜自動結算\n\n"
        "輸入「儲值」開始你的第一筆入金吧！"
    ])


def handle_text_message(event: MessageEvent):
    """Handle text messages."""
    user_id = event.source.user_id
    text = event.message.text.strip()

    # Ensure user exists
    api = _get_api()
    try:
        profile = api.get_profile(user_id)
        display_name = profile.display_name
    except Exception:
        display_name = "玩家"
    user_repo.get_or_create_user(user_id, display_name)

    # Check if user is in a conversation state
    state = _get_state(user_id)
    if state:
        _handle_state_input(event, user_id, text, state)
        return

    # Parse command
    cmd = parse_text_command(text)
    if cmd == "games":
        _handle_games(event, user_id)
    elif cmd == "deposit":
        _handle_deposit_menu(event, user_id)
    elif cmd == "leaderboard":
        _handle_leaderboard(event, user_id)
    elif cmd == "stats":
        _handle_stats(event, user_id)
    elif cmd == "my_bets":
        _handle_my_bets(event, user_id)
    elif cmd == "standings":
        _handle_standings(event)
    elif cmd == "recent_results":
        _handle_recent_results(event)
    elif cmd == "upcoming":
        _handle_upcoming(event)
    elif cmd == "live":
        _handle_live(event, user_id)
    elif cmd == "help":
        _handle_help(event)
    else:
        _reply(event.reply_token, [
            "我不太懂你的意思 😅\n\n"
            "試試以下指令:\n"
            "🏟️ 今日賽事\n"
            "💰 儲值\n"
            "📊 我的戰績\n"
            "🏆 排行榜\n"
            "⚾ 球隊戰績\n"
            "📋 我的注單\n"
            "❓ 說明"
        ])


def handle_postback(event: PostbackEvent):
    """Handle postback events from buttons."""
    user_id = event.source.user_id
    data = parse_postback(event.postback.data)

    # Ensure user exists
    user_repo.get_or_create_user(user_id)

    if data.action == "bet":
        _handle_bet_select(event, user_id, data.params)
    elif data.action == "confirm_bet":
        _handle_bet_confirm(event, user_id)
    elif data.action == "cancel_bet":
        _clear_state(user_id)
        _reply(event.reply_token, [flex_messages.build_error_message("已取消下注")])
    elif data.action == "deposit":
        _handle_deposit(event, user_id, data.params)
    elif data.action == "deposit_custom":
        _set_state(user_id, "awaiting_deposit_amount")
        _reply(event.reply_token, ["請輸入儲值金額 (1 ~ 10,000):"])
    elif data.action == "games":
        _handle_games(event, user_id)


# --- Command Handlers ---

def _handle_games(event, user_id: str):
    from datetime import date
    today = date.today().isoformat()
    all_games = game_repo.get_games_by_date(today)
    scheduled = [g for g in all_games if g.get("status") == "scheduled"]

    if not scheduled:
        if all_games:
            _reply(event.reply_token, ["今日賽事已全部結束。"])
        else:
            _reply(event.reply_token, ["今日沒有賽事，明天再來！"])
        return

    # Mark which games can still be bet on (before game time)
    now = datetime.now()
    for g in scheduled:
        game_time = g.get("game_time", "")
        can_bet = True
        if game_time:
            try:
                hour, minute = int(game_time.split(":")[0]), int(game_time.split(":")[1])
                game_start = now.replace(hour=hour, minute=minute, second=0)
                if now >= game_start:
                    can_bet = False
            except (ValueError, IndexError):
                pass
        g["_can_bet"] = can_bet

    carousel = flex_messages.build_games_carousel(scheduled)
    _reply(event.reply_token, [carousel])


def _handle_deposit_menu(event, user_id: str):
    user = user_repo.get_user(user_id)
    if not user:
        _reply(event.reply_token, [flex_messages.build_error_message("請先加入好友")])
        return
    menu = flex_messages.build_deposit_menu(user)
    _reply(event.reply_token, [menu])


def _handle_deposit(event, user_id: str, params: list):
    if not params:
        return
    try:
        amount = int(params[0])
    except ValueError:
        _reply(event.reply_token, [flex_messages.build_error_message("無效金額")])
        return

    result = bet_service.deposit(user_id, amount)
    if result["success"]:
        _reply(event.reply_token, [flex_messages.build_success_message(result["message"])])
    else:
        _reply(event.reply_token, [flex_messages.build_error_message(result["error"])])


def _handle_leaderboard(event, user_id: str):
    top_users = user_repo.get_top_users_by_profit(10)
    user = user_repo.get_user(user_id) or {}

    # Calculate house profit: sum of all users' negative profit
    all_profits = sum(u.get("total_profit", 0) for u in top_users)
    # House profit = total wagered - total won across all users (approximation from top users)
    house_profit = -all_profits  # simplified

    lb = flex_messages.build_leaderboard(top_users, user, house_profit)
    _reply(event.reply_token, [lb])


def _handle_stats(event, user_id: str):
    user = user_repo.get_user(user_id)
    if not user:
        _reply(event.reply_token, [flex_messages.build_error_message("請先加入好友")])
        return
    recent = bet_repo.get_user_bets(user_id, limit=5)
    stats = flex_messages.build_stats(user, recent)
    _reply(event.reply_token, [stats])


_standings_cache: dict = {"data": None, "updated_at": None}


def _get_standings_cached() -> dict:
    """Get standings with 30-min cache."""
    now = datetime.now()
    if (_standings_cache["data"]
            and _standings_cache["updated_at"]
            and (now - _standings_cache["updated_at"]).seconds < 1800):
        return _standings_cache["data"]

    from app.scraper.cpbl_standings import _parse_standings_html, _default_standings
    from app.db.client import get_db
    try:
        # Try DB cache first
        db = get_db()
        cached = db["cache"].find_one({"_id": "standings"})
        if cached and cached.get("data"):
            standings = cached["data"]
        else:
            # Fallback: scrape synchronously
            import httpx
            from app.scraper.http_client import _browser_headers
            r = httpx.get("https://en.cpbl.com.tw/standings/season",
                         headers=_browser_headers("https://en.cpbl.com.tw/"),
                         follow_redirects=True, timeout=15)
            if r.status_code == 200:
                standings = _parse_standings_html(r.text)
                db["cache"].update_one({"_id": "standings"}, {"$set": {"data": standings}}, upsert=True)
            else:
                standings = _default_standings()
    except Exception:
        standings = _default_standings()

    _standings_cache["data"] = standings
    _standings_cache["updated_at"] = now
    return standings


def _handle_standings(event):
    standings = _get_standings_cached()
    if not standings:
        _reply(event.reply_token, [flex_messages.build_error_message("無法取得戰績資料")])
        return
    msg = flex_messages.build_standings(standings)
    _reply(event.reply_token, [msg])


def _handle_upcoming(event):
    """Show upcoming 7-day schedule from DB cache."""
    from app.db.client import get_db
    from datetime import date, timedelta

    db = get_db()
    cached = db["cache"].find_one({"_id": "upcoming_schedule"})

    if cached and cached.get("data"):
        games_by_date = cached["data"]
    else:
        _reply(event.reply_token, [flex_messages.build_error_message("尚未載入賽程，請等待每日排程更新。")])
        return

    if not games_by_date:
        _reply(event.reply_token, ["未來七天沒有賽事"])
        return

    msg = flex_messages.build_upcoming_schedule(games_by_date)
    _reply(event.reply_token, [msg])


_live_rate_limit: dict[str, datetime] = {}  # user_id -> last request time


def _handle_live(event, user_id: str):
    """Show live scores with 2-min per-user rate limit."""
    import json
    import re
    from app.db.client import get_db
    from app.scraper.cpbl_schedule import _to_chinese_name, _to_chinese_venue

    # Rate limit: 2 minutes per user
    now = datetime.now()
    last = _live_rate_limit.get(user_id)
    if last and (now - last).total_seconds() < 120:
        remaining = 120 - int((now - last).total_seconds())
        _reply(event.reply_token, [flex_messages.build_error_message(f"請等 {remaining} 秒後再查詢即時比分")])
        return

    # Check DB cache first (shared across users, 2 min TTL)
    db = get_db()
    cached = db["cache"].find_one({"_id": "live_scores"})
    if cached and cached.get("updated_at"):
        cache_age = (now - cached["updated_at"]).total_seconds()
        if cache_age < 120 and cached.get("data"):
            _live_rate_limit[user_id] = now
            if not cached["data"]:
                _reply(event.reply_token, ["目前沒有進行中的比賽"])
                return
            msg = flex_messages.build_live_scores(cached["data"])
            _reply(event.reply_token, [msg])
            return

    # Scrape fresh live data
    try:
        import httpx
        from app.scraper.http_client import _browser_headers

        headers = _browser_headers("https://en.cpbl.com.tw/")

        # Get today's game SNOs from DB
        today_str = now.strftime("%Y-%m-%d")
        today_games = list(db["games"].find({"date": today_str}))

        if not today_games:
            _live_rate_limit[user_id] = now
            _reply(event.reply_token, ["今日沒有賽事"])
            return

        # Get token from box page
        r = httpx.get("https://en.cpbl.com.tw/box", headers=headers, follow_redirects=True, timeout=15)
        token_match = re.search(r'__RequestVerificationToken.*?value="([^"]+)"', r.text)
        if not token_match:
            token_match = re.search(r"RequestVerificationToken:\s*'([A-Za-z0-9_\-:]+)'", r.text)
        token = token_match.group(1) if token_match else ""

        live_games = []
        for game in today_games:
            sno = game.get("game_sno")
            if not sno:
                continue

            try:
                r2 = httpx.post(
                    "https://en.cpbl.com.tw/box/getlive",
                    data={"gameSno": str(sno), "year": str(now.year), "kindCode": "A"},
                    headers={
                        **headers,
                        "RequestVerificationToken": token,
                        "X-Requested-With": "XMLHttpRequest",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    cookies=dict(r.cookies),
                    follow_redirects=True,
                    timeout=15,
                )

                if r2.status_code != 200:
                    continue

                data = r2.json()
                gd_list = json.loads(data.get("GameDetailJson", "[]"))
                if not gd_list:
                    continue
                gd = gd_list[0] if isinstance(gd_list, list) else gd_list

                # Parse scoreboard
                sb_list = json.loads(data.get("ScoreboardJson", "[]"))
                away_inn = {}
                home_inn = {}
                for item in sb_list:
                    inning = item.get("Inning", 0)
                    score = item.get("Score", 0) or 0
                    vh = item.get("VisitingHomeType", 0)
                    if vh == 1:
                        away_inn[inning] = score
                    elif vh == 2:
                        home_inn[inning] = score

                max_inning = max(list(away_inn.keys()) + list(home_inn.keys()) + [0])
                away_scores = [away_inn.get(i, 0) for i in range(1, max_inning + 1)]
                home_scores = [home_inn.get(i, 0) for i in range(1, max_inning + 1)]

                # Parse pitchers
                pitching_list = json.loads(data.get("PitchingJson", "[]"))
                pitchers = []
                for p in pitching_list[:4]:
                    pitchers.append({
                        "name": p.get("PitcherName", "") or p.get("PlayerName", ""),
                        "team": "home" if p.get("VisitingHomeType") == 2 else "away",
                        "ip": f"{p.get('InningPitchedCnt', 0) or 0}.{p.get('InningPitchedDiv3Cnt', 0) or 0}",
                        "strikeouts": p.get("StrikeOutCnt", 0) or 0,
                    })

                # Determine status text
                game_status = gd.get("GameStatusChi", "")
                if not game_status:
                    gs_code = gd.get("GameStatus", 0)
                    game_status = {0: "未開始", 1: "比賽中", 2: "比賽中", 3: "比賽結束"}.get(gs_code, "")

                live_games.append({
                    "away_team_name": _to_chinese_name(gd.get("VisitingTeamName", "")),
                    "home_team_name": _to_chinese_name(gd.get("HomeTeamName", "")),
                    "away_score": gd.get("VisitingTotalScore", 0) or 0,
                    "home_score": gd.get("HomeTotalScore", 0) or 0,
                    "venue": _to_chinese_venue(gd.get("FieldAbbe", game.get("venue", ""))),
                    "status_text": game_status,
                    "innings": {"away": away_scores, "home": home_scores},
                    "pitchers": pitchers,
                })

            except Exception as e:
                logger.warning(f"Live score failed for sno {sno}: {e}")

        # Cache for 2 min
        db["cache"].update_one(
            {"_id": "live_scores"},
            {"$set": {"data": live_games, "updated_at": now}},
            upsert=True,
        )

        _live_rate_limit[user_id] = now

        if not live_games:
            _reply(event.reply_token, ["目前沒有進行中的比賽"])
            return

        msg = flex_messages.build_live_scores(live_games)
        _reply(event.reply_token, [msg])

    except Exception as e:
        logger.error(f"Live score error: {e}")
        _reply(event.reply_token, [flex_messages.build_error_message("無法取得即時比分")])


def _handle_recent_results(event):
    """Show recent 3 days game results from MongoDB."""
    from app.db.client import get_db
    from datetime import date, timedelta
    db = get_db()

    three_days_ago = (date.today() - timedelta(days=3)).isoformat()

    recent = list(
        db["games"]
        .find({
            "status": {"$in": ["final", "postponed"]},
            "date": {"$gte": three_days_ago},
        })
        .sort("date", -1)
    )

    if not recent:
        _reply(event.reply_token, ["目前沒有已完成的比賽紀錄，請等待每日排程更新。"])
        return

    msg = flex_messages.build_recent_results(recent)
    _reply(event.reply_token, [msg])


def _handle_my_bets(event, user_id: str):
    bets = bet_repo.get_user_bets(user_id, limit=10)
    if not bets:
        _reply(event.reply_token, ["你還沒有下注紀錄，輸入「今日賽事」開始玩！"])
        return

    msg = flex_messages.build_my_bets(bets)
    _reply(event.reply_token, [msg])


def _handle_help(event):
    _reply(event.reply_token, [
        "🏟️ CPBL 虛擬下注 使用說明\n\n"
        "【指令】\n"
        "今日賽事 - 查看今天的比賽和下注盤口\n"
        "儲值 - 儲值虛擬幣到帳戶\n"
        "我的戰績 - 查看餘額、勝率、獲利\n"
        "排行榜 - 獲利前 10 名 + 莊家獲利\n"
        "我的注單 - 查看最近下注紀錄\n"
        "球隊戰績 - CPBL 即時戰績排名\n\n"
        "【規則】\n"
        "• 儲值上限: 每日 10,000 / 30天 100,000\n"
        "• 下注上限: 每日 10,000，最低 1 元\n"
        "• 餘額不足不能下注\n"
        "• 延賽全額退款\n"
        "• 每日午夜自動結算\n\n"
        "⚾ 賠率由 AI 根據當日數據動態生成！"
    ])


# --- Bet Flow ---

def _handle_bet_select(event, user_id: str, params: list):
    """User tapped a bet button on game card. params: [game_id, market_idx, selection, odds]"""
    if len(params) < 4:
        _reply(event.reply_token, [flex_messages.build_error_message("無效操作")])
        return

    game_id, market_idx_str, selection, odds_str = params[0], params[1], params[2], params[3]

    try:
        market_idx = int(market_idx_str)
        odds = float(odds_str)
    except ValueError:
        _reply(event.reply_token, [flex_messages.build_error_message("無效操作")])
        return

    game = game_repo.get_game(game_id)
    if not game:
        _reply(event.reply_token, [flex_messages.build_error_message("找不到比賽")])
        return

    if game.get("status") != "scheduled":
        _reply(event.reply_token, [flex_messages.build_error_message("比賽已開始或結束")])
        return

    markets = game.get("odds", {}).get("markets", [])
    market_name = markets[market_idx]["name"] if market_idx < len(markets) else "未知"

    user = user_repo.get_user(user_id)
    balance = user.get("balance", 0) if user else 0

    # Set state: awaiting amount
    _set_state(user_id, "awaiting_bet_amount", {
        "game_id": game_id,
        "market_index": market_idx,
        "market_name": market_name,
        "selection": selection,
        "odds": odds,
    })

    confirm_msg = flex_messages.build_bet_confirm(game, market_name, selection, odds, balance)
    _reply(event.reply_token, [confirm_msg])


def _handle_state_input(event, user_id: str, text: str, state: dict):
    """Handle input when user is in a conversation state."""
    s = state["state"]
    ctx = state["context"]

    if s == "awaiting_bet_amount":
        try:
            amount = int(text)
        except ValueError:
            _reply(event.reply_token, ["請輸入數字金額:"])
            return

        if amount < 1:
            _reply(event.reply_token, ["最低下注 1 元，請重新輸入:"])
            return

        # Store amount, move to confirm state
        ctx["amount"] = amount
        _set_state(user_id, "awaiting_bet_confirm", ctx)

        game = game_repo.get_game(ctx["game_id"])
        if not game:
            _clear_state(user_id)
            _reply(event.reply_token, [flex_messages.build_error_message("找不到比賽")])
            return

        confirm = flex_messages.build_bet_final_confirm(
            game, ctx["market_name"], ctx["selection"], ctx["odds"], amount
        )
        _reply(event.reply_token, [confirm])

    elif s == "awaiting_deposit_amount":
        try:
            amount = int(text)
        except ValueError:
            _reply(event.reply_token, ["請輸入數字金額:"])
            return

        _clear_state(user_id)
        result = bet_service.deposit(user_id, amount)
        if result["success"]:
            _reply(event.reply_token, [flex_messages.build_success_message(result["message"])])
        else:
            _reply(event.reply_token, [flex_messages.build_error_message(result["error"])])

    else:
        _clear_state(user_id)
        _reply(event.reply_token, ["操作已過期，請重新開始。"])


def _handle_bet_confirm(event, user_id: str):
    """User confirmed the bet."""
    state = _get_state(user_id)
    if not state or state["state"] != "awaiting_bet_confirm":
        _reply(event.reply_token, [flex_messages.build_error_message("操作已過期，請重新下注")])
        return

    ctx = state["context"]
    _clear_state(user_id)

    result = bet_service.place_bet(
        user_id=user_id,
        game_id=ctx["game_id"],
        market_index=ctx["market_index"],
        selection=ctx["selection"],
        odds=ctx["odds"],
        amount=ctx["amount"],
    )

    if result["success"]:
        _reply(event.reply_token, [flex_messages.build_success_message(result["message"])])
    else:
        _reply(event.reply_token, [flex_messages.build_error_message(result["error"])])
