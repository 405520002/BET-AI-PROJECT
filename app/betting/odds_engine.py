"""Odds engine: two-step Gemini approach.
Step 1: creative market design (temperature 0.7, free-form text)
Step 2: per-game JSON formatting (temperature 0, responseMimeType=application/json)

Both steps force thinkingBudget=0 to avoid hidden thinking-token cost.
"""
from __future__ import annotations

import json
import logging
import time

from app.config import settings
from app.llm import MODEL, gemini_generate
from app.betting.odds_prompt import build_design_prompt, build_json_prompt_single
from app.betting.odds_fallback import generate_fallback_odds

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


def generate_odds_for_games(games: list[dict], standings: dict) -> dict[str, dict]:
    if not games:
        return {}
    try:
        return _generate_two_step(games, standings)
    except Exception as e:
        logger.error(f"All LLM attempts failed, falling back to rule-based: {e}")
        return _generate_with_fallback(games, standings)


def _generate_two_step(games: list[dict], standings: dict) -> dict[str, dict]:
    """Step 1: AI designs markets in natural language. Step 2: AI converts to JSON per game."""

    # === Step 1: Design markets ===
    design_prompt = build_design_prompt(games, standings)
    design_text = ""

    for attempt in range(MAX_RETRIES):
        try:
            logger.info(f"Step 1 (design) attempt {attempt + 1}/{MAX_RETRIES} with {MODEL}")
            design_text = gemini_generate(
                design_prompt,
                temperature=0.7,
                max_output_tokens=3000,
            )
            if len(design_text) > 100:
                logger.info(f"Step 1 success: {len(design_text)} chars")
                break
        except Exception as e:
            logger.warning(f"Step 1 attempt {attempt + 1} failed: {e}")
            time.sleep(1)

    if not design_text or len(design_text) < 100:
        raise RuntimeError("Step 1 (design) failed")

    # === Step 2: Convert to JSON per game ===
    result = {}
    for game in games:
        gid = game.get("id", "")
        try:
            game_odds = _convert_single_game_json(design_text, gid)
            if game_odds:
                result[gid] = game_odds
            else:
                logger.warning(f"Step 2 failed for {gid}, using fallback")
                result[gid] = generate_fallback_odds(game, standings)
        except Exception as e:
            logger.warning(f"Step 2 crashed for {gid}: {e}, using fallback")
            result[gid] = generate_fallback_odds(game, standings)

    logger.info(f"Step 2 done: {sum(1 for v in result.values() if len(v.get('markets',[])) > 3)} games with AI odds")
    return result


def _convert_single_game_json(design_text: str, game_id: str) -> dict | None:
    prompt = build_json_prompt_single(design_text, game_id)

    for attempt in range(MAX_RETRIES):
        json_text = ""
        try:
            logger.info(f"Step 2 (JSON) {game_id} attempt {attempt + 1}/{MAX_RETRIES}")
            json_text = gemini_generate(
                prompt,
                temperature=0,
                max_output_tokens=4096,
                json_mode=True,
            )

            parsed = _parse_json_response(json_text)

            if isinstance(parsed, list) and len(parsed) > 0:
                game_data = parsed[0]
            elif isinstance(parsed, dict):
                game_data = parsed
            else:
                raise ValueError("Invalid format")

            markets = game_data.get("markets", [])
            validated = _validate_markets(markets)
            if validated:
                logger.info(f"Step 2 {game_id} success: {len(validated)} markets")
                return {"markets": validated}

            raise ValueError("No valid markets")

        except Exception as e:
            logger.warning(
                f"Step 2 {game_id} attempt {attempt + 1} failed: {e} | len: {len(json_text)} | raw: {json_text[:200]}"
            )
            time.sleep(1)

    return None


def _parse_json_response(text: str):
    text = text.strip()
    # Remove markdown code fences (rare with responseMimeType but safety net)
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    # Direct parse first (responseMimeType=application/json makes this reliable)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fallback: locate array/object bounds
    for open_c, close_c in (("[", "]"), ("{", "}")):
        start = text.find(open_c)
        end = text.rfind(close_c)
        if start != -1 and end > start:
            candidate = text[start:end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    # Fix common issues (trailing commas, unescaped newlines in strings)
    import re
    fixed = re.sub(r',\s*([}\]])', r'\1', text)
    fixed = re.sub(r'(?<!\\)\n', ' ', fixed)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    raise json.JSONDecodeError("Cannot parse JSON", text, 0)


def _generate_with_fallback(games: list[dict], standings: dict) -> dict[str, dict]:
    result = {}
    for game in games:
        gid = game.get("id", "")
        result[gid] = generate_fallback_odds(game, standings)
    return result


def _validate_markets(markets: list[dict]) -> list[dict]:
    validated = []
    for market in markets:
        options = market.get("options", [])
        if len(options) < 2:
            continue
        valid_options = []
        for opt in options:
            odds = opt.get("odds", 0)
            if not isinstance(odds, (int, float)) or odds <= 0:
                continue
            odds = max(settings.min_odds, min(settings.max_odds, odds))
            opt["odds"] = round(odds, 2)
            valid_options.append(opt)
        if len(valid_options) < 2:
            continue

        implied_sum = sum(1.0 / opt["odds"] for opt in valid_options)
        if implied_sum < 1.02:
            factor = 1.08 / implied_sum
            for opt in valid_options:
                opt["odds"] = round(max(settings.min_odds, opt["odds"] / factor), 2)
        elif implied_sum > 1.20:
            factor = 1.08 / implied_sum
            for opt in valid_options:
                opt["odds"] = round(min(settings.max_odds, opt["odds"] / factor), 2)

        market["options"] = valid_options
        validated.append(market)
    return validated
