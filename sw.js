/* 麻吉股研所 PWA Service Worker v1
   策略:一律「網路優先」——保持你 push 整檔即更新的部署習慣;
   網路失敗才回快取(離線時至少能開出最後一次看過的頁面與資料)。 */
const CACHE = 'stock-pwa-v1';
self.addEventListener('install', e => { self.skipWaiting(); });
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks =>
    Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;      // 外部資源(CDN/代理/TV)不攔,行為與瀏覽器相同
  e.respondWith(
    fetch(req).then(r => {
      try {
        if (r && r.ok) {                             // 只快取成功回應,404/500 不汙染快取
          const cp = r.clone();
          caches.open(CACHE).then(c => c.put(req, cp));
        }
      } catch (err) {}
      return r;
    }).catch(() => caches.match(req, { ignoreSearch: url.pathname.endsWith('.json') })
      .then(hit => hit || caches.match('./index.html')))
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
