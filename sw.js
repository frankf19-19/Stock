/* K研所 PWA Service Worker v2(r900)
   策略:仍是「網路優先」(push 整檔即更新);網路失敗才回快取。
   r900 修正:v1 把每個帶 ?t=/?v= 的網址都存一份 → 一台電腦累積 266 份 data.json、1.6GB。
     • 快取鍵一律去掉查詢字串:同一個檔案只留最新一份
     • 只清自己的舊快取(stock-pwa-*),不動同網域其他專案的快取
     • 超過 8MB 的回應不進快取 */
const CACHE = 'stock-pwa-v3';
self.addEventListener('install', e => { self.skipWaiting(); });
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks =>
    Promise.all(ks.filter(k => k.startsWith('stock-pwa-') && k !== CACHE).map(k => caches.delete(k)))
  ).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;      // 外部資源(CDN/代理/TV)不攔
  if (!url.pathname.startsWith('/Stock/')) return; // 同網域其他專案不攔
  const key = url.origin + url.pathname;            // 去掉查詢字串:每個檔案只留一份
  // r925:仍是網路優先,但網路 5 秒沒回應且本機有快取 → 先用快取把畫面開起來(背景照樣更新快取),
  //      不再「開起來就卡在載入中」;網路失敗也回快取
  // r1153:快取寫入納入 SW 生命週期;離線只對頁面導覽回傳 HTML。
  const cached = () => caches.open(CACHE).then(c => c.match(key));
  const net = fetch(req).then(async r => {
    try {
      const len = +(r.headers.get('content-length') || 0);
      if (r.ok && r.type === 'basic' && (!len || len < 8e6)) {
        const c = await caches.open(CACHE);
        await c.put(key, r.clone());
      }
    } catch (err) {} // 儲存空間不足不能阻擋正常網路回應
    return r;
  });
  e.waitUntil(net.catch(() => {}));
  const fallback = async () => {
    const hit = await cached();
    if (hit) return hit;
    if (req.mode === 'navigate') {
      const c = await caches.open(CACHE);
      const shell = await c.match(url.origin + '/Stock/index.html')
        || await c.match(url.origin + '/Stock/');
      if (shell) return shell;
    }
    return Response.error(); // JSON/JS 缺快取時維持失敗,讓呼叫端正確處理
  };
  e.respondWith(new Promise(resolve => {
    let done = false;
    const timer = setTimeout(() => {
      cached().then(hit => {
        if (hit && !done) { done = true; resolve(hit); }
      }).catch(() => {});
    }, 5000);
    net.then(r => { clearTimeout(timer); if (!done) { done = true; resolve(r); } })
       .catch(() => {
         clearTimeout(timer);
         if (!done) { done = true; fallback().then(resolve, () => resolve(Response.error())); }
       });
  }));
});

/* ═══ r784:Web Push ═══
   後端 notify.py 用 VAPID 推;這裡負責把 payload 變成系統通知、點了開對應頁面。
   payload:{title, body, url, tag} */
/* r1152:AI Pick 推播的股票名稱原本放在標題最後(「🇺🇸 ⚠️ 美股 AI Pick 逼近停損 Astera Labs」),
   iPhone 鎖屏只顯示到「美股 AI Pick…」就截斷,看不出是哪一檔 → 顯示前把名稱搬到最前面:
   「🇺🇸 Astera Labs ⚠️逼近停損」;對不上格式就原樣顯示 */
function aipTitle(t) {
  try {
    const m = String(t || '').match(/^\s*((?:🇺🇸|🇹🇼)\s*)?(\S+?)\s*(?:美股|台股)?\s*AI\s*Pick[\s・:：|｜-]+([^\s\d・:：|｜]{2,8})[\s・:：|｜-]+(.+?)\s*$/u);
    if (!m) return t;
    const flag = (m[1] || '').trim(), ic = m[2], act = m[3], name = m[4];
    return `${flag ? flag + ' ' : ''}${name} ${ic}${act}`;
  } catch (err) { return t; }
}
// r1168: 只對已知獨立事件tag靜默更新；未升級的哨兵tag保留原提醒方式。
function noticeRenotify(tag){return !/^kyansuo-(?:[0-9a-f]{20}$|(?:fz|fh|fl|fb|ftp|fsl)-)/.test(String(tag||''));}
self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) { d = { body: e.data ? e.data.text() : '' }; }
  const title = aipTitle(d.title || 'K研所');
  e.waitUntil(self.registration.showNotification(title, {
    body: d.body || '',
    icon: './icon192.png',
    badge: './icon192.png',
    tag: d.tag || 'kyansuo',
    renotify: noticeRenotify(d.tag),
    data: { url: d.url || './' }
  }));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || './';
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(cs => {
    for (const c of cs) { if ('focus' in c) { c.navigate(url); return c.focus(); } }
    return self.clients.openWindow(url);
  }));
});
