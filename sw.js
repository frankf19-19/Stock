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
