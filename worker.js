/* ═══════════════════════════════════════════════════════════════
   麻吉股研所・自家代理(Cloudflare Worker 免費版)
   用途:台股官方資料源的 CORS/IP 封鎖繞道
   安全:只轉發下方白名單網域,不能被別人當萬用代理濫用
   格式:GET/POST  https://你的網址.workers.dev/?url=<編碼後目標網址>
   ═══════════════════════════════════════════════════════════════ */
const ALLOW = new Set([
  'mis.twse.com.tw',      // 證交所即時報價/分線
  'www.twse.com.tw',      // 證交所 rwd 端點(每5秒指數統計等)
  'openapi.twse.com.tw',  // 證交所 OpenAPI(季報三率最新季等)
  'mops.twse.com.tw',     // 公開資訊觀測站
  'mopsov.twse.com.tw',   // 公開資訊觀測站(舊版,季報歷史回補用)
  'www.tpex.org.tw'       // 櫃買中心(OpenAPI 與各式端點)
]);

export default {
  async fetch(req, env) {
    const cors = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
      'Access-Control-Allow-Headers': '*'
    };
    if (req.method === 'OPTIONS') return new Response(null, { headers: cors });

    // ── 🐦 /fk:發放富果 Key(Key 存在 Cloudflare 加密環境變數 FUGLE_KEY,絕不進 repo)──
    //    僅允許來自本人網站的請求(Origin/Referer 檢查);未設定變數則回 404
    if (new URL(req.url).pathname === '/fk') {
      const src = (req.headers.get('Origin') || '') + ' ' + (req.headers.get('Referer') || '');
      const mine = src.includes('frankf19-19.github.io') || src.includes('localhost');
      if (!mine) return new Response('forbidden', { status: 403, headers: cors });
      const k = (env && env.FUGLE_KEY) || '';
      if (!k) return new Response('not set', { status: 404, headers: cors });
      return new Response(JSON.stringify({ k }), {
        headers: { ...cors, 'content-type': 'application/json', 'cache-control': 'no-store' }
      });
    }

    const u = new URL(req.url).searchParams.get('url');
    if (!u) return new Response('missing ?url=', { status: 400, headers: cors });

    let t;
    try { t = new URL(u); } catch (e) {
      return new Response('bad url', { status: 400, headers: cors });
    }
    if (t.protocol !== 'https:' || !ALLOW.has(t.hostname))
      return new Response('host not allowed', { status: 403, headers: cors });

    const init = {
      method: req.method,
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept': '*/*',
        'Referer': t.origin + '/'
      }
    };
    if (req.method === 'POST') {
      init.body = await req.arrayBuffer();
      const ct = req.headers.get('content-type');
      if (ct) init.headers['Content-Type'] = ct;
    }

    let r;
    try { r = await fetch(t.toString(), init); } catch (e) {
      return new Response('upstream error: ' + e.message, { status: 502, headers: cors });
    }
    const h = new Headers(cors);
    const ct = r.headers.get('content-type');
    if (ct) h.set('Content-Type', ct);
    return new Response(r.body, { status: r.status, headers: h });
  }
};
