
/* ═══════════════════════════════════════════════════════════════════════════
   r847:AI Pick 即時哨兵 —— 每分鐘(台北 09:00–13:35 週一至五)
   讀 aipick.json → 證交所 MIS 即時價 → 成交/追價/停利/停損 → 直接 Web Push(VAPID,不經 GitHub)
   狀態存 KV(PUSH)去重:sent:<date>:<sid>:<kind>
   需要 secret:VAPID_PRIVATE(pywebpush 用的同一把,base64url 32 bytes 或 PEM)
   ═══════════════════════════════════════════════════════════════════════════ */
const SENT_SITE = 'https://frankf19-19.github.io/Stock/';
const SENT_RAW  = 'https://raw.githubusercontent.com/frankf19-19/Stock/main/';
const VAPID_PUB = 'BFrDuw2hruCLJLNkaoBNC-pXPM8WZt8udHaoQ2mGzFNAqWojcqMgGiEMqaQgnjGy1u8FofvsBmpKS2IErmzA6U4';
const VAPID_SUB = 'mailto:frankccc199@hotmail.com';

function tpe(now) {                                            // 台北時間各欄位
  const t = new Date(now.getTime() + 8 * 3600 * 1000);
  return { y: t.getUTCFullYear(), m: t.getUTCMonth() + 1, d: t.getUTCDate(), dow: t.getUTCDay(), hh: t.getUTCHours(), mm: t.getUTCMinutes(),
           date: t.toISOString().slice(0, 10), hhmm: String(t.getUTCHours()).padStart(2, '0') + ':' + String(t.getUTCMinutes()).padStart(2, '0') };
}
function inMarket(T) { const m = T.hh * 60 + T.mm; return T.dow >= 1 && T.dow <= 5 && m >= 9 * 60 && m <= 13 * 60 + 35; }

async function sentinel(env, now) {
  const T = tpe(now);
  if (!inMarket(T)) return 'off-hours';
  if (!env.VAPID_PRIVATE) return 'VAPID_PRIVATE 未設';
  const r = await fetch(SENT_RAW + 'aipick.json?t=' + Math.floor(now.getTime() / 60000), { cf: { cacheTtl: 0 } });
  if (!r.ok) return 'aipick.json ' + r.status;
  const J = await r.json();
  // 本週活躍的 picks
  const active = [];
  for (const w of (J.weeks || [])) {
    if (w.bt || w.status === 'done') continue;
    const bw = w.buy_week; if (!bw) continue;
    const bwEnd = new Date(bw + 'T00:00:00Z'); bwEnd.setUTCDate(bwEnd.getUTCDate() + 4);
    const evEnd = w.eval_week ? new Date(w.eval_week + 'T00:00:00Z') : bwEnd; evEnd.setUTCDate(evEnd.getUTCDate() + 4);
    const today = new Date(T.date + 'T00:00:00Z');
    if (today < new Date(bw + 'T00:00:00Z') || today > evEnd) continue;
    for (const p of (w.picks || [])) {
      const legs = p.legs || []; const cur = legs.length ? legs[legs.length - 1] : null;
      if (cur && cur.xd) continue;                                  // 已收工
      const iv = p.iv || {};
      const inBuyWeek = today <= bwEnd;
      active.push({ p, cur, iv, inBuyWeek, sid: cur ? cur.id : p.id, name: cur ? (cur.name || p.name) : p.name });
    }
  }
  if (!active.length) return 'no active picks';
  // 即時價:每檔同時試 tse/otc
  const ch = []; for (const a of active) ch.push(`tse_${a.sid}.tw`, `otc_${a.sid}.tw`);
  const mis = 'https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=' + ch.join('|') + '&json=1&delay=0&_=' + Date.now();
  const q = await fetch(mis, { headers: { 'Accept': 'application/json', 'Referer': 'https://mis.twse.com.tw/stock/index.jsp', 'User-Agent': 'Mozilla/5.0' } });
  if (!q.ok) return 'MIS ' + q.status;
  const M = await q.json().catch(() => null); const arr = (M && M.msgArray) || [];
  const px = {}; for (const m of arr) { const v = parseFloat(m.z); const c = m.c; if (c && v > 0) px[c] = v; }   // z = 最新成交價(- 表示無)
  const events = [];
  for (const a of active) {
    const cur = px[a.sid]; if (!cur) continue;
    const p = a.p;
    if (!a.cur) {                                                     // 等買進
      if (!a.inBuyWeek || a.iv.fill) continue;
      if (cur <= p.buy) events.push({ sid: a.sid, kind: 'fill', title: `🤖 AI Pick 成交 ${a.name}`, body: `${T.hhmm} 現價 ${cur} ≤ 買價 ${p.buy}——限價成交。目標 ${p.target}、停損 ${p.stop}` });
      else if (cur <= (p.buy_hi || p.buy)) events.push({ sid: a.sid, kind: 'chase', title: `🤖 AI Pick 追價成交 ${a.name}`, body: `${T.hhmm} 現價 ${cur} 在追價上限 ${p.buy_hi} 內——以現價買進。目標 ${p.target}、停損 ${p.stop}` });
    } else {                                                          // 持有中
      const L = a.cur; if (a.iv.exit && a.iv.exit.leg === (p.legs || []).length - 1) continue;
      if (cur >= L.target) events.push({ sid: a.sid, kind: 'tp', title: `🎯 AI Pick 停利 ${a.name}`, body: `${T.hhmm} 現價 ${cur} ≥ 目標 ${L.target}(進場 ${L.entry},+${((L.target / L.entry - 1) * 100).toFixed(1)}%)——出場` });
      else if (cur <= L.stop) events.push({ sid: a.sid, kind: 'sl', title: `🛑 AI Pick 停損 ${a.name}`, body: `${T.hhmm} 現價 ${cur} ≤ 停損 ${L.stop}(進場 ${L.entry},${((L.stop / L.entry - 1) * 100).toFixed(1)}%)——出場` });
      else if (cur >= L.entry + (L.target - L.entry) * 0.8) events.push({ sid: a.sid, kind: 'near_tp', title: `📈 AI Pick 接近目標 ${a.name}`, body: `${T.hhmm} 現價 ${cur},距目標 ${L.target} 只差 ${((L.target / cur - 1) * 100).toFixed(1)}%` });
      else if (cur <= L.entry - (L.entry - L.stop) * 0.8) events.push({ sid: a.sid, kind: 'near_sl', title: `⚠️ AI Pick 逼近停損 ${a.name}`, body: `${T.hhmm} 現價 ${cur},距停損 ${L.stop} 只剩 ${((cur / L.stop - 1) * 100).toFixed(1)}%` });
    }
  }
  if (!events.length) return `ok ${active.length} picks, no event`;
  // 去重 + 推播
  const subs = await allSubs(env);
  let sent = 0, skipped = 0;
  for (const ev of events) {
    const key = `sent:${T.date}:${ev.sid}:${ev.kind}`;
    if (await env.PUSH.get(key)) { skipped++; continue; }
    await env.PUSH.put(key, T.hhmm, { expirationTtl: 36 * 3600 });
    const n = await pushAll(env, subs, ev.title, ev.body, SENT_SITE + '#aipick');
    sent += n;
    await env.PUSH.put(`sentlog:${T.date}:${T.hhmm}:${ev.sid}:${ev.kind}`, JSON.stringify(ev), { expirationTtl: 7 * 86400 });
  }
  return `events ${events.length}, pushed ${sent}, dup ${skipped}`;
}

async function allSubs(env) {
  const out = []; let cursor;
  do {
    const l = await env.PUSH.list({ prefix: 'u:', cursor });
    for (const k of l.keys) { const v = await env.PUSH.get(k.name, 'json'); if (!v) continue;
      const cats = v.cats; const want = !Array.isArray(cats) || cats.includes('aip') || cats.some(c => ['fill', 'chase', 'tp', 'sl'].includes(c));
      if (!want) continue;
      for (const s of Object.values(v.subs || {})) if (s && s.endpoint) out.push(s); }
    cursor = l.list_complete ? null : l.cursor;
  } while (cursor);
  return out;
}

async function pushAll(env, subs, title, body, url) {
  let n = 0;
  for (const s of subs) { try { const ok = await webPush(env, s, JSON.stringify({ title, body, url })); if (ok) n++; } catch (e) { console.log('push fail', String(e).slice(0, 120)); } }
  return n;
}

/* ── Web Push(RFC 8291 aes128gcm + VAPID ES256)── */
const b64u = { enc: b => btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''),
               dec: s => { s = s.replace(/-/g, '+').replace(/_/g, '/'); while (s.length % 4) s += '='; return Uint8Array.from(atob(s), c => c.charCodeAt(0)); } };
const te = new TextEncoder();
function cat(...arrs) { const n = arrs.reduce((a, b) => a + b.length, 0); const o = new Uint8Array(n); let p = 0; for (const a of arrs) { o.set(a, p); p += a.length; } return o; }
async function hkdf(salt, ikm, info, len) {
  const k = await crypto.subtle.importKey('raw', ikm, 'HKDF', false, ['deriveBits']);
  return new Uint8Array(await crypto.subtle.deriveBits({ name: 'HKDF', hash: 'SHA-256', salt, info }, k, len * 8));
}
let _vapidKey = null;
async function vapidKey(env) {
  if (_vapidKey) return _vapidKey;
  const raw = env.VAPID_PRIVATE.trim();
  if (raw.includes('BEGIN')) {                                          // PEM(pkcs8)
    const b = raw.replace(/-----[^-]+-----/g, '').replace(/\s+/g, '');
    _vapidKey = await crypto.subtle.importKey('pkcs8', b64u.dec(b), { name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign']);
  } else {                                                              // base64url 32 bytes d + 公鑰 x,y
    const pub = b64u.dec(VAPID_PUB);
    const jwk = { kty: 'EC', crv: 'P-256', d: raw.replace(/=+$/, ''), x: b64u.enc(pub.slice(1, 33)), y: b64u.enc(pub.slice(33, 65)), ext: true };
    _vapidKey = await crypto.subtle.importKey('jwk', jwk, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign']);
  }
  return _vapidKey;
}
async function vapidAuth(env, endpoint) {
  const aud = new URL(endpoint).origin;
  const hdr = b64u.enc(te.encode(JSON.stringify({ typ: 'JWT', alg: 'ES256' })));
  const clm = b64u.enc(te.encode(JSON.stringify({ aud, exp: Math.floor(Date.now() / 1000) + 12 * 3600, sub: VAPID_SUB })));
  const sig = await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, await vapidKey(env), te.encode(hdr + '.' + clm));
  return `vapid t=${hdr}.${clm}.${b64u.enc(sig)}, k=${VAPID_PUB}`;
}
async function webPush(env, sub, payload) {
  const clientPub = b64u.dec(sub.keys.p256dh), auth = b64u.dec(sub.keys.auth);
  const local = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']);
  const localPub = new Uint8Array(await crypto.subtle.exportKey('raw', local.publicKey));
  const cpk = await crypto.subtle.importKey('raw', clientPub, { name: 'ECDH', namedCurve: 'P-256' }, false, []);
  const shared = new Uint8Array(await crypto.subtle.deriveBits({ name: 'ECDH', public: cpk }, local.privateKey, 256));
  const prk = await hkdf(auth, shared, cat(te.encode('WebPush: info\0'), clientPub, localPub), 32);
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const cek = await hkdf(salt, prk, te.encode('Content-Encoding: aes128gcm\0'), 16);
  const nonce = await hkdf(salt, prk, te.encode('Content-Encoding: nonce\0'), 12);
  const plain = cat(te.encode(payload), new Uint8Array([2]));         // 最後一筆記錄的 padding delimiter
  const key = await crypto.subtle.importKey('raw', cek, 'AES-GCM', false, ['encrypt']);
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv: nonce }, key, plain));
  const rs = new Uint8Array([0, 0, 16, 0]);                             // 4096
  const body = cat(salt, rs, new Uint8Array([localPub.length]), localPub, ct);
  const res = await fetch(sub.endpoint, { method: 'POST', headers: { 'Content-Encoding': 'aes128gcm', 'Content-Type': 'application/octet-stream', 'TTL': '21600', 'Urgency': 'high', 'Authorization': await vapidAuth(env, sub.endpoint) }, body });
  if (res.status === 404 || res.status === 410) console.log('sub gone', res.status);
  return res.status >= 200 && res.status < 300;
}
