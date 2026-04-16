"""Odds engine: two-step LLM approach - design markets then format JSON."""
from __future__ import annotations

import json
import logging
import time

from openai import OpenAI

from app.config import settings
from app.betting.odds_prompt import build_design_prompt, build_json_prompt
from app.betting.odds_fallback import generate_fallback_odds

logger = logging.getLogger(__name__)

MAX_RETRIES = 3

MODELS = [
    "meta-llama/llama-4-maverick:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "qwen/qwen3-235b-a22b:free",
]


def _get_client() -> OpenAI:
    return OpenAI(
        api_key=settings.openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
    )


def generate_odds_for_games(games: list[dict], standings: dict) -> dict[str, dict]:
    if not games:
        return {}
    try:
        return _generate_two_step(games, standings)
    except Exception as e:
        logger.error(f"All LLM attempts failed, falling back to rule-based: {e}")
        return _generate_with_fallback(games, standings)


def _generate_two_step(games: list[dict], standings: dict) -> dict[str, dict]:
    """Step 1: AI designs markets in natural language. Step 2: AI converts to JSON."""
    client = _get_client()

    # === Step 1: Design markets ===
    design_prompt = build_design_prompt(games, standings)
    design_text = None

    for attempt in range(MAX_RETRIES):
        model = MODELS[attempt % len(MODELS)]
        try:
            logger.info(f"Step 1 (design) attempt {attempt + 1}/{MAX_RETRIES} with {model}")
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": design_prompt}],
                temperature=0.7,
                max_tokens=3000,
            )
            design_text = response.choices[0].message.content or ""
            # Remove thinking tags
            if "<think>" in design_text:
                idx = design_text.rfind("</think>")
                if idx != -1:
                    design_text = design_text[idx + 8:].strip()
            if len(design_text) > 100:
                logger.info(f"Step 1 success: {len(design_text)} chars")
                break
        except Exception as e:
            logger.warning(f"Step 1 attempt {attempt + 1} failed: {e}")
            time.sleep(1)

    if not design_text or len(design_text) < 100:
        raise RuntimeError("Step 1 (design) failed")

    # === Step 2: Convert to JSON ===
    game_ids = [g.get("id", "") for g in games]
    json_prompt = build_json_prompt(design_text, game_ids)

    for attempt in range(MAX_RETRIES):
        model = MODELS[attempt % len(MODELS)]
        try:
            logger.info(f"Step 2 (JSON) attempt {attempt + 1}/{MAX_RETRIES} with {model}")
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": json_prompt}],
                temperature=0,
                max_tokens=3000,
            )
            json_text = response.choices[0].message.content or ""
            # Remove thinking tags
            if "<think>" in json_text:
                idx = json_text.rfind("</think>")
                if idx != -1:
                    json_text = json_text[idx + 8:].strip()

            odds_list = _parse_json_response(json_text)

            if not isinstance(odds_list, list) or len(odds_list) == 0:
                raise ValueError("Empty response")

            result = {}
            for game_odds in odds_list:
                game_id = game_odds.get("game_id", "")
                markets = game_odds.get("markets", [])
                validated = _validate_markets(markets)
                if validated:
                    result[game_id] = {"markets": validated}

            if not result:
                raise ValueError("No valid markets")

            # Fill in missing games with fallback
            for game in games:
                gid = game.get("id", "")
                if gid not in result:
                    result[gid] = generate_fallback_odds(game, standings)

            logger.info(f"Step 2 success: {len(result)} games with LLM odds")
            return result

        except Exception as e:
            logger.warning(f"Step 2 attempt {attempt + 1} failed: {e}")
            time.sleep(1)

    raise RuntimeError("Step 2 (JSON) failed")


def _parse_json_response(text: str) -> list[dict]:
    text = text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        text = text[start:end + 1]
    return json.loads(text)


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
