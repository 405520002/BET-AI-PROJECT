import sys, asyncio, httpx
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from app.main import app

async def main():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60.0) as client:
        # Test 1: full summary
        r = await client.get("/player/summary", params={"q": "張育成 上壘率為什麼比去年低"})
        assert r.status_code == 200, f"summary status {r.status_code}: {r.text[:200]}"
        data = r.json()
        assert data["summary"], "empty summary"
        assert not data["summary"].startswith("[AI 摘要產生失敗"), f"AI failed: {data['summary'][:100]}"
        assert len(data["axes"]) >= 4, f"axes {len(data['axes'])}"
        assert data["player_url"].startswith("https://stats.cpbl.com.tw/players/"), data["player_url"]
        assert "0000006888" in data["radar_image_url"], data["radar_image_url"]
        acnt = data["radar_image_url"].split("acnt=")[1]
        print(f"[OK] /player/summary  axes={len(data['axes'])} summary_len={len(data['summary'])} player={data['player_name']}")
        print("--- summary preview ---")
        print(data["summary"][:300])
        print("--- end preview ---")

        # Test 2: radar PNG
        r = await client.get("/player/radar.png", params={"acnt": acnt})
        assert r.status_code == 200, f"radar status {r.status_code}"
        assert r.headers["content-type"] == "image/png", r.headers["content-type"]
        png = r.content
        assert png[:8] == b"\x89PNG\r\n\x1a\n", f"bad signature: {png[:8]!r}"
        assert len(png) > 10000, f"png too small: {len(png)}"
        Path(f"/tmp/radar_e2e_{acnt}.png").write_bytes(png)
        print(f"[OK] /player/radar.png  size={len(png)}  saved=/tmp/radar_e2e_{acnt}.png")

        # Test 3: 404 for unknown player
        r = await client.get("/player/summary", params={"q": "不存在的球員xyz"})
        assert r.status_code == 404, f"expected 404, got {r.status_code}"
        print(f"[OK] /player/summary 404 for unknown player: {r.json()}")

if __name__ == "__main__":
    asyncio.run(main())
    print("\nAll 3 e2e tests passed.")
