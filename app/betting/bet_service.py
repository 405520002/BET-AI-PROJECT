"""Bet placement and deposit service with validation."""
from datetime import date, datetime

from app.config import settings
from app.db import user_repo, game_repo, bet_repo, tx_repo


def deposit(user_id: str, amount: int) -> dict:
    """Process a deposit. Returns {success, message, new_balance} or {success, error}."""
    if amount <= 0:
        return {"success": False, "error": "金額必須大於 0"}

    user = user_repo.get_user(user_id)
    if not user:
        return {"success": False, "error": "找不到使用者"}

    today = date.today().isoformat()

    # Reset daily counter if new day
    if user.get("deposit_today_date") != today:
        user["deposit_today_total"] = 0

    today_total = user.get("deposit_today_total", 0)

    # Daily cap
    if today_total + amount > settings.daily_deposit_cap:
        remaining = settings.daily_deposit_cap - today_total
        return {"success": False, "error": f"超過每日儲值上限，今日剩餘額度: {remaining:,} 元"}

    # 30-day rolling cap
    month_total = tx_repo.sum_deposits_last_30_days(user_id)
    if month_total + amount > settings.monthly_deposit_cap:
        remaining = settings.monthly_deposit_cap - month_total
        return {"success": False, "error": f"超過 30 天儲值上限，剩餘額度: {remaining:,} 元"}

    # Execute deposit
    new_balance = user.get("balance", 0) + amount
    user_repo.update_user(user_id, {
        "balance": new_balance,
        "total_deposited": user.get("total_deposited", 0) + amount,
        "deposit_today_total": today_total + amount,
        "deposit_today_date": today,
    })

    tx_repo.create_transaction({
        "user_id": user_id,
        "type": "deposit",
        "amount": amount,
        "balance_after": new_balance,
        "note": f"儲值 {amount:,} 元",
    })

    return {"success": True, "message": f"儲值成功！餘額: {new_balance:,} 元", "new_balance": new_balance}


def place_bet(user_id: str, game_id: str, market_index: int, selection: str, odds: float, amount: int) -> dict:
    """Place a bet. Returns {success, message, bet_id} or {success, error}."""
    if amount < settings.min_bet:
        return {"success": False, "error": f"最低下注金額: {settings.min_bet} 元"}

    user = user_repo.get_user(user_id)
    if not user:
        return {"success": False, "error": "找不到使用者"}

    # Check balance
    if user.get("balance", 0) < amount:
        return {"success": False, "error": f"餘額不足 (目前: {user.get('balance', 0):,} 元)"}

    # Check daily bet cap
    today = date.today().isoformat()
    if user.get("bet_today_date") != today:
        user["bet_today_total"] = 0

    today_bet_total = user.get("bet_today_total", 0)
    if today_bet_total + amount > settings.daily_bet_cap:
        remaining = settings.daily_bet_cap - today_bet_total
        return {"success": False, "error": f"超過每日下注上限，今日剩餘額度: {remaining:,} 元"}

    # Check game exists and is open
    game = game_repo.get_game(game_id)
    if not game:
        return {"success": False, "error": "找不到比賽"}
    if game.get("status") != "scheduled":
        return {"success": False, "error": "比賽已開始或結束，無法下注"}

    # Check if game time has passed
    from datetime import datetime
    game_time = game.get("game_time", "")
    if game_time:
        try:
            now = datetime.now()
            hour, minute = int(game_time.split(":")[0]), int(game_time.split(":")[1])
            game_start = now.replace(hour=hour, minute=minute, second=0)
            if now >= game_start:
                return {"success": False, "error": "比賽已開始，無法下注"}
        except (ValueError, IndexError):
            pass

    # Verify odds match (protect against stale odds)
    markets = game.get("odds", {}).get("markets", [])
    if market_index >= len(markets):
        return {"success": False, "error": "無效的玩法"}

    market = markets[market_index]
    matching_option = None
    for opt in market.get("options", []):
        if opt["label"] == selection and abs(opt["odds"] - odds) < 0.01:
            matching_option = opt
            break

    if not matching_option:
        return {"success": False, "error": "賠率已變更，請重新選擇"}

    # Deduct balance and place bet
    new_balance = user.get("balance", 0) - amount
    potential_payout = round(amount * odds)

    user_repo.update_user(user_id, {
        "balance": new_balance,
        "total_wagered": user.get("total_wagered", 0) + amount,
        "bet_today_total": today_bet_total + amount,
        "bet_today_date": today,
    })

    bet_id = bet_repo.create_bet({
        "user_id": user_id,
        "game_id": game_id,
        "game_date": game.get("date", today),
        "bet_type": market.get("type", "custom"),
        "market_name": market.get("name", ""),
        "selection": selection,
        "odds": odds,
        "amount": amount,
        "potential_payout": potential_payout,
        "status": "pending",
        "payout": 0,
        "profit": 0,
    })

    tx_repo.create_transaction({
        "user_id": user_id,
        "type": "bet_placed",
        "amount": amount,
        "balance_after": new_balance,
        "bet_id": bet_id,
        "game_id": game_id,
        "note": f"下注 {market.get('name', '')} - {selection} @{odds} ({amount:,} 元)",
    })

    return {
        "success": True,
        "message": f"下注成功！\n注單: {selection} @{odds}\n金額: {amount:,} 元\n預計獎金: {potential_payout:,} 元\n餘額: {new_balance:,} 元",
        "bet_id": bet_id,
    }
