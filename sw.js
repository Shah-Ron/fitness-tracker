/* Fitness Tracker service worker.
   Keeps the page shell and the last good copy of a few API answers so the
   phone can open the app and log sets at the gym with no connection, and
   flushes the write queue when a connection comes back. The server swaps
   __BUILD__ for a stamp of the page files, so any edit rolls this worker. */
"use strict";

const VERSION = "__BUILD__";
const SHELL = "shell-" + VERSION;
const API = "api";
const PRECACHE = ["/", "/manifest.webmanifest", "/icon-192.png", "/icon-512.png", "/icon-maskable-512.png"];
const CACHED_API = ["/api/today", "/api/state", "/api/exercises", "/api/foods/list", "/api/plan/week", "/api/settings"];
const NETWORK_TIMEOUT_MS = 3000;

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(SHELL).then(cache => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter(n => n.startsWith("shell-") && n !== SHELL).map(n => caches.delete(n)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", event => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  const path = url.pathname;

  // A pairing link must reach the server so the cookie gets set.
  if (url.searchParams.has("key")) return;

  if (req.mode === "navigate" || path === "/" || path === "/app.html" || path === "/index.html") {
    event.respondWith(shellFirst(req));
    return;
  }
  if (PRECACHE.includes(path)) {
    event.respondWith(cacheFirst(req));
    return;
  }
  if (CACHED_API.includes(path)) {
    event.respondWith(networkFirst(req));
  }
});

async function shellFirst(req) {
  const cache = await caches.open(SHELL);
  const hit = await cache.match("/", { ignoreSearch: true });
  if (hit) return hit;
  try {
    const res = await fetch(req);
    if (res.ok) cache.put("/", res.clone());
    return res;
  } catch (e) {
    return new Response("<h1>Offline</h1><p>Open Fitness Tracker once on home wifi so it can be saved to this phone.</p>",
      { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } });
  }
}

async function cacheFirst(req) {
  const cache = await caches.open(SHELL);
  const hit = await cache.match(req, { ignoreSearch: true });
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) cache.put(req, res.clone());
  return res;
}

async function networkFirst(req) {
  const cache = await caches.open(API);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), NETWORK_TIMEOUT_MS);
  try {
    const res = await fetch(req, { signal: ctrl.signal });
    clearTimeout(timer);
    if (res.ok) cache.put(req, res.clone());      // never keep a 401 or a 500
    return res;
  } catch (e) {
    clearTimeout(timer);
    const hit = await cache.match(req);
    if (hit) return hit;
    return new Response(JSON.stringify({ error: "offline" }), { status: 503, headers: { "Content-Type": "application/json" } });
  }
}

self.addEventListener("message", event => {
  if (event.data && event.data.type === "version" && event.source) {
    event.source.postMessage({ type: "version", version: VERSION });
  }
});

/* Background Sync: Chrome retries a few times with backoff, which is a bonus.
   The page flushes the same queue whenever it is open and online. */
self.addEventListener("sync", event => {
  if (event.tag === "flush") event.waitUntil(flushQueue());
});

function openQueue() {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open("fitness", 1);
    open.onupgradeneeded = () => { if (!open.result.objectStoreNames.contains("queue")) open.result.createObjectStore("queue", { keyPath: "client_id" }); };
    open.onsuccess = () => resolve(open.result);
    open.onerror = () => reject(open.error);
  });
}

function allOps(db) {
  return new Promise((resolve, reject) => {
    const req = db.transaction("queue", "readonly").objectStore("queue").getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror = () => reject(req.error);
  });
}

function deleteOps(db, ids) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction("queue", "readwrite");
    const store = tx.objectStore("queue");
    ids.forEach(id => store.delete(id));
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function flushQueue() {
  const db = await openQueue();
  const ops = (await allOps(db)).sort((a, b) => (a.at || "").localeCompare(b.at || ""));
  if (!ops.length) return;
  const res = await fetch("/api/sync", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ device: "sw", ops: ops.slice(0, 200) }),
  });
  if (!res.ok) throw new Error("sync failed " + res.status);
  const out = await res.json();
  const gone = (out.applied || []).concat((out.rejected || []).filter(r => !r.retry).map(r => r.client_id));
  if (gone.length) await deleteOps(db, gone);
  const clients = await self.clients.matchAll({ type: "window" });
  clients.forEach(c => c.postMessage({ type: "flushed", applied: (out.applied || []).length }));
}
