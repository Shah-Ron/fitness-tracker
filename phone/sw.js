/* Fitness Tracker service worker, phone edition.
   Everything the app needs is precached, so once it has loaded on the phone
   it opens with no connection at all. The build stamps 5700bbca8cb3 so any change
   to the app rolls the cache. There is no server to talk to; nothing is proxied. */
"use strict";

const VERSION = "5700bbca8cb3";
const CACHE = "fitness-phone-" + VERSION;
const FILES = ["./", "./index.html", "./app.js", "./engine.js", "./store.js", "./local-api.js", "./manifest.webmanifest",
  "./icon-192.png", "./icon-512.png", "./icon-maskable-512.png", "./version.json",
  "./data/exercises.json", "./data/programme.json", "./data/foods.json"];

self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE).then(c => c.addAll(FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter(n => n.startsWith("fitness-phone-") && n !== CACHE).map(n => caches.delete(n)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", event => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;       // Open Food Facts goes straight through
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const hit = await cache.match(req, { ignoreSearch: true });
    if (hit) return hit;
    try {
      const res = await fetch(req);
      if (res.ok) cache.put(req, res.clone());
      return res;
    } catch (e) {
      if (req.mode === "navigate") return cache.match("./index.html");
      return new Response("", { status: 503 });
    }
  })());
});

self.addEventListener("message", event => {
  if (event.data && event.data.type === "version" && event.source) event.source.postMessage({ type: "version", version: VERSION });
});
