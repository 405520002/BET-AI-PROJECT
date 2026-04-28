"""CPBL transparent forwarding proxy.

Deployed as a Cloud Function (Gen2) in asia-east1 (Changhua, TW) so the
egress IP is treated as legitimate TW traffic by HiNet's CDN. Forwards
/proxy/<path> to https://www.cpbl.com.tw/<path>, preserving method,
headers, body, query string, and cookies in both directions.

Auth: every request must carry an X-Proxy-Secret header matching the
PROXY_SECRET env var. Health check at / and /health.
"""
import os

import functions_framework
import requests
from flask import Response


CPBL_BASE = "https://www.cpbl.com.tw"
PROXY_SECRET = os.environ.get("PROXY_SECRET", "")

# Hop-by-hop and infra headers we do NOT forward upstream.
HOP_BY_HOP_REQUEST = {
    "host", "x-proxy-secret",
    "x-forwarded-for", "x-forwarded-proto", "x-forwarded-host",
    "x-cloud-trace-context", "x-appengine-user-ip",
    "x-appengine-default-version-hostname", "function-execution-id",
    "forwarded", "via",
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}

# Headers we do NOT forward downstream (Flask/requests recompute these).
SKIP_RESPONSE = {
    "transfer-encoding", "content-encoding", "content-length",
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "upgrade",
}


@functions_framework.http
def proxy(request):
    if request.method == "OPTIONS":
        return ("", 204, {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Max-Age": "86400",
        })

    path = request.path or "/"

    if path in ("/", "/health"):
        return ({"status": "ok", "proxy": "cpbl-gcp", "region": "asia-east1"}, 200)

    if not PROXY_SECRET or request.headers.get("X-Proxy-Secret", "") != PROXY_SECRET:
        return ({"error": "unauthorized"}, 403)

    if path.startswith("/proxy"):
        upstream_path = path[len("/proxy"):] or "/"
    else:
        upstream_path = path

    upstream_url = CPBL_BASE + upstream_path
    if request.query_string:
        upstream_url += "?" + request.query_string.decode("utf-8", errors="replace")

    fwd_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP_REQUEST
    }

    try:
        upstream = requests.request(
            method=request.method,
            url=upstream_url,
            headers=fwd_headers,
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=False,
            timeout=20,
        )
    except Exception as e:
        return ({"error": f"upstream: {type(e).__name__}: {e}"}, 502)

    response = Response(upstream.content, status=upstream.status_code)
    for k, v in upstream.headers.items():
        kl = k.lower()
        if kl in SKIP_RESPONSE or kl == "set-cookie":
            continue
        response.headers[k] = v
    for c in upstream.raw.headers.getlist("Set-Cookie"):
        response.headers.add("Set-Cookie", c)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response
