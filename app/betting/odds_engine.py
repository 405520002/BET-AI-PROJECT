"""Odds engine: two-step LLM approach.
Step 1 (OpenRouter free models): creative market design
Step 2 (Groq Llama 3.3): reliable JSON formatting
"""
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

# Step 1: creative design (Trinity is best for creative Chinese output)
DESIGN_MODELS = [
    "arcee-ai/trinity-large-preview:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "arcee-ai/trinity-large-preview:free",
]

# Step 2: JSON formatting (Nemotron is most accurate for JSON + correct team names)
JSON_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"


def _get_openrouter() -> OpenAI:
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

    # === Step 1: Design markets (OpenRouter free models) ===
    design_prompt = build_design_prompt(games, standings)
    design_text = None
    openrouter = _get_openrouter()

    for attempt in range(MAX_RETRIES):
        model = DESIGN_MODELS[attempt % len(DESIGN_MODELS)]
        try:
            logger.info(f"Step 1 (design) attempt {attempt + 1}/{MAX_RETRIES} with {model}")
            response = openrouter.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": design_prompt}],
                temperature=0.7,
                max_tokens=3000,
            )
            design_text = response.choices[0].message.content or ""
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

    # === Step 2: Convert to JSON per game (one at a time for reliability) ===
    from app.betting.odds_prompt import build_json_prompt_single
    openrouter = _get_openrouter()
    result = {}

    for game in games:
        gid = game.get("id", "")
        game_odds = _convert_single_game_json(openrouter, design_text, gid)
        if game_odds:
            result[gid] = game_odds
        else:
            logger.warning(f"Step 2 failed for {gid}, using fallback")
            result[gid] = generate_fallback_odds(game, standings)

    logger.info(f"Step 2 done: {sum(1 for v in result.values() if len(v.get('markets',[])) > 3)} games with AI odds")
    return result


def _convert_single_game_json(openrouter, design_text: str, game_id: str) -> dict | None:
    """Convert Step 1 design to JSON for a single game."""
    from app.betting.odds_prompt import build_json_prompt_single

    prompt = build_json_prompt_single(design_text, game_id)

    for attempt in range(MAX_RETRIES):
        response = None
        try:
            logger.info(f"Step 2 (JSON) {game_id} attempt {attempt + 1}/{MAX_RETRIES}")
            response = openrouter.chat.completions.create(
                model=JSON_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=4096,
            )
            json_text = response.choices[0].message.content or ""
            if "<think>" in json_text:
                idx = json_text.rfind("</think>")
                if idx != -1:
                    json_text = json_text[idx + 8:].strip()

            parsed = _parse_json_response(json_text)

            # Handle both formats: single object or array
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
            raw_full = (response.choices[0].message.content or "") if response else ""
            finish = response.choices[0].finish_reason if response else "none"
            logger.warning(f"Step 2 {game_id} attempt {attempt + 1} failed: {e} | finish_reason: {finish} | len: {len(raw_full)} | raw: {raw_full[:200]}")
            time.sleep(1)

    return None


def _parse_json_response(text: str) -> list[dict]:
    text = text.strip()
    # Remove thinking tags
    if "<think>" in text:
        idx = text.rfind("</think>")
        if idx != -1:
            text = text[idx + 8:].strip()
    # Remove markdown code blocks
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    # Find JSON array
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        text = text[start:end + 1]

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fix common JSON issues
    import re
    # Remove trailing commas before } or ]
    text = re.sub(r',\s*([}\]])', r'\1', text)
    # Fix unescaped newlines in strings
    text = re.sub(r'(?<!\\)\n', ' ', text)
    # Try again
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Last resort: try to parse partial JSON (cut at last valid })
    for i in range(len(text) - 1, 0, -1):
        if text[i] == ']':
            try:
                return json.loads(text[:i + 1])
            except json.JSONDecodeError:
                continue

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
