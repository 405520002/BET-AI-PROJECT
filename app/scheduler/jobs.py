"""Scheduled jobs for daily scraping and settlement.

Daily flow:
  08:00  morning_job()
         1. Clean up 30-day old data
         2. Scrape today's schedule
         3. AI generate odds
         4. Store games + odds in MongoDB

  12:00  midday_update()
         1. Re-scrape today's schedule (update pitcher/venue/time changes)
         2. Update game info but keep existing odds

  00:00  midnight_settle()
         1. Scrape today's game results
         2. Settle all bets
"""
import logging
from datetime import date, timedelta

from app.scraper import cpbl_schedule, cpbl_results, cpbl_standings
from app.betting.odds_engine import generate_odds_for_games
from app.betting.settlement import settle_all_games_for_date
from app.db import game_repo
from app.db.client import get_db

logger = logging.getLogger(__name__)


async def morning_job():
    """08:00 - Scrape schedule + AI generate odds."""
    today_obj = date.today()
    today_str = today_obj.isoformat()
    logger.info(f"[08:00] Starting morning job for {today_str}")

    # Clean up old data
    _cleanup_old_data()

    db = get_db()

    # Check if we have recent results in DB
    recent_count = db["games"].count_documents({
        "status": {"$in": ["final", "postponed"]},
        "date": {"$gte": (today_obj - timedelta(days=10)).isoformat()},
    })
    logger.info(f"[08:00] Recent finished games in DB: {recent_count}")

    # If less than 5 recent results, backfill from CPBL
    if recent_count < 5:
        logger.info("[08:00] Backfilling recent results...")
        await _backfill_recent_results(today_obj)

    # Scrape standings
    standings = await cpbl_standings.scrape_standings()

    # Cache standings in DB for LINE bot, but ONLY if scrape returned real data.
    # If the scrape failed (e.g. HiNet CDN blocks datacenter ASNs on /standings/season)
    # scrape_standings() returns the all-zero default. Writing that would clobber the
    # iPhone Shortcut residential relay's good cache (POSTed via /ingest/standings).
    if not cpbl_standings.is_default_standings(standings):
        db["cache"].update_one(
            {"_id": "standings"},
            {"$set": {"data": standings, "updated_at": today_str}},
            upsert=True,
        )
    else:
        logger.warning("[08:00] scrape_standings returned default; keeping existing cache")

    # Scrape this month's schedule (and next month if near end of month)
    import time, random
    all_games = []
    all_games += await cpbl_schedule.scrape_schedule_for_date(today_obj.year, today_obj.month)
    if today_obj.day >= 25:
        time.sleep(random.uniform(1, 2))
        next_month = today_obj.replace(day=28) + timedelta(days=4)
        all_games += await cpbl_schedule.scrape_schedule_for_date(next_month.year, next_month.month)

    # Store finished games
    finished = [g for g in all_games if g.get("status") in ("final", "postponed")]
    for game in finished:
        game_repo.upsert_game(game["id"], game)
    logger.info(f"[08:00] Stored {len(finished)} finished games")

    # Cache upcoming 7-day schedule
    seven_days_later = (today_obj + timedelta(days=7)).isoformat()
    upcoming = [g for g in all_games if g.get("status") == "scheduled" and today_str <= g.get("date", "") <= seven_days_later]
    games_by_date = {}
    for g in upcoming:
        d = g.get("date", "")
        if d not in games_by_date:
            games_by_date[d] = []
        games_by_date[d].append({
            "away_team_name": g.get("away_team_name", ""),
            "home_team_name": g.get("home_team_name", ""),
            "venue": g.get("venue", ""),
            "game_time": g.get("game_time", ""),
        })
    db["cache"].update_one(
        {"_id": "upcoming_schedule"},
        {"$set": {"data": games_by_date, "updated_at": today_str}},
        upsert=True,
    )
    logger.info(f"[08:00] Cached {len(upcoming)} upcoming games for {len(games_by_date)} days")

    # Store today's scheduled games with AI odds
    scheduled = [g for g in all_games if g.get("status") == "scheduled" and g.get("date") == today_str]
    logger.info(f"[08:00] {len(scheduled)} scheduled games today")

    if not scheduled:
        return {"games": 0, "finished_stored": len(finished)}

    odds_map = generate_odds_for_games(scheduled, standings)

    for game in scheduled:
        gid = game.get("id", "")
        game["odds"] = odds_map.get(gid, {"markets": []})
        game_repo.upsert_game(gid, game)
        logger.info(f"[08:00] {game.get('away_team_name','')} vs {game.get('home_team_name','')}: {len(game['odds'].get('markets',[]))} markets")

    # Push today's games to all users (only once per day)
    push_key = f"today_games_pushed_{today_str}"
    if not db["cache"].find_one({"_id": push_key}):
        _push_today_games(scheduled)
        db["cache"].update_one({"_id": push_key}, {"$set": {"pushed": True}}, upsert=True)

    return {"games": len(scheduled), "finished_stored": len(finished)}


def _push_today_games(games: list[dict]):
    """Push today's games summary with quick action button."""
    from linebot.v3.messaging import (
        ApiClient, Configuration, MessagingApi,
        PushMessageRequest, FlexMessage, FlexContainer,
    )
    from app.config import settings

    if not games:
        return

    # Build game rows
    game_rows = []
    for g in games:
        away = g.get("away_team_name", "")
        home = g.get("home_team_name", "")
        venue = g.get("venue", "")
        game_time = g.get("game_time", "")
        markets_count = len(g.get("odds", {}).get("markets", []))
        game_rows.append({
            "type": "box", "layout": "vertical", "margin": "lg",
            "contents": [
                {"type": "text", "text": f"🏟️ {away} vs {home}", "size": "sm", "color": "#FFFFFF", "weight": "bold"},
                {"type": "text", "text": f"📍{venue}  ⏰{game_time}  🎰{markets_count}個玩法", "size": "xs", "color": "#AAAAAA", "margin": "xs"},
            ],
        })

    flex_data = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1B2838",
            "paddingAll": "15px",
            "contents": [
                {"type": "text", "text": f"⚾ 今日有 {len(games)} 場比賽！", "size": "lg", "weight": "bold", "color": "#F39C12"},
                {"type": "separator", "margin": "lg", "color": "#333333"},
                *game_rows,
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1B2838",
            "contents": [
                {
                    "type": "button",
                    "action": {"type": "message", "label": "查看盤口 & 下注", "text": "今日賽事"},
                    "style": "primary",
                    "color": "#2C3E50",
                    "height": "md",
                },
            ],
        },
    }

    db = get_db()
    users = list(db["users"].find({}, {"_id": 1}))
    if not users:
        return

    configuration = Configuration(access_token=settings.line_channel_access_token)
    sent = 0

    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        for user in users:
            try:
                api.push_message(PushMessageRequest(
                    to=user["_id"],
                    messages=[FlexMessage(
                        alt_text=f"⚾ 今日有 {len(games)} 場比賽！",
                        contents=FlexContainer.from_dict(flex_data),
                    )],
                ))
                sent += 1
            except Exception as e:
                logger.warning(f"Push failed for {user['_id'][:10]}...: {e}")

    logger.info(f"[08:00] Pushed today's games to {sent}/{len(users)} users")


def _push_post_game_analysis(date_str: str, boxscores: dict, games: list[dict]):
    """Generate and push post-game analysis cards to users who bet."""
    from linebot.v3.messaging import (
        ApiClient, Configuration, MessagingApi,
        PushMessageRequest, FlexMessage, FlexContainer,
    )
    from app.config import settings
    from app.db import bet_repo

    db = get_db()

    # Group bets by user
    user_bets: dict[str, list[dict]] = {}
    all_bets = list(db["bets"].find({"game_date": date_str}))
    for bet in all_bets:
        uid = bet.get("user_id", "")
        user_bets.setdefault(uid, []).append(bet)

    if not user_bets:
        logger.info("[00:00] No users bet today, skipping analysis")
        return

    # Generate AI summaries + analysis cards for each game
    game_cards = {}
    ai_summaries = _generate_game_summaries(games, boxscores)

    for game in games:
        gid = game.get("id", "")
        bs = boxscores.get(gid)
        if not bs:
            continue
        summary = ai_summaries.get(gid, "")
        card = _build_analysis_card(game, bs, summary)
        if card:
            game_cards[gid] = card

    # Push to each user: analysis carousel + daily settlement card
    configuration = Configuration(access_token=settings.line_channel_access_token)
    sent = 0

    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        for uid, bets in user_bets.items():
            messages = []

            game_ids = {b.get("game_id", "") for b in bets}
            cards = [game_cards[gid] for gid in game_ids if gid in game_cards]
            if cards:
                carousel = {"type": "carousel", "contents": cards[:10]}
                messages.append(FlexMessage(
                    alt_text="賽後分析",
                    contents=FlexContainer.from_dict(carousel),
                ))

            settlement = _build_daily_settlement_card(date_str, bets)
            if settlement:
                messages.append(FlexMessage(
                    alt_text="今日結算",
                    contents=FlexContainer.from_dict(settlement),
                ))

            if not messages:
                continue

            try:
                api.push_message(PushMessageRequest(to=uid, messages=messages))
                sent += 1
            except Exception as e:
                logger.warning(f"Post-game push failed for {uid[:10]}...: {e}")

    logger.info(f"[00:00] Pushed post-game analysis + settlement to {sent} users")


def _generate_game_summaries(games: list[dict], boxscores: dict) -> dict[str, str]:
    """Use AI to generate post-game summary per game. Returns {game_id: summary_text}."""
    from app.llm import gemini_generate, GeminiError
    import time
    import random

    summaries = {}

    for game in games:
        gid = game.get("id", "")
        bs = boxscores.get(gid)
        if not bs:
            continue

        away = game.get("away_team_name", "")
        home = game.get("home_team_name", "")

        # Build boxscore text
        batters_text = ""
        for b in bs.get("batting_summary", []):
            side = home if b.get("team") == "home" else away
            stats = f"{b.get('hits',0)}安"
            if b.get("hr", 0) > 0:
                stats += f" {b['hr']}轟"
            if b.get("rbi", 0) > 0:
                stats += f" {b['rbi']}打點"
            batters_text += f"  {side} {b.get('name','')}: {stats}\n"

        pitchers_text = ""
        for p in bs.get("pitchers", []):
            side = home if p.get("team") == "home" else away
            pitchers_text += (
                f"  {side} {p.get('name','')}: {p.get('ip','0.0')}局 "
                f"{p.get('strikeouts',0)}K {p.get('earned_runs',0)}自責分 "
                f"{p.get('hits_allowed',0)}被安 {p.get('walks',0)}保送\n"
            )

        boxscore_text = (
            f"{away} {bs.get('away_score',0)} : {bs.get('home_score',0)} {home}\n"
            f"首局得分: {bs.get('first_inning_runs',0)}\n"
            f"全壘打: {bs.get('total_hr',0)}\n"
            f"勝分差: {bs.get('winning_margin',0)}\n\n"
            f"打擊:\n{batters_text}\n投手:\n{pitchers_text}"
        )

        prompt = f"""你是中華職棒球評「TAKAMEI」，請針對這場比賽寫一段賽後評論。

要求：
- 繁體中文，2-3句話，80-120字
- 語氣專業簡潔，像體育主播
- 點出關鍵球員、比賽轉折點、值得注意的數據
- 直接寫評論，不要加標題或格式符號

比賽數據：
{boxscore_text}"""

        try:
            text = gemini_generate(prompt, temperature=0.7, max_output_tokens=500).strip()
            if text and len(text) > 20:
                summaries[gid] = text
                logger.info(f"[00:00] TAKAMEI summary for {gid}: {len(text)} chars")
            time.sleep(random.uniform(0.5, 1.0))
        except Exception as e:
            logger.warning(f"[00:00] TAKAMEI summary failed for {gid}: {e}")

    return summaries


def _build_analysis_card(game: dict, bs: dict, summary: str = "") -> dict | None:
    """Build a single post-game analysis bubble from boxscore."""
    away = game.get("away_team_name", "")
    home = game.get("home_team_name", "")
    away_score = bs.get("away_score", 0)
    home_score = bs.get("home_score", 0)
    winner = home if home_score > away_score else away

    # Find top performers from batting
    batters = bs.get("batting_summary", [])
    top_hitters = sorted(batters, key=lambda b: b.get("hits", 0) + b.get("hr", 0) * 2, reverse=True)[:3]

    # Pitchers
    pitchers = bs.get("pitchers", [])
    starters = []
    for team in ["away", "home"]:
        for p in pitchers:
            if p.get("team") == team:
                starters.append(p)
                break

    # Build content
    contents = [
        # Score header
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {"type": "text", "text": away, "size": "sm", "color": "#CCCCCC", "flex": 3},
                {"type": "text", "text": str(away_score), "size": "xl", "color": "#FFFFFF", "weight": "bold", "align": "center", "flex": 1},
                {"type": "text", "text": ":", "size": "md", "color": "#888888", "align": "center", "flex": 1},
                {"type": "text", "text": str(home_score), "size": "xl", "color": "#FFFFFF", "weight": "bold", "align": "center", "flex": 1},
                {"type": "text", "text": home, "size": "sm", "color": "#CCCCCC", "align": "end", "flex": 3},
            ],
        },
        {"type": "text", "text": f"🏆 {winner} 勝", "size": "sm", "color": "#F39C12", "align": "center", "margin": "md"},
        {"type": "separator", "margin": "lg", "color": "#333333"},
    ]

    # Top hitters
    if top_hitters:
        contents.append({"type": "text", "text": "打擊表現", "size": "sm", "color": "#F39C12", "weight": "bold", "margin": "lg"})
        for h in top_hitters:
            name = h.get("name", "")
            hits = h.get("hits", 0)
            hr = h.get("hr", 0)
            rbi = h.get("rbi", 0)
            stats = f"{hits}安"
            if hr > 0:
                stats += f" {hr}轟"
            if rbi > 0:
                stats += f" {rbi}打點"
            contents.append({
                "type": "box", "layout": "horizontal", "margin": "sm",
                "contents": [
                    {"type": "text", "text": name, "size": "xs", "color": "#CCCCCC", "flex": 3},
                    {"type": "text", "text": stats, "size": "xs", "color": "#FFFFFF", "align": "end", "flex": 4},
                ],
            })

    # Pitchers
    if starters:
        contents.append({"type": "separator", "margin": "lg", "color": "#333333"})
        contents.append({"type": "text", "text": "投手表現", "size": "sm", "color": "#F39C12", "weight": "bold", "margin": "lg"})
        for p in starters:
            name = p.get("name", "")
            ip = p.get("ip", "0.0")
            k = p.get("strikeouts", 0)
            er = p.get("earned_runs", 0)
            contents.append({
                "type": "box", "layout": "horizontal", "margin": "sm",
                "contents": [
                    {"type": "text", "text": name, "size": "xs", "color": "#CCCCCC", "flex": 3},
                    {"type": "text", "text": f"{ip}局 {k}K {er}ER", "size": "xs", "color": "#FFFFFF", "align": "end", "flex": 4},
                ],
            })

    # Game stats
    total_hr = bs.get("total_hr", 0)
    first_inning = bs.get("first_inning_runs", 0)
    contents.append({"type": "separator", "margin": "lg", "color": "#333333"})
    contents.append({
        "type": "box", "layout": "horizontal", "margin": "lg",
        "contents": [
            {"type": "text", "text": f"全壘打 {total_hr}", "size": "xxs", "color": "#888888", "flex": 1},
            {"type": "text", "text": f"首局得分 {first_inning}", "size": "xxs", "color": "#888888", "align": "center", "flex": 1},
            {"type": "text", "text": f"總分 {away_score + home_score}", "size": "xxs", "color": "#888888", "align": "end", "flex": 1},
        ],
    })

    # AI summary
    if summary:
        contents.append({"type": "separator", "margin": "lg", "color": "#333333"})
        contents.append({
            "type": "box",
            "layout": "vertical",
            "margin": "lg",
            "backgroundColor": "#0D1117",
            "cornerRadius": "md",
            "paddingAll": "12px",
            "contents": [
                {"type": "text", "text": "TAKAMEI 賽評", "size": "xs", "color": "#F39C12", "weight": "bold"},
                {"type": "text", "text": summary, "size": "sm", "color": "#CCCCCC", "wrap": True, "margin": "sm"},
            ],
        })

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1B2838",
            "paddingAll": "12px",
            "contents": [
                {"type": "text", "text": f"📊 賽後分析  {game.get('date', '')}", "color": "#AAAAAA", "size": "xs"},
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1B2838",
            "paddingAll": "15px",
            "contents": contents,
        },
    }


def _build_daily_settlement_card(date_str: str, bets: list[dict]) -> dict | None:
    """Summary of a user's bets for the day: per-status count, totals, and per-bet detail."""
    if not bets:
        return None

    status_icon = {"won": "✅", "lost": "❌", "refunded": "↩️", "pending": "⏳"}
    status_color = {"won": "#27AE60", "lost": "#E74C3C", "refunded": "#AAAAAA", "pending": "#888888"}

    total = len(bets)
    won = sum(1 for b in bets if b.get("status") == "won")
    lost = sum(1 for b in bets if b.get("status") == "lost")
    refunded = sum(1 for b in bets if b.get("status") == "refunded")
    pending = sum(1 for b in bets if b.get("status") == "pending")

    total_wagered = sum(b.get("amount", 0) for b in bets)
    total_payout = sum(b.get("payout", 0) for b in bets)
    net = total_payout - total_wagered

    net_color = "#27AE60" if net > 0 else ("#E74C3C" if net < 0 else "#AAAAAA")
    net_text = f"+{net:,}" if net > 0 else f"{net:,}"

    summary_parts = [f"✅{won}", f"❌{lost}"]
    if refunded:
        summary_parts.append(f"↩️{refunded}")
    if pending:
        summary_parts.append(f"⏳{pending}")

    contents = [
        {
            "type": "box", "layout": "horizontal",
            "contents": [
                {"type": "text", "text": f"共 {total} 注", "size": "sm", "color": "#CCCCCC", "flex": 2},
                {"type": "text", "text": " ".join(summary_parts), "size": "sm", "color": "#FFFFFF", "align": "end", "flex": 3},
            ],
        },
        {"type": "separator", "margin": "lg", "color": "#333333"},
        {
            "type": "box", "layout": "horizontal", "margin": "md",
            "contents": [
                {"type": "text", "text": "總投注", "size": "xs", "color": "#888888", "flex": 1},
                {"type": "text", "text": f"{total_wagered:,}", "size": "sm", "color": "#CCCCCC", "align": "end", "flex": 2},
            ],
        },
        {
            "type": "box", "layout": "horizontal", "margin": "sm",
            "contents": [
                {"type": "text", "text": "總派彩", "size": "xs", "color": "#888888", "flex": 1},
                {"type": "text", "text": f"{total_payout:,}", "size": "sm", "color": "#CCCCCC", "align": "end", "flex": 2},
            ],
        },
        {
            "type": "box", "layout": "horizontal", "margin": "sm",
            "contents": [
                {"type": "text", "text": "淨損益", "size": "xs", "color": "#888888", "flex": 1},
                {"type": "text", "text": net_text, "size": "md", "color": net_color, "align": "end", "weight": "bold", "flex": 2},
            ],
        },
        {"type": "separator", "margin": "lg", "color": "#333333"},
        {"type": "text", "text": "注單明細", "size": "sm", "color": "#F39C12", "weight": "bold", "margin": "lg"},
    ]

    for bet in bets[:10]:
        status = bet.get("status", "pending")
        icon = status_icon.get(status, "•")
        amount = bet.get("amount", 0)
        payout = bet.get("payout", 0)
        market = bet.get("market_name", "")
        selection = bet.get("selection", "")
        odds = bet.get("odds", 0)

        if status == "won":
            delta_text = f"+{payout - amount:,}"
        elif status == "lost":
            delta_text = f"-{amount:,}"
        elif status == "refunded":
            delta_text = "±0"
        else:
            delta_text = "待結算"

        contents.append({
            "type": "box", "layout": "horizontal", "margin": "md",
            "contents": [
                {"type": "text", "text": f"{icon} {selection}", "size": "xs", "color": "#CCCCCC", "flex": 4, "wrap": True},
                {"type": "text", "text": delta_text, "size": "xs", "color": status_color.get(status, "#CCCCCC"), "align": "end", "weight": "bold", "flex": 2},
            ],
        })
        contents.append({
            "type": "text", "text": f"  {market} · {amount:,} @{odds}",
            "size": "xxs", "color": "#666666",
        })

    if len(bets) > 10:
        contents.append({
            "type": "text", "text": f"...另有 {len(bets) - 10} 筆",
            "size": "xxs", "color": "#666666", "margin": "md", "align": "center",
        })

    return {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1B2838",
            "paddingAll": "12px",
            "contents": [
                {"type": "text", "text": f"📋 今日結算  {date_str}", "color": "#AAAAAA", "size": "xs"},
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1B2838",
            "paddingAll": "15px",
            "contents": contents,
        },
    }


def _push_takamei_reminder():
    """Push TAKAMEI mascot reminder + help cards to all users."""
    from linebot.v3.messaging import (
        ApiClient, Configuration, MessagingApi,
        PushMessageRequest, FlexMessage, FlexContainer, TextMessage,
    )
    from app.config import settings
    from app.llm import gemini_generate
    from app.line_bot.flex_messages import build_help

    db = get_db()
    users = list(db["users"].find({}, {"_id": 1, "display_name": 1}))
    if not users:
        return

    configuration = Configuration(access_token=settings.line_channel_access_token)
    sent = 0

    # Generate one template with AI (use {NAME} as placeholder)
    try:
        template = gemini_generate(
            """你是TAKAMEI，中華職棒虛擬下注平台的可愛吉祥物。
請用可愛、活潑、有趣的語調寫一段提醒訊息。

要求：
- 繁體中文，3-4句話，100字以內
- 語調像可愛的動物吉祥物（用「~」「！」「喔」「呢」等語氣詞）
- 提醒今天有比賽可以下注
- 鼓勵來玩，但不要太強迫
- 可以加一點棒球梗或可愛的表情描述
- 開頭用 {NAME} 當作名字的佔位符（例如：{NAME}～今天...）
- 可以適當使用 emoji 增加可愛感

直接寫訊息，不要加標題。""",
            temperature=0.9,
            max_output_tokens=400,
        ).strip()
    except Exception:
        template = "{NAME}～今天也有精彩的中職比賽喔！⚾ 快來看看今日賽事，說不定會有意想不到的好盤口呢！TAKAMEI在這裡等你來挑戰～💪"

    help_msg = build_help()

    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        for user in users:
            name = user.get("display_name", "") or "朋友"
            mascot_msg = template.replace("{NAME}", name)

            try:
                api.push_message(PushMessageRequest(
                    to=user["_id"],
                    messages=[TextMessage(text=f"🐾 TAKAMEI提醒 {name}:\n\n{mascot_msg}\n\n👇 點下方功能開始玩")],
                ))
                sent += 1
            except Exception as e:
                logger.warning(f"TAKAMEI reminder push failed: {e}")

    logger.info(f"[12:00] TAKAMEI reminder pushed to {sent}/{len(users)} users")


async def midday_update():
    """12:00 - Re-scrape schedule to update game info (pitchers/venue/time), keep existing odds."""
    today = date.today().isoformat()
    logger.info(f"[12:00] Updating game info for {today}")

    games = await cpbl_schedule.scrape_today_schedule()
    scheduled = [g for g in games if g.get("status") == "scheduled"]
    updated = 0

    for game in scheduled:
        gid = game.get("id", "")
        existing = game_repo.get_game(gid)

        if existing:
            # Keep existing odds, only update game info
            game["odds"] = existing.get("odds", {"markets": []})
            game_repo.upsert_game(gid, game)
            logger.info(f"[12:00] Updated info: {game.get('away_team_name','')} vs {game.get('home_team_name','')}")
        else:
            # New game that wasn't in 08:00 scrape, use fallback odds
            from app.betting.odds_fallback import generate_fallback_odds
            standings = await cpbl_standings.scrape_standings()
            game["odds"] = generate_fallback_odds(game, standings)
            game_repo.upsert_game(gid, game)
            logger.info(f"[12:00] New game added: {gid}")
        updated += 1

    # Push TAKAMEI reminder (only if there are games today)
    if updated > 0:
        _push_takamei_reminder()

    return {"updated": updated}


async def send_pending_notifications():
    """Every 1 min - Send notifications that are due (notify_at <= now, sent=false)."""
    from datetime import datetime
    from linebot.v3.messaging import (
        ApiClient, Configuration, MessagingApi,
        PushMessageRequest, TextMessage,
    )
    from app.config import settings

    now = datetime.now()
    db = get_db()

    # Atomically claim due notifications (prevents duplicate sends across workers)
    configuration = Configuration(access_token=settings.line_channel_access_token)
    notified = 0

    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        while True:
            # find_one_and_update: atomically find + mark sent
            n = db["notifications"].find_one_and_update(
                {"notify_at": {"$lte": now}, "sent": False},
                {"$set": {"sent": True}},
            )
            if not n:
                break
            info = n.get("game_info", {})
            away = info.get("away_team_name", "")
            home = info.get("home_team_name", "")
            venue = info.get("venue", "")
            game_time = info.get("game_time", "")

            msg = (
                f"⚾ 比賽即將開始！\n\n"
                f"{away} vs {home}\n"
                f"📍 {venue}  ⏰ {game_time}\n\n"
                f"你在這場比賽有下注，祝好運！🍀"
            )

            try:
                api.push_message(PushMessageRequest(
                    to=n["user_id"],
                    messages=[TextMessage(text=msg)],
                ))
                notified += 1
                logger.info(f"[NOTIFY] {n['user_id'][:10]}.. → {away} vs {home}")
            except Exception as e:
                logger.warning(f"Push notify failed: {e}")

            # Already marked sent by find_one_and_update above

    return {"notified": notified}


async def midnight_settle():
    """00:00 - Scrape today's results + boxscores and settle all bets."""
    from app.scraper.cpbl_boxscore import scrape_boxscore
    import time
    import random

    # At 00:00, settle yesterday's games (they just finished)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    today = yesterday  # settle yesterday
    logger.info(f"[00:00] Scraping results and settling for {today}")

    # Step 1: Scrape basic results (updates game status to final/postponed)
    results_updated = await _scrape_and_update_results(today)
    logger.info(f"[00:00] Updated {results_updated} game results")

    # Step 2: Scrape boxscores for completed games
    games = game_repo.get_games_by_date(today)
    final_games = [g for g in games if g.get("status") == "final"]
    boxscores = {}

    for game in final_games:
        game_sno = game.get("game_sno")
        if not game_sno:
            continue
        try:
            time.sleep(random.uniform(1, 2))
            bs = await scrape_boxscore(game_sno)
            if bs:
                boxscores[game["id"]] = bs
                # Persist for weekly awards aggregation
                game_repo.upsert_game(game["id"], {"boxscore": bs})
                logger.info(f"[00:00] Boxscore {game['id']}: {bs.get('away_score',0)}-{bs.get('home_score',0)}, HR:{bs.get('total_hr',0)}, 1st:{bs.get('first_inning_runs',0)}")
        except Exception as e:
            logger.warning(f"[00:00] Boxscore failed for {game['id']}: {e}")

    logger.info(f"[00:00] Got {len(boxscores)} boxscores")

    # Step 3: Settle all bets (with boxscores for custom bets)
    settle_result = settle_all_games_for_date(today, boxscores)
    logger.info(f"[00:00] Settlement: {settle_result}")

    # Step 4: Push post-game analysis (only once per day)
    db = get_db()
    push_key = f"post_game_pushed_{today}"
    already_pushed = db["cache"].find_one({"_id": push_key})
    if boxscores and not already_pushed:
        _push_post_game_analysis(today, boxscores, final_games)
        db["cache"].update_one({"_id": push_key}, {"$set": {"pushed": True}}, upsert=True)

    # Step 5: Update caches (standings, upcoming, finished games)
    await _update_caches_after_settle()

    return {"results_updated": results_updated, "boxscores": len(boxscores), **settle_result}


async def _update_caches_after_settle():
    """Update standings, upcoming schedule, and finished games cache after settlement."""
    import time as _time
    import random as _random

    db = get_db()
    today_obj = date.today()
    today_str = today_obj.isoformat()

    try:
        # Update standings — but skip the write if scrape returned the default
        # fallback (e.g. when HiNet blocks the datacenter IP), so we don't clobber
        # the iPhone Shortcut residential relay's good cache.
        standings = await cpbl_standings.scrape_standings()
        if not cpbl_standings.is_default_standings(standings):
            db["cache"].update_one(
                {"_id": "standings"},
                {"$set": {"data": standings, "updated_at": today_str}},
                upsert=True,
            )
            logger.info("[00:00] Updated standings cache")
        else:
            logger.warning("[00:00] scrape_standings returned default; keeping existing cache")

        _time.sleep(_random.uniform(1, 2))

        # Update finished games + upcoming schedule
        all_games = await cpbl_schedule.scrape_schedule_for_date(today_obj.year, today_obj.month)

        # Store finished games (for 近期賽果)
        finished = [g for g in all_games if g.get("status") in ("final", "postponed")]
        for game in finished:
            game_repo.upsert_game(game["id"], game)
        logger.info(f"[00:00] Updated {len(finished)} finished games")

        # Update upcoming schedule cache
        seven_days = (today_obj + timedelta(days=7)).isoformat()
        upcoming = [g for g in all_games if g.get("status") == "scheduled" and today_str <= g.get("date", "") <= seven_days]
        games_by_date = {}
        for g in upcoming:
            d = g.get("date", "")
            if d not in games_by_date:
                games_by_date[d] = []
            games_by_date[d].append({
                "away_team_name": g.get("away_team_name", ""),
                "home_team_name": g.get("home_team_name", ""),
                "venue": g.get("venue", ""),
                "game_time": g.get("game_time", ""),
            })
        db["cache"].update_one(
            {"_id": "upcoming_schedule"},
            {"$set": {"data": games_by_date, "updated_at": today_str}},
            upsert=True,
        )
        logger.info(f"[00:00] Updated upcoming cache: {len(upcoming)} games")

    except Exception as e:
        logger.warning(f"[00:00] Cache update failed: {e}")


# === Helpers ===

async def _scrape_and_update_results(date_str: str) -> int:
    """Scrape game results and update MongoDB."""
    games = game_repo.get_games_by_date(date_str)
    if not games:
        return 0

    pending_games = [g for g in games if g.get("status") not in ("final", "postponed")]
    if not pending_games:
        return 0

    results = await cpbl_results.scrape_game_results(date_str)
    updated = 0

    for result in results:
        sno = result.get("game_sno")
        matching_game = None
        for g in pending_games:
            if g.get("game_sno") == sno:
                matching_game = g
                break

        if not matching_game:
            continue

        if result["status"] == "postponed":
            game_repo.update_game_status(matching_game["id"], "postponed")
            logger.info(f"Game {matching_game['id']} postponed")
        elif result["status"] == "final":
            game_repo.update_game_result(
                matching_game["id"],
                result["home_score"],
                result["away_score"],
                result.get("result_details"),
            )
            logger.info(f"Game {matching_game['id']} final: {result['away_score']}-{result['home_score']}")
        updated += 1

    return updated


def _cleanup_old_data():
    """Remove games, bets, and transactions older than 30 days."""
    from datetime import datetime
    cutoff = datetime.now() - timedelta(days=30)
    cutoff_date_str = (date.today() - timedelta(days=30)).isoformat()
    db = get_db()

    r1 = db["games"].delete_many({"date": {"$lt": cutoff_date_str}})
    r2 = db["bets"].delete_many({"created_at": {"$lt": cutoff}})
    r3 = db["transactions"].delete_many({"created_at": {"$lt": cutoff}})

    total = r1.deleted_count + r2.deleted_count + r3.deleted_count
    if total > 0:
        logger.info(f"[CLEANUP] Deleted {r1.deleted_count} games, {r2.deleted_count} bets, {r3.deleted_count} tx")


async def _backfill_recent_results(today_obj):
    """Backfill recent finished games from CPBL when DB is empty/sparse.
    Scrapes current month and previous month to get ~10 days of results.
    """
    import time
    import random

    stored = 0
    months_to_scrape = [(today_obj.year, today_obj.month)]

    # Also scrape previous month if we're early in the month
    if today_obj.day <= 10:
        prev = today_obj.replace(day=1) - timedelta(days=1)
        months_to_scrape.append((prev.year, prev.month))

    for year, month in months_to_scrape:
        logger.info(f"[BACKFILL] Scraping {year}-{month:02d}")
        try:
            games = await cpbl_schedule.scrape_schedule_for_date(year, month)
            finished = [g for g in games if g.get("status") in ("final", "postponed")]
            for game in finished:
                game_repo.upsert_game(game["id"], game)
                stored += 1
            logger.info(f"[BACKFILL] {year}-{month:02d}: {len(finished)} finished games stored")
            # Random delay between months
            time.sleep(random.uniform(1, 3))
        except Exception as e:
            logger.error(f"[BACKFILL] Failed for {year}-{month:02d}: {e}")

    logger.info(f"[BACKFILL] Total stored: {stored} games")
