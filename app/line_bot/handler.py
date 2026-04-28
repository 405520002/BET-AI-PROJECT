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
from app.db import user_repo, game_repo, bet_repo, whitelist_repo
from app.betting import bet_service
from app.line_bot.commands import parse_text_command, parse_postback
from app.line_bot import flex_messages

logger = logging.getLogger(__name__)

# In-memory conversation state
_user_states: dict[str, dict] = {}

configuration = Configuration(access_token=settings.line_channel_access_token)


def _get_api() -> MessagingApi:
    return MessagingApi(ApiClient(configuration))


def _is_allowed(user_id: str) -> bool:
    """Whitelist gate. Empty whitelist collection = allow everyone."""
    return whitelist_repo.is_whitelisted(user_id)


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
    # Log userId so the operator can add it to the whitelist if desired
    logger.info(f"FollowEvent userId={user_id}")

    if not _is_allowed(user_id):
        _reply(event.reply_token, [
            "感謝加入，但此服務目前僅限受邀使用者 🔒\n"
            "如需使用，請聯繫管理員開通。"
        ])
        return

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

    if not _is_allowed(user_id):
        _reply(event.reply_token, ["此服務目前僅限受邀使用者 🔒"])
        return

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
    elif cmd == "balance":
        _handle_balance(event, user_id)
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

    if not _is_allowed(user_id):
        _reply(event.reply_token, ["此服務目前僅限受邀使用者 🔒"])
        return

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
    elif data.action == "bets_pending":
        _handle_bets_pending(event, user_id)
    elif data.action == "bets_settled":
        _handle_bets_settled(event, user_id)


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


def _handle_balance(event, user_id: str):
    user = user_repo.get_user(user_id)
    if not user:
        _reply(event.reply_token, [flex_messages.build_error_message("請先加入好友")])
        return
    msg = flex_messages.build_balance(user)
    _reply(event.reply_token, [msg])


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

    from app.scraper.cpbl_standings import _default_standings
    from app.db.client import get_db
    try:
        # /standings/season is blocked from datacenter ASNs at HiNet's CDN edge,
        # so the only path to fresh data is db.cache.standings, populated daily
        # by the iPhone Shortcut residential relay (POST /ingest/standings).
        # If the cache is empty (iPhone hasn't pushed yet today), fall through
        # to the all-zero default so the UI still renders.
        db = get_db()
        cached = db["cache"].find_one({"_id": "standings"})
        if cached and cached.get("data"):
            standings = cached["data"]
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
    if last and (now - last).total_seconds() < 10:
        remaining = 10 - int((now - last).total_seconds())
        _reply(event.reply_token, [flex_messages.build_error_message(f"請等 {remaining} 秒後再查詢即時比分")])
        return

    db = get_db()

    # Reply immediately (scraping takes time)
    _reply(event.reply_token, ["⚾ 查詢即時比分中..."])

    # Scrape fresh live data
    try:
        from app.scraper.http_client import get_cpbl_session_sync, _ajax_headers, _browser_headers
        import time as _time
        import random as _random

        today_str = now.strftime("%Y-%m-%d")
        today_games = list(db["games"].find({"date": today_str}))

        if not today_games:
            _live_rate_limit[user_id] = now
            _reply(event.reply_token, ["今日沒有賽事"])
            return

        # Create session with anti-scraping
        client = get_cpbl_session_sync("https://www.cpbl.com.tw")

        try:
            # Get token from /box/index?gameSno=... — the bare /box path is
            # blocked from datacenter ASNs (HiNet CDN) but /box/index with a
            # gameSno query is whitelisted. Seed with any of today's snos.
            seed_sno = next((g.get("game_sno") for g in today_games if g.get("game_sno")), None)
            if not seed_sno:
                _live_rate_limit[user_id] = now
                _reply(event.reply_token, ["今日沒有賽事"])
                return
            box_index_url = f"https://www.cpbl.com.tw/box/index?gameSno={seed_sno}&year={now.year}&kindCode=A"
            headers = _browser_headers("https://www.cpbl.com.tw/")
            _time.sleep(_random.uniform(0.3, 0.8))
            r = client.get(box_index_url, headers=headers)

            token_match = re.search(r"RequestVerificationToken:\s*'([A-Za-z0-9_\-:]+)'", r.text)
            if not token_match:
                token_match = re.search(r'__RequestVerificationToken.*?value="([^"]+)"', r.text)
            token = token_match.group(1) if token_match else ""

            live_games = []
            for game in today_games:
                sno = game.get("game_sno")
                if not sno:
                    continue

                try:
                    ajax_h = _ajax_headers(box_index_url, token)
                    _time.sleep(_random.uniform(0.3, 0.8))
                    r2 = client.post(
                        "https://www.cpbl.com.tw/box/getlive",
                        data={"gameSno": str(sno), "year": str(now.year), "kindCode": "A"},
                        headers=ajax_h,
                    )

                    if r2.status_code != 200:
                        continue

                    data = r2.json()
                    # Use CurtGameDetailJson (has team names) over GameDetailJson (often null)
                    curt_raw = data.get("CurtGameDetailJson") or "{}"
                    gd = json.loads(curt_raw) if isinstance(curt_raw, str) else (curt_raw or {})
                    if not gd or not gd.get("VisitingTeamName"):
                        # Fallback to GameDetailJson
                        gd_raw = data.get("GameDetailJson") or "[]"
                        gd_list = json.loads(gd_raw) if isinstance(gd_raw, str) else (gd_raw or [])
                        if not gd_list:
                            continue
                        gd = gd_list[0] if isinstance(gd_list, list) else gd_list

                    # Parse scoreboard
                    sb_raw = data.get("ScoreboardJson") or "[]"
                    sb_list = json.loads(sb_raw) if isinstance(sb_raw, str) else (sb_raw or [])
                    away_inn = {}
                    home_inn = {}
                    away_total_hits = 0
                    home_total_hits = 0
                    away_total_errors = 0
                    home_total_errors = 0
                    for item in sb_list:
                        inning = int(float(item.get("InningSeq", 0) or item.get("Inning", 0) or 0))
                        score = int(float(item.get("ScoreCnt", 0) or item.get("Score", 0) or 0))
                        hits = int(float(item.get("HittingCnt", 0) or 0))
                        errors = int(float(item.get("ErrorCnt", 0) or 0))
                        vh = int(float(item.get("VisitingHomeType", 0) or 0))
                        if vh == 1:
                            away_inn[inning] = score
                            away_total_hits += hits
                            away_total_errors += errors
                        elif vh == 2:
                            home_inn[inning] = score
                            home_total_hits += hits
                            home_total_errors += errors

                    max_inning = max(list(away_inn.keys()) + list(home_inn.keys()) + [0])
                    away_scores = [away_inn.get(i, 0) for i in range(1, max_inning + 1)]
                    home_scores = [home_inn.get(i, 0) for i in range(1, max_inning + 1)]

                    # Parse pitchers
                    pitch_raw = data.get("PitchingJson") or "[]"
                    pitching_list = json.loads(pitch_raw) if isinstance(pitch_raw, str) else (pitch_raw or [])
                    pitchers = []
                    for p in pitching_list[:4]:
                        vh = int(float(p.get("VisitingHomeType", 0) or 0))
                        pitchers.append({
                            "name": p.get("PitcherName", "") or p.get("PlayerName", ""),
                            "team": "home" if vh == 2 else "away",
                            "ip": f"{int(p.get('InningPitchedCnt', 0) or 0)}.{int(p.get('InningPitchedDiv3Cnt', 0) or 0)}",
                            "strikeouts": int(p.get("StrikeOutCnt", 0) or 0),
                        })

                    # Determine status text
                    game_status = gd.get("GameStatusChi", "")
                    if not game_status:
                        gs_code = gd.get("GameStatus", 0)
                        game_status = {0: "未開始", 1: "比賽中", 2: "比賽中", 3: "比賽結束"}.get(gs_code, "")

                    # Top batters (sorted by hits+HR)
                    bat_raw = data.get("BattingJson") or "[]"
                    bat_list = json.loads(bat_raw) if isinstance(bat_raw, str) else (bat_raw or [])
                    batters = []
                    for b in bat_list:
                        hits = int(b.get("HittingCnt", 0) or 0)
                        hr = int(b.get("HomeRunCnt", 0) or 0)
                        if hits > 0 or hr > 0:
                            vh = int(float(b.get("VisitingHomeType", 0) or 0))
                            batters.append({
                                "name": b.get("HitterName", "") or "",
                                "team": "home" if vh == 2 else "away",
                                "hits": hits,
                                "hr": hr,
                                "rbi": int(b.get("RunBattedINCnt", 0) or 0),
                                "runs": int(b.get("ScoreCnt", 0) or 0),
                                "so": int(b.get("StrikeOutCnt", 0) or 0),
                                "ab": int(b.get("HitCnt", 0) or 0),
                                "bb": int(b.get("BasesONBallsCnt", 0) or 0),
                            })
                    batters.sort(key=lambda x: x["hits"] + x["hr"] * 2, reverse=True)

                    # Detailed pitchers
                    detailed_pitchers = []
                    for p in pitching_list:
                        vh = int(float(p.get("VisitingHomeType", 0) or 0))
                        detailed_pitchers.append({
                            "name": p.get("PitcherName", "") or "",
                            "team": "home" if vh == 2 else "away",
                            "role": p.get("RoleType", ""),
                            "ip": f"{int(p.get('InningPitchedCnt', 0) or 0)}.{int(p.get('InningPitchedDiv3Cnt', 0) or 0)}",
                            "k": int(p.get("StrikeOutCnt", 0) or 0),
                            "er": int(p.get("EarnedRunCnt", 0) or 0),
                            "pitches": int(p.get("PitchCnt", 0) or 0),
                            "strikes": int(p.get("StrikeCnt", 0) or 0),
                            "balls": int(p.get("BallCnt", 0) or 0),
                            "max_speed": int(p.get("GameHigherSpeedPitch", 0) or 0),
                        })

                    # Current at-bat + bases from LiveLog
                    log_raw = data.get("LiveLogJson") or "[]"
                    log_list = json.loads(log_raw) if isinstance(log_raw, str) else (log_raw or [])
                    current_ab = {}
                    if log_list:
                        last = log_list[-1]
                        # VisitingHomeType in LiveLog: 1=客隊打, 2=主隊打
                        batting_side = "home" if int(float(last.get("VisitingHomeType", 0) or 0)) == 2 else "away"
                        current_ab = {
                            "hitter": last.get("HitterName", ""),
                            "pitcher": last.get("PitcherName", ""),
                            "count": f"{last.get('StrikeCnt', 0)}-{last.get('BallCnt', 0)}",
                            "outs": int(last.get("OutCnt", 0) or 0),
                            "base1": bool(last.get("FirstBase", "")),
                            "base2": bool(last.get("SecondBase", "")),
                            "base3": bool(last.get("ThirdBase", "")),
                            "batting_side": batting_side,  # which team is batting
                            "inning": int(float(last.get("InningSeq", 0) or 0)),
                        }

                    live_games.append({
                        "away_team_name": _to_chinese_name(gd.get("VisitingTeamName") or game.get("away_team_name", "")),
                        "home_team_name": _to_chinese_name(gd.get("HomeTeamName") or game.get("home_team_name", "")),
                        "away_score": gd.get("VisitingTotalScore", 0) or 0,
                        "home_score": gd.get("HomeTotalScore", 0) or 0,
                        "away_hits": away_total_hits,
                        "home_hits": home_total_hits,
                        "away_errors": away_total_errors,
                        "home_errors": home_total_errors,
                        "venue": _to_chinese_venue(gd.get("FieldAbbe", game.get("venue", ""))),
                        "status_text": game_status,
                        "weather": gd.get("WeatherDesc", ""),
                        "audience": gd.get("AudienceCntBackend", 0) or 0,
                        "innings": {"away": away_scores, "home": home_scores},
                        "pitchers": detailed_pitchers,
                        "batters": batters[:6],
                        "current_ab": current_ab,
                    })

                except Exception as e:
                    logger.warning(f"Live score failed for sno {sno}: {e}")

        finally:
            client.close()

        # Cache for 2 min
        db["cache"].update_one(
            {"_id": "live_scores"},
            {"$set": {"data": live_games, "updated_at": now}},
            upsert=True,
        )

        _live_rate_limit[user_id] = now

        # Push result to user (reply token already used)
        from linebot.v3.messaging import (
            PushMessageRequest, FlexMessage, FlexContainer, TextMessage as TM,
        )
        api = _get_api()
        if not live_games:
            api.push_message(PushMessageRequest(
                to=user_id, messages=[TM(text="目前沒有進行中的比賽")]
            ))
            return

        msg_data = flex_messages.build_live_scores(live_games)
        api.push_message(PushMessageRequest(
            to=user_id,
            messages=[FlexMessage(
                alt_text="即時比分",
                contents=FlexContainer.from_dict(msg_data["contents"]),
            )],
        ))

    except Exception as e:
        logger.error(f"Live score error: {e}")
        # Fallback to cache
        try:
            from linebot.v3.messaging import (
                PushMessageRequest, FlexMessage, FlexContainer, TextMessage as TM,
            )
            cached = db["cache"].find_one({"_id": "live_scores"})
            if cached and cached.get("data"):
                cache_age = int((now - cached["updated_at"]).total_seconds()) if cached.get("updated_at") else 0
                cache_min = cache_age // 60
                msg_data = flex_messages.build_live_scores(cached["data"])
                _get_api().push_message(PushMessageRequest(
                    to=user_id,
                    messages=[
                        TM(text=f"📡 以下為 {cache_min} 分鐘前的比分，最新數據稍後更新"),
                        FlexMessage(alt_text="即時比分(快取)", contents=FlexContainer.from_dict(msg_data["contents"])),
                    ],
                ))
                _live_rate_limit[user_id] = now
            else:
                _get_api().push_message(PushMessageRequest(
                    to=user_id, messages=[TM(text="❌ 無法取得即時比分")]
                ))
        except Exception:
            pass


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
    pending = list(bet_repo.get_user_bets_by_status(user_id, "pending"))
    settled_count = bet_repo.count_user_settled_bets(user_id)

    msg = flex_messages.build_bets_menu(len(pending), settled_count)
    _reply(event.reply_token, [msg])


def _handle_bets_pending(event, user_id: str):
    bets = list(bet_repo.get_user_bets_by_status(user_id, "pending"))
    if not bets:
        _reply(event.reply_token, ["目前沒有待結算的注單"])
        return
    msg = flex_messages.build_my_bets(bets)
    _reply(event.reply_token, [msg])


def _handle_bets_settled(event, user_id: str):
    bets = bet_repo.get_user_settled_bets(user_id, limit=30)
    if not bets:
        _reply(event.reply_token, ["目前沒有已結算的注單"])
        return
    msg = flex_messages.build_settled_bets_table(bets)
    _reply(event.reply_token, [msg])


def _handle_help(event):
    msg = flex_messages.build_help()
    _reply(event.reply_token, [msg])


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

        # Check balance before proceeding
        user = user_repo.get_user(user_id)
        balance = user.get("balance", 0) if user else 0
        if balance < amount:
            _clear_state(user_id)
            _reply(event.reply_token, [flex_messages.build_insufficient_balance(balance, amount)])
            return

        # Check daily bet cap
        from datetime import date as date_cls
        today = date_cls.today().isoformat()
        today_bet = user.get("bet_today_total", 0) if user.get("bet_today_date") == today else 0
        if today_bet + amount > 10000:
            remaining = 10000 - today_bet
            _reply(event.reply_token, [f"超過每日下注上限，今日剩餘額度: {remaining:,} 元\n請重新輸入較小的金額:"])
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
