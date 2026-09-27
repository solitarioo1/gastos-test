// Solo se guardan archivos estáticos (estilos, scripts, iconos) para abrir más rápido y
// aguantar una caída de internet. Los datos (/api/*) y las páginas nunca se guardan.
const CACHE = "tusgastos-v1";
const PRECARGA = [
  "/static/vendor/tabler/tabler.min.css",
  "/static/vendor/tabler/tabler.min.js",
  "/static/style.css",
  "/static/common.js",
];

const SIN_CONEXION = `<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Sin conexión · TusGastos</title>
<style>body{font-family:system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;padding:24px;text-align:center;background:#f4f6f4;color:#1c2a25}
h1{font-size:1.4rem;margin:0 0 8px}p{margin:0 0 16px;color:#5d6b65}button{font:inherit;padding:10px 20px;border:0;border-radius:10px;background:#1c1d1f;color:#fff;font-weight:600}</style></head>
<body><main><h1>Sin conexión</h1><p>No pudimos llegar a TusGastos. Revisa tu internet e inténtalo otra vez.</p>
<button onclick="location.reload()">Reintentar</button></main></body></html>`;

self.addEventListener("install", (evento) => {
  evento.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PRECARGA)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (evento) => {
  evento.waitUntil(
    caches
      .keys()
      .then((claves) => Promise.all(claves.filter((c) => c !== CACHE).map((c) => caches.delete(c))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (evento) => {
  const pedido = evento.request;
  if (pedido.method !== "GET") return;
  const url = new URL(pedido.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/static/")) {
    // Red primero (siempre lo más nuevo); si no hay internet, lo guardado.
    evento.respondWith(
      fetch(pedido)
        .then((respuesta) => {
          if (respuesta.ok) {
            const copia = respuesta.clone();
            caches.open(CACHE).then((cache) => cache.put(pedido, copia));
          }
          return respuesta;
        })
        .catch(() => caches.match(pedido))
    );
    return;
  }

  if (pedido.mode === "navigate") {
    evento.respondWith(
      fetch(pedido).catch(
        () => new Response(SIN_CONEXION, { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } })
      )
    );
  }
});
