/* WH40k Battle App — offline shell for static assets (not full gameplay). */
const CACHE = "wh40k-battle-shell-v1";
const PRECACHE = [
    "/wh40k/app",
    "/wh40k/manifest.webmanifest",
    "/wh40k_companion/static/description/icon.png",
];

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches
            .open(CACHE)
            .then((cache) => cache.addAll(PRECACHE))
            .then(() => self.skipWaiting())
            .catch(() => self.skipWaiting())
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches
            .keys()
            .then((keys) =>
                Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
            )
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", (event) => {
    const req = event.request;
    if (req.method !== "GET") {
        return;
    }
    const url = new URL(req.url);
    // Never cache JSON-RPC / API — always network.
    if (url.pathname.startsWith("/wh40k/api/")) {
        return;
    }
    // Cache-first for module static assets and manifest/icons.
    const isStatic =
        url.pathname.startsWith("/wh40k_companion/static/") ||
        url.pathname === "/wh40k/manifest.webmanifest" ||
        url.pathname === "/wh40k/sw.js" ||
        url.pathname.endsWith(".css") ||
        url.pathname.endsWith(".js") ||
        url.pathname.endsWith(".png") ||
        url.pathname.endsWith(".webmanifest");
    if (!isStatic && url.pathname !== "/wh40k/app") {
        return;
    }
    event.respondWith(
        caches.match(req).then((cached) => {
            const fetched = fetch(req)
                .then((resp) => {
                    if (resp && resp.ok && isStatic) {
                        const clone = resp.clone();
                        caches.open(CACHE).then((cache) => cache.put(req, clone));
                    }
                    return resp;
                })
                .catch(() => cached);
            return cached || fetched;
        })
    );
});
