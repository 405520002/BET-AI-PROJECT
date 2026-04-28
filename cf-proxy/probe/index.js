export default {
  async fetch(req) {
    const start = Date.now();
    const probes = {};
    for (const path of ["/", "/schedule", "/standings/season"]) {
      try {
        const r = await fetch("https://www.cpbl.com.tw" + path, {
          headers: {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.cpbl.com.tw/",
          },
          redirect: "follow",
        });
        probes[path] = { status: r.status, length: (await r.text()).length };
      } catch (e) {
        probes[path] = { error: e.message };
      }
    }
    return Response.json({
      colo: req.cf?.colo,
      country: req.cf?.country,
      city: req.cf?.city,
      caller_ip: req.headers.get("cf-connecting-ip"),
      probes,
      elapsed_ms: Date.now() - start,
    }, { headers: { "Access-Control-Allow-Origin": "*" } });
  }
};
