/* K研所 PWA Service Worker v2(r900)
   策略:仍是「網路優先」(push 整檔即更新);網路失敗才回快取。
   r900 修正:v1 把每個帶 ?t=/?v= 的網址都存一份 → 一台電腦累積 266 份 data.json、1.6GB。
     • 快取鍵一律去掉查詢字串:同一個檔案只留最新一份
     • 只清自己的舊快取(stock-pwa-*),不動同網域其他專案的快取
     • 超過 8MB 的回應不進快取 */
const CACHE = 'stock-pwa-v2';
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
  e.respondWith(
    fetch(req).then(r => {
      try {
        const len = +(r.headers.get('content-length') || 0);
        if (r && r.ok && r.type === 'basic' && (!len || len < 8e6)) {
          const cp = r.clone();
          caches.open(CACHE).then(c => c.put(key, cp));
        }
      } catch (err) {}
      return r;
    }).catch(() => caches.match(key).then(hit => hit || caches.match(url.origin + '/Stock/index.html') || caches.match('./index.html')))
  );
});

/* ═══ r784:Web Push ═══
   後端 notify.py 用 VAPID 推;這裡負責把 payload 變成系統通知、點了開對應頁面。
   payload:{title, body, url, tag} */
self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) { d = { body: e.data ? e.data.text() : '' }; }
  const title = d.title || 'K研所';
  e.waitUntil(self.registration.showNotification(title, {
    body: d.body || '',
    icon: './icon192.png',
    badge: './icon192.png',
    tag: d.tag || 'kyansuo',
    renotify: true,
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
