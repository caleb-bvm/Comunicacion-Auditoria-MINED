{% autoescape off %}// Service worker de SIGA-MINEDUCYT (lo genera apps/core/views.py:service_worker).
// Solo guarda la página «Sin conexión» y sus estilos: nunca guarda páginas ni archivos
// del sistema, que son privados. Si una página no se puede abrir porque el dispositivo
// no llega al servidor, muestra esa página en lugar del error del navegador.
const CACHE_NAME = {{ cache_name }};
const CACHE_PREFIX = "siga-sin-conexion-";
const OFFLINE_URL = {{ offline_url }};
const ASSETS = {{ assets }};

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => cache.addAll(ASSETS.map((url) => new Request(url, { cache: "reload" }))))
            .then(() => self.skipWaiting()),
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys()
            .then((names) => Promise.all(
                names.filter((name) => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME)
                    .map((name) => caches.delete(name)),
            ))
            .then(() => self.clients.claim()),
    );
});

self.addEventListener("fetch", (event) => {
    const { request } = event;
    if (request.method !== "GET") return;
    if (request.mode === "navigate") {
        // Solo un fallo de red llega al catch: los errores del servidor (404, 500, 502)
        // siguen mostrando su propia página.
        event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
        return;
    }
    const url = new URL(request.url);
    if (url.origin === self.location.origin && ASSETS.includes(url.pathname)) {
        event.respondWith(fetch(request).catch(() => caches.match(url.pathname)));
    }
});
{% endautoescape %}