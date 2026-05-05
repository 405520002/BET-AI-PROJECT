"""Verification script for app/scraper/player_lookup.py.

Run from project root:
    .venv/bin/python scripts/verify_player_lookup.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.scraper.player_lookup import parse_query, find_player

# --- parse_query ---
assert parse_query("張育成 上壘率為什麼比去年低") == ("張育成", "上壘率為什麼比去年低"), \
    "parse_query with whitespace failed"

assert parse_query("張育成") == ("張育成", ""), \
    "parse_query without whitespace failed"

# --- find_player ---
result_zhang = find_player("張育成")
assert result_zhang is not None, "find_player('張育成') returned None"
assert result_zhang["acnt"] == "0000006888", \
    f"Expected acnt 0000006888, got {result_zhang['acnt']}"

# Verify a second player can be found (陳統恩)
result_chen = find_player("陳統恩")
assert result_chen is not None, "find_player('陳統恩') returned None"
assert "acnt" in result_chen, "find_player('陳統恩') result has no 'acnt' key"

assert find_player("不存在的人123") is None, \
    "find_player with unknown name should return None"

print("OK", result_zhang, result_chen)
