// Service worker minimal : rend l'application installable et garde l'interface disponible hors ligne.
const CACHE = "souvenirs-v1";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  if (e.request.mode === "navigate") {
    // page : réseau d'abord, copie en cache si le réseau manque
    e.respondWith(
      fetch(e.request).then((r) => {
        const copy = r.clone();
        caches.open(CACHE).then((c) => c.put("/__shell", copy));
        return r;
      }).catch(() => caches.match("/__shell"))
    );
    return;
  }
  e.respondWith(
    caches.match(e.request).then((hit) => hit || fetch(e.request).then((r) => {
      if (r.ok && (url.pathname.startsWith("/assets/") || url.pathname.endsWith(".png"))) {
        const copy = r.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
      }
      return r;
    }))
  );
});
