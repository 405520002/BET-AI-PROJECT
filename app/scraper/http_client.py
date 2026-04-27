"""Anti-anti-scraping HTTP client with browser-like behavior."""
from __future__ import annotations

import random
import time
import logging

import httpx

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0",
]


def _random_ua() -> str:
    return random.choice(USER_AGENTS)


def _browser_headers(referer: str = "") -> dict:
    return {
        "User-Agent": _random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        # Drop "br" -- httpx only decodes brotli when the brotli library is installed,
        # otherwise the body comes back as raw compressed bytes.
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        **({"Referer": referer} if referer else {}),
    }


def _ajax_headers(referer: str, token: str) -> dict:
    return {
        "User-Agent": _random_ua(),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "RequestVerificationToken": token,
        "Referer": referer,
        "Origin": referer.split("/")[0] + "//" + referer.split("/")[2],
    }


def get_cpbl_session_sync(base_url: str) -> httpx.Client:
    """Create a sync session that mimics a real browser."""
    client = httpx.Client(timeout=20, follow_redirects=True)
    headers = _browser_headers()
    try:
        client.get(base_url, headers=headers)
        time.sleep(random.uniform(0.5, 1.5))
    except Exception as e:
        logger.warning(f"Sync homepage visit failed: {e}")
    return client


def fetch_api_sync(base_url: str, page_path: str, api_path: str, data: dict) -> dict | None:
    """Sync version of fetch_api for use in LINE handlers."""
    import re
    client = get_cpbl_session_sync(base_url)
    try:
        # Visit page to get token
        headers = _browser_headers(referer=base_url + "/")
        time.sleep(random.uniform(0.3, 1.0))
        page_r = client.get(base_url + page_path, headers=headers)

        if page_r.status_code != 200:
            logger.warning(f"Sync page {page_path}: {page_r.status_code}")
            return None

        match = re.search(r"RequestVerificationToken:\s*'([A-Za-z0-9_\-:]+)'", page_r.text)
        if not match:
            match = re.search(r'__RequestVerificationToken.*?value="([^"]+)"', page_r.text)
        token = match.group(1) if match else ""

        if not token:
            logger.warning(f"Sync no token on {page_path}")
            return None

        # POST to API
        ajax_headers = _ajax_headers(base_url + page_path, token)
        time.sleep(random.uniform(0.5, 1.0))
        api_r = client.post(base_url + api_path, data=data, headers=ajax_headers)

        if api_r.status_code == 200:
            return api_r.json()

        logger.warning(f"Sync API {api_path}: {api_r.status_code}")
        return None
    finally:
        client.close()


async def get_cpbl_session(base_url: str) -> tuple[httpx.AsyncClient, dict]:
    """Create a session that mimics a real browser visiting CPBL.
    Returns (client, cookies) after visiting homepage.
    """
    client = httpx.AsyncClient(
        timeout=20,
        follow_redirects=True,
        http2=True,
    )

    # Step 1: Visit homepage to get cookies (like a real browser)
    headers = _browser_headers()
    try:
        r = await client.get(base_url, headers=headers)
        logger.debug(f"Homepage: {r.status_code}")
        # Small random delay like a human
        time.sleep(random.uniform(0.5, 1.5))
    except Exception as e:
        logger.warning(f"Homepage visit failed: {e}")

    return client, dict(client.cookies)


async def fetch_page(base_url: str, path: str) -> str | None:
    """Fetch a page with browser-like behavior. Returns HTML text."""
    client, _ = await get_cpbl_session(base_url)
    try:
        headers = _browser_headers(referer=base_url + "/")
        time.sleep(random.uniform(0.3, 1.0))
        r = await client.get(base_url + path, headers=headers)
        if r.status_code == 200:
            return r.text
        logger.warning(f"Fetch {path}: {r.status_code}")
        return None
    finally:
        await client.aclose()


async def fetch_api(base_url: str, page_path: str, api_path: str, data: dict) -> dict | None:
    """Fetch CPBL API endpoint with proper token and browser simulation.
    1. Visit homepage (get cookies)
    2. Visit page (get verification token)
    3. POST to API with token
    """
    import re
    client, _ = await get_cpbl_session(base_url)

    try:
        # Visit the page to get token
        headers = _browser_headers(referer=base_url + "/")
        time.sleep(random.uniform(0.3, 1.0))
        page_r = await client.get(base_url + page_path, headers=headers)

        if page_r.status_code != 200:
            logger.warning(f"Page {page_path}: {page_r.status_code}")
            return None

        # Token is in: RequestVerificationToken: 'xxxxx'  (JS headers)
        # Fallback: <input name="__RequestVerificationToken" value="xxxxx" />
        match = re.search(r"RequestVerificationToken:\s*'([A-Za-z0-9_\-:]+)'", page_r.text)
        if not match:
            match = re.search(r'__RequestVerificationToken.*?value="([^"]+)"', page_r.text)
        token = match.group(1) if match else ""

        if not token:
            logger.warning(f"No token found on {page_path}")
            return None

        # POST to API
        ajax_headers = _ajax_headers(base_url + page_path, token)
        time.sleep(random.uniform(0.5, 1.5))
        api_r = await client.post(base_url + api_path, data=data, headers=ajax_headers)

        if api_r.status_code == 200:
            return api_r.json()

        logger.warning(f"API {api_path}: {api_r.status_code}")
        return None
    finally:
        await client.aclose()
