"""Weekly awards: aggregate last week's leaderboards and push Monday noon.

Leaders computed (Mon-Sun of previous week):
- 打擊王: highest batting average (min 10 AB)
- 自責分率王: lowest ERA (min 5.0 IP)
- 盜壘王: most stolen bases
- 保送王: most walks received (batter)
- 被三振王: most strikeouts (batter)
- 三振王: most strikeouts thrown (pitcher)
- 失誤王: most fielding errors

AI (via OpenRouter) writes a short commentary per award.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta

from app.config import settings
from app.db.client import get_db

logger = logging.getLogger(__name__)

MIN_AB_FOR_AVG = 10
MIN_IP_OUTS_FOR_ERA = 15  # 5.0 IP = 15 outs


def _last_week_range(today: date | None = None) -> tuple[str, str]:
    """Return (mon, sun) ISO dates for the week preceding `today`."""
    today = today or date.today()
    # weekday(): Mon=0 ... Sun=6
    this_monday = today - timedelta(days=today.weekday())
    last_sunday = this_monday - timedelta(days=1)
    last_monday = last_sunday - timedelta(days=6)
    return last_monday.isoformat(), last_sunday.isoformat()


def _aggregate(start: str, end: str) -> dict:
    """Scan games with boxscore in [start, end] and aggregate per-player totals."""
    db = get_db()
    games = list(db["games"].find({
        "date": {"$gte": start, "$lte": end},
        "status": "final",
        "boxscore": {"$exists": True},
    }))

    batters: dict[tuple, dict] = {}  # (name, team_name) -> agg
    pitchers: dict[tuple, dict] = {}

    for g in games:
        bs = g.get("boxscore") or {}
        for b in bs.get("batting_summary", []):
            key = (b.get("name", ""), b.get("team_name", ""))
            if not key[0]:
                continue
            agg = batters.setdefault(key, {
                "name": key[0], "team_name": key[1],
                "hits": 0, "hr": 0, "rbi": 0, "at_bats": 0, "errors": 0,
                "walks": 0, "strikeouts": 0, "stolen_bases": 0, "games": 0,
            })
            agg["hits"] += b.get("hits", 0)
            agg["hr"] += b.get("hr", 0)
            agg["rbi"] += b.get("rbi", 0)
            agg["at_bats"] += b.get("at_bats", 0)
            agg["errors"] += b.get("errors", 0)
            agg["walks"] += b.get("walks", 0)
            agg["strikeouts"] += b.get("strikeouts", 0)
            agg["stolen_bases"] += b.get("stolen_bases", 0)
            agg["games"] += 1

        for p in bs.get("pitchers", []):
            key = (p.get("name", ""), p.get("team_name", ""))
            if not key[0]:
                continue
            agg = pitchers.setdefault(key, {
                "name": key[0], "team_name": key[1],
                "ip_outs": 0, "earned_runs": 0, "strikeouts": 0, "walks": 0, "hits_allowed": 0, "games": 0,
            })
            agg["ip_outs"] += p.get("ip_outs", 0)
            agg["earned_runs"] += p.get("earned_runs", 0)
            agg["strikeouts"] += p.get("strikeouts", 0)
            agg["walks"] += p.get("walks", 0) or 0
            agg["hits_allowed"] += p.get("hits_allowed", 0)
            agg["games"] += 1

    return {
        "batters": list(batters.values()),
        "pitchers": list(pitchers.values()),
        "game_count": len(games),
    }


def _pick_winners(agg: dict) -> dict:
    """Return top-3 per category. Each value is a list of dicts (champion first)."""
    batters = agg["batters"]
    pitchers = agg["pitchers"]

    # 打擊王 — min AB threshold
    eligible_avg = [b for b in batters if b["at_bats"] >= MIN_AB_FOR_AVG]
    avg_top = sorted(eligible_avg, key=lambda b: b["hits"] / b["at_bats"], reverse=True)[:3]
    avg_top = [dict(b, avg=b["hits"] / b["at_bats"]) for b in avg_top]

    # 自責分率王 — min IP threshold (ascending: lowest ERA wins)
    eligible_era = [p for p in pitchers if p["ip_outs"] >= MIN_IP_OUTS_FOR_ERA]
    era_top = sorted(eligible_era, key=lambda p: (p["earned_runs"] * 27) / p["ip_outs"])[:3]
    era_top = [
        dict(p, ip=f"{p['ip_outs'] // 3}.{p['ip_outs'] % 3}", era=(p["earned_runs"] * 27) / p["ip_outs"])
        for p in era_top
    ]

    steal_top = sorted([b for b in batters if b["stolen_bases"] > 0], key=lambda b: b["stolen_bases"], reverse=True)[:3]
    walk_top = sorted([b for b in batters if b["walks"] > 0], key=lambda b: b["walks"], reverse=True)[:3]
    sok_top = sorted([b for b in batters if b["strikeouts"] > 0], key=lambda b: b["strikeouts"], reverse=True)[:3]
    pk_top = sorted([p for p in pitchers if p["strikeouts"] > 0], key=lambda p: p["strikeouts"], reverse=True)[:3]
    error_top = sorted([b for b in batters if b["errors"] > 0], key=lambda b: b["errors"], reverse=True)[:3]

    return {
        "avg_king": avg_top,
        "era_king": era_top,
        "steal_king": steal_top,
        "walk_king": walk_top,
        "strikeout_victim_king": sok_top,
        "pitcher_k_king": pk_top,
        "error_king": error_top,
    }


def _generate_intro_text(winners: dict, date_range: tuple[str, str], game_count: int) -> str:
    """Ask the LLM to write an intro message announcing the weekly awards."""
    from openai import OpenAI

    def champ(key):
        lst = winners.get(key) or []
        return lst[0] if lst else None

    lines = []
    w = champ("avg_king")
    if w:
        lines.append(f"- 打擊王：{w['name']} ({w['team_name']}) .{int(round(w['avg']*1000)):03d} ({w['hits']}/{w['at_bats']})")
    w = champ("era_king")
    if w:
        lines.append(f"- 自責分率王：{w['name']} ({w['team_name']}) ERA {w['era']:.2f} ({w['ip']}局)")
    w = champ("steal_king")
    if w:
        lines.append(f"- 盜壘王：{w['name']} ({w['team_name']}) {w['stolen_bases']} 次")
    w = champ("walk_king")
    if w:
        lines.append(f"- 保送王：{w['name']} ({w['team_name']}) {w['walks']} 保送")
    w = champ("strikeout_victim_king")
    if w:
        lines.append(f"- 被三振王：{w['name']} ({w['team_name']}) {w['strikeouts']} K")
    w = champ("pitcher_k_king")
    if w:
        lines.append(f"- 三振王：{w['name']} ({w['team_name']}) {w['strikeouts']} K")
    w = champ("error_king")
    if w:
        lines.append(f"- 失誤王：{w['name']} ({w['team_name']}) {w['errors']} 失誤")

    if not lines:
        return ""

    start, end = date_range
    fallback = (
        f"⚾ 本週榮譽榜出爐！\n"
        f"上週 ({start} ~ {end}) 共 {game_count} 場比賽，七大獎項揭曉。\n"
        f"下方卡片看完整前三名排名 👇\n"
        f"這週 CPBL 繼續開打，祝大家戰績長紅！"
    )

    prompt = f"""你是中華職棒虛擬下注平台的吉祥物「TAKAMEI」，請寫一段推播文字當作本週榮譽榜的開場。

要求：
- 繁體中文，100~180 字，2~4 段
- 第一段：宣布上週 ({start} ~ {end}) 榮譽榜出爐，共 {game_count} 場比賽
- 第二段：簡短 summary（挑 2~3 個最有梗的得主簡單點評，不要逐一列 7 項）
- 第三段：祝大家這週下注順利、好好玩
- 語氣活潑、有棒球味、適度 emoji（不過度）
- 不要用「**」加粗符號或 markdown，純文字即可
- 只回文字內容，不要加標題或引號

七大得主資料：
{chr(10).join(lines)}"""

    try:
        client = OpenAI(api_key=settings.openrouter_api_key, base_url="https://openrouter.ai/api/v1")
        response = client.chat.completions.create(
            model="arcee-ai/trinity-large-preview:free",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=500,
        )
        text = (response.choices[0].message.content or "").strip()
        # Strip code fences if the model wrapped the reply
        if text.startswith("```"):
            text = text.strip("`").strip()
        return text or fallback
    except Exception as e:
        logger.warning(f"Weekly awards intro AI failed: {e}")
        return fallback


def _build_awards_card(winners: dict, date_range: tuple[str, str]) -> dict | None:
    start, end = date_range
    sections = []
    MEDAL = {1: "🥇", 2: "🥈", 3: "🥉"}

    def add_block(emoji: str, title: str, title_color: str, key: str, stat_fn):
        entries = winners.get(key) or []
        if not entries:
            return
        champ = entries[0]
        block = [
            {"type": "box", "layout": "horizontal", "contents": [
                {"type": "text", "text": f"{emoji} {title}", "size": "sm", "color": title_color, "weight": "bold", "flex": 3},
                {"type": "text", "text": stat_fn(champ), "size": "sm", "color": "#FFFFFF", "align": "end", "flex": 4, "weight": "bold"},
            ]},
            {"type": "text",
             "text": f"{MEDAL[1]} {champ['name']} · {champ['team_name']}",
             "size": "xs", "color": "#CCCCCC", "margin": "xs"},
        ]
        for idx, e in enumerate(entries[1:], start=2):
            block.append({
                "type": "text",
                "text": f"{MEDAL[idx]} {e['name']} · {e['team_name']}  {stat_fn(e)}",
                "size": "xxs", "color": "#777777", "margin": "xs", "wrap": True,
            })
        block.append({"type": "separator", "margin": "lg", "color": "#333333"})
        sections.extend(block)

    # Order follows user's requested list
    add_block("📈", "打擊王", "#27AE60", "avg_king",
              lambda e: f".{int(round(e['avg']*1000)):03d} ({e['hits']}/{e['at_bats']})")
    add_block("🥎", "自責分率王", "#3498DB", "era_king",
              lambda e: f"ERA {e['era']:.2f} ({e['ip']}局)")
    add_block("💨", "盜壘王", "#1ABC9C", "steal_king",
              lambda e: f"{e['stolen_bases']} 次盜壘")
    add_block("🎫", "保送王", "#E67E22", "walk_king",
              lambda e: f"{e['walks']} 保送")
    add_block("💀", "被三振王", "#95A5A6", "strikeout_victim_king",
              lambda e: f"{e['strikeouts']} K")
    add_block("⚾", "三振王", "#F39C12", "pitcher_k_king",
              lambda e: f"{e['strikeouts']} K")
    add_block("🧤", "失誤王", "#9B59B6", "error_king",
              lambda e: f"{e['errors']} 失誤")

    if not sections:
        return None

    # Remove the trailing separator
    if sections and sections[-1].get("type") == "separator":
        sections.pop()

    return {
        "type": "bubble",
        "size": "giga",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1B2838",
            "paddingAll": "14px",
            "contents": [
                {"type": "text", "text": "🏆 本週榮譽榜", "color": "#F39C12", "size": "lg", "weight": "bold"},
                {"type": "text", "text": f"{start} ~ {end}", "color": "#AAAAAA", "size": "xs", "margin": "xs"},
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#1B2838",
            "paddingAll": "15px",
            "contents": sections,
        },
    }


def push_weekly_awards(today: date | None = None, force: bool = False) -> dict:
    """Main entry: compute last week's awards and push to all whitelisted users."""
    from linebot.v3.messaging import (
        ApiClient, Configuration, MessagingApi,
        PushMessageRequest, FlexMessage, FlexContainer, TextMessage,
    )
    from app.db import whitelist_repo

    start, end = _last_week_range(today)
    db = get_db()
    push_key = f"weekly_awards_pushed_{end}"
    if not force and db["cache"].find_one({"_id": push_key}):
        logger.info(f"[Weekly Awards] Already pushed for week ending {end}, skipping")
        return {"status": "skipped", "reason": "already_pushed", "week": [start, end]}

    logger.info(f"[Weekly Awards] Aggregating {start} ~ {end}")

    agg = _aggregate(start, end)
    logger.info(f"[Weekly Awards] {agg['game_count']} games, {len(agg['batters'])} batters, {len(agg['pitchers'])} pitchers")

    if agg["game_count"] == 0:
        logger.info("[Weekly Awards] No games last week, skipping")
        return {"status": "skipped", "reason": "no_games", "week": [start, end]}

    winners = _pick_winners(agg)
    if not any(winners.values()):
        logger.info("[Weekly Awards] No qualifying winners, skipping")
        return {"status": "skipped", "reason": "no_winners", "week": [start, end]}

    card = _build_awards_card(winners, (start, end))
    if not card:
        return {"status": "skipped", "reason": "empty_card", "week": [start, end]}

    intro = _generate_intro_text(winners, (start, end), agg["game_count"])

    # Push to whitelisted users (fall back to all users if whitelist empty)
    recipients = [e["id"] for e in whitelist_repo.list_all()]
    if not recipients:
        recipients = [u["_id"] for u in db["users"].find({}, {"_id": 1})]

    configuration = Configuration(access_token=settings.line_channel_access_token)
    sent = 0
    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        for uid in recipients:
            try:
                msgs = []
                if intro:
                    msgs.append(TextMessage(text=intro))
                msgs.append(FlexMessage(
                    alt_text="🏆 本週榮譽榜",
                    contents=FlexContainer.from_dict(card),
                ))
                api.push_message(PushMessageRequest(to=uid, messages=msgs))
                sent += 1
            except Exception as e:
                logger.warning(f"Weekly awards push failed for {uid[:10]}...: {e}")

    # Mark as pushed (idempotency key per week)
    db["cache"].update_one(
        {"_id": push_key},
        {"$set": {"pushed": True, "pushed_at": datetime.now(), "sent": sent}},
        upsert=True,
    )

    logger.info(f"[Weekly Awards] Pushed to {sent}/{len(recipients)} users")
    return {
        "status": "ok",
        "week": [start, end],
        "games": agg["game_count"],
        "sent": sent,
        "recipients": len(recipients),
        "winners": {k: (v[0]["name"] if v else None) for k, v in winners.items()},
    }
