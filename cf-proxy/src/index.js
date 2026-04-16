/**
 * CPBL Proxy Worker
 * Fetches from en.cpbl.com.tw and translates English names to Chinese
 */

const CPBL_BASE = "https://www.cpbl.com.tw";
const PROXY_SECRET = "cpbl-proxy-secret-2026";

const EN_TO_ZH_TEAM = {
  "Brothers": "中信兄弟",
  "CTBC Brothers": "中信兄弟",
  "U-Lions": "統一7-ELEVEn獅",
  "Uni-Lions": "統一7-ELEVEn獅",
  "Monkeys": "樂天桃猿",
  "Rakuten Monkeys": "樂天桃猿",
  "Guardians": "富邦悍將",
  "Fubon Guardians": "富邦悍將",
  "DRAGONS": "味全龍",
  "Wei Chuan Dragons": "味全龍",
  "Dragons": "味全龍",
  "TSG Hawks": "台鋼雄鷹",
  "Hawks": "台鋼雄鷹",
};

const EN_TO_ZH_VENUE = {
  "CCL": "澄清湖",
  "XZG": "新莊",
  "TMU": "天母",
  "LOT": "樂天桃園",
  "TPD": "大巨蛋",
  "TCD": "洲際",
  "TYB": "台南",
  "ICC": "洲際",
  "Dome": "大巨蛋",
  "Taichung Intercontinental Baseball Stadium": "洲際棒球場",
  "Xinzhuang Baseball Stadium": "新莊棒球場",
  "Tianmu Baseball Stadium": "天母棒球場",
  "Chengcing Lake Baseball Stadium": "澄清湖棒球場",
  "Rakuten Taoyuan Baseball Stadium": "樂天桃園棒球場",
  "Taipei Dome": "大巨蛋",
  "Tainan Municipal Baseball Stadium": "台南棒球場",
  "Hsinchu Baseball Stadium": "新竹棒球場",
};

function translateGameData(jsonStr) {
  // Replace English team names with Chinese in the raw JSON string
  let result = jsonStr;

  // Sort by length desc to avoid partial matches
  const entries = Object.entries(EN_TO_ZH_TEAM).sort((a, b) => b[0].length - a[0].length);
  for (const [en, zh] of entries) {
    result = result.replaceAll(en, zh);
  }

  // Replace venue names
  const venueEntries = Object.entries(EN_TO_ZH_VENUE).sort((a, b) => b[0].length - a[0].length);
  for (const [en, zh] of venueEntries) {
    result = result.replaceAll(en, zh);
  }

  return result;
}

export default {
  async fetch(request) {
    const url = new URL(request.url);

    // Health check
    if (url.pathname === "/" || url.pathname === "/health") {
      return new Response(JSON.stringify({ status: "ok", worker: "cpbl-proxy", source: "en.cpbl.com.tw" }), {
        headers: { "Content-Type": "application/json" },
      });
    }

    // CORS
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, POST",
          "Access-Control-Allow-Headers": "Content-Type, X-Proxy-Secret",
        },
      });
    }

    // Auth
    const secret = request.headers.get("X-Proxy-Secret");
    if (secret !== PROXY_SECRET) {
      return new Response(JSON.stringify({ error: "Unauthorized" }), {
        status: 403,
        headers: { "Content-Type": "application/json" },
      });
    }

    try {
      const cpblPath = url.pathname.replace("/proxy", "");
      const cpblUrl = CPBL_BASE + cpblPath + url.search;

      const baseHeaders = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        "Referer": CPBL_BASE + "/",
      };

      if (request.method === "POST") {
        // Get token
        const pagePath = "/" + cpblPath.split("/").filter(Boolean)[0];
        const pageResp = await fetch(CPBL_BASE + pagePath, {
          headers: baseHeaders,
          redirect: "follow",
        });
        const pageText = await pageResp.text();
        const tokenMatch = pageText.match(/RequestVerificationToken[^']*'([^']+)'/);
        const token = tokenMatch ? tokenMatch[1] : "";

        // Forward POST
        const body = await request.text();
        const resp = await fetch(cpblUrl, {
          method: "POST",
          headers: {
            ...baseHeaders,
            "Content-Type": "application/x-www-form-urlencoded",
            "RequestVerificationToken": token,
            "X-Requested-With": "XMLHttpRequest",
          },
          body: body,
          redirect: "follow",
        });

        let respText = await resp.text();

        // Translate English to Chinese
        respText = translateGameData(respText);

        return new Response(respText, {
          status: resp.status,
          headers: {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
          },
        });
      } else {
        const resp = await fetch(cpblUrl, { headers: baseHeaders, redirect: "follow" });
        const respText = await resp.text();
        return new Response(respText, {
          status: resp.status,
          headers: {
            "Content-Type": resp.headers.get("Content-Type") || "text/html",
            "Access-Control-Allow-Origin": "*",
          },
        });
      }
    } catch (err) {
      return new Response(JSON.stringify({ error: err.message }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    }
  },
};
