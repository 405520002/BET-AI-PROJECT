"""CPBL Proxy - GCP Cloud Function in asia-east1 (Taiwan)"""
import re
import functions_framework
import requests

CPBL_BASE = "https://www.cpbl.com.tw"
PROXY_SECRET = "cpbl-proxy-secret-2026"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": CPBL_BASE + "/",
}


def _get_session():
    """Create a session with cookies from homepage."""
    session = requests.Session()
    session.headers.update(HEADERS)
    # Visit homepage first to get cookies
    session.get(CPBL_BASE, timeout=15)
    return session


@functions_framework.http
def proxy(request):
    # CORS
    if request.method == "OPTIONS":
        return ("", 204, {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST",
            "Access-Control-Allow-Headers": "Content-Type, X-Proxy-Secret",
        })

    path = request.path

    # Health check
    if path == "/" or path == "/health":
        return ({"status": "ok", "proxy": "cpbl-gcp", "region": "asia-east1"}, 200)

    # Auth
    secret = request.headers.get("X-Proxy-Secret", "")
    if secret != PROXY_SECRET:
        return ({"error": "Unauthorized"}, 403)

    # Debug: test raw access
    if path == "/proxy/debug":
        session = _get_session()
        results = {}
        for test_path in ["/", "/schedule", "/standings/season"]:
            r = session.get(CPBL_BASE + test_path, timeout=15)
            results[test_path] = {
                "status": r.status_code,
                "length": len(r.text),
                "cookies": dict(session.cookies),
            }
        return (results, 200, {"Content-Type": "application/json"})

    try:
        cpbl_path = path.replace("/proxy", "", 1)
        cpbl_url = CPBL_BASE + cpbl_path
        session = _get_session()

        if request.method == "POST":
            # Get token from the parent page
            page_path = "/" + cpbl_path.strip("/").split("/")[0]
            page_resp = session.get(CPBL_BASE + page_path, timeout=15)
            token_match = re.search(r"RequestVerificationToken[^']*'([^']+)'", page_resp.text)
            token = token_match.group(1) if token_match else ""

            body = request.get_data(as_text=True)
            resp = session.post(cpbl_url, data=body, headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "RequestVerificationToken": token,
                "X-Requested-With": "XMLHttpRequest",
            }, timeout=15)

            return (resp.text, resp.status_code, {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            })
        else:
            resp = session.get(cpbl_url, timeout=15)
            return (resp.text, resp.status_code, {
                "Content-Type": resp.headers.get("Content-Type", "text/html"),
                "Access-Control-Allow-Origin": "*",
            })

    except Exception as e:
        return ({"error": str(e)}, 500)
