/* WH40k Battle App — cache static assets only. Documents stay on the network. */
const CACHE = "wh40k-battle-shell-v2";
const PRECACHE = [
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

function isAppDocument(req, url) {
    // A cached /wh40k/app shell keeps old asset URLs. The next full navigation
    // (join redirect, refresh, manifest start_url) then paints an empty body.
    return (
        req.mode === "navigate" ||
        url.pathname === "/wh40k/app" ||
        url.pathname.startsWith("/wh40k/join") ||
        url.pathname === "/wh40k/sw.js"
    );
}

self.addEventListener("fetch", (event) => {
    const req = event.request;
    if (req.method !== "GET") {
        return;
    }
    const url = new URL(req.url);
    if (url.origin !== self.location.origin) {
        return;
    }
    if (url.pathname.startsWith("/wh40k/api/") || isAppDocument(req, url)) {
        event.respondWith(fetch(req));
        return;
    }
    const isStatic =
        url.pathname.startsWith("/wh40k_companion/static/") ||
        url.pathname === "/wh40k/manifest.webmanifest" ||
        url.pathname.endsWith(".css") ||
        url.pathname.endsWith(".js") ||
        url.pathname.endsWith(".png") ||
        url.pathname.endsWith(".webmanifest");
    if (!isStatic) {
        return;
    }
    event.respondWith(
        fetch(req)
            .then((resp) => {
                if (resp && resp.ok) {
                    const clone = resp.clone();
                    caches.open(CACHE).then((cache) => cache.put(req, clone));
                }
                return resp;
            })
            .catch(async () => (await caches.match(req)) || Response.error())
    );
});