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
from app.firebase import user_repo, game_repo, bet_repo
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
    games = game_repo.get_games_by_date(today)

    if not games:
        _reply(event.reply_token, ["今日沒有賽事，明天再來！"])
        return

    carousel = flex_messages.build_games_carousel(games)
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

    import httpx
    from app.scraper.cpbl_standings import _parse_standings_html, _default_standings
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Accept-Language": "zh-TW,zh;q=0.9",
            "Referer": "https://www.cpbl.com.tw/",
        }
        r = httpx.get("https://www.cpbl.com.tw/standings/season", headers=headers, follow_redirects=True, timeout=15)
        r.raise_for_status()
        standings = _parse_standings_html(r.text)
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
