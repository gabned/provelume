"use strict";
const CACHE = "provelume-capture-public-__CAPTURE_SHELL_REVISION__";
const PUBLIC = ["/capture/", "/capture/shell.js", "/capture/style.css", "/capture/manifest.webmanifest", "/capture/icon.svg", "/capture/icon192.png", "/capture/icon512.png"];
const MAX_FILE = 256 * 1024;
self.addEventListener("install", event => event.waitUntil((async () => {
  const cache = await caches.open(CACHE);
  for (const path of PUBLIC) {
    const response = await fetch(path, {credentials: "omit", cache: "no-store"});
    if (!response.ok || response.headers.has("Set-Cookie")) throw new Error("Public shell unavailable");
    const bytes = await response.arrayBuffer();
    if (bytes.byteLength > MAX_FILE) throw new Error("Public shell size bound");
    await cache.put(path, new Response(bytes, {status: 200, headers: response.headers}));
  }
})()));
self.addEventListener("activate", event => event.waitUntil((async () => {
  for (const key of await caches.keys()) if (key.startsWith("provelume-capture-public-") && key !== CACHE) await caches.delete(key);
  await self.clients.claim();
})()));
self.addEventListener("fetch", event => {
  const request = event.request, url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin || url.search ||
      !PUBLIC.includes(url.pathname) || request.headers.has("Authorization") || request.headers.has("X-Capture-Nonce")) return;
  event.respondWith((async () => {
    try { return await fetch(request); }
    catch (error) { const saved = await caches.match(url.pathname, {cacheName: CACHE}); if (saved) return saved; throw error; }
  })());
});
