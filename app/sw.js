/* The brochure as a web app: every file kept on the phone, so it opens with no network at all.
   The build writes manifest.json (version + every file with its hash). On each visit this worker asks the server
   for manifest.json; when the version changed it fetches the new files into a fresh cache, then tells the page
   ({contentReady}), which offers "Show" → reload. Old caches go once the new one is complete. */
const PREFIX = "brochure-";
const ENTRY = ["index.html", "manifest.json"];

async function manifestFrom(cacheOrNet) {
  const r = await cacheOrNet; if (!r) return null;
  try { return await r.clone().json(); } catch (e) { return null; }
}

async function fill(version, files) {
  const cache = await caches.open(PREFIX + version);
  const have = new Set((await cache.keys()).map(r => new URL(r.url).pathname.split("/").pop()));
  const names = [...new Set([...ENTRY, ...Object.keys(files)])];
  // files the previous version already holds are copied, not fetched again
  const olds = (await caches.keys()).filter(k => k.startsWith(PREFIX) && k !== PREFIX + version);
  const prev = olds.length ? await caches.open(olds[olds.length - 1]) : null;
  const prevManifest = prev ? await manifestFrom(prev.match("manifest.json")) : null;
  for (const name of names) {
    if (have.has(name.split("/").pop()) && name !== "manifest.json") continue;
    const same = prev && prevManifest && name !== "manifest.json" && prevManifest.files?.[name]?.sha256 === files[name]?.sha256;
    const hit = same ? await prev.match(name) : null;
    if (hit) { await cache.put(name, hit.clone()); continue; }
    const r = await fetch(name, { cache: "no-cache" });
    if (!r.ok) throw new Error("missing " + name);
    await cache.put(name, r);
  }
  for (const k of olds) await caches.delete(k);
  return cache;
}

self.addEventListener("install", e => {
  e.waitUntil((async () => {
    const m = await manifestFrom(fetch("manifest.json", { cache: "no-cache" }));
    if (m) await fill(m.version, m.files);
    await self.skipWaiting();
  })());
});
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin || e.request.method !== "GET") return;
  e.respondWith((async () => {
    const hit = await caches.match(e.request, { ignoreSearch: true });
    if (hit) return hit;
    try { return await fetch(e.request); }
    catch (err) { return (await caches.match("index.html")) || Response.error(); }
  })());
});

// the page asks on each open: {check: true}
self.addEventListener("message", e => {
  if (!e.data?.check) return;
  e.waitUntil((async () => {
    let m = null;
    try { m = await manifestFrom(fetch("manifest.json", { cache: "no-cache" })); } catch (err) { return; }
    if (!m) return;
    const current = (await caches.keys()).filter(k => k.startsWith(PREFIX)).map(k => k.slice(PREFIX.length)).sort().pop();
    if (!current || m.version.localeCompare(current, undefined, { numeric: true }) > 0) {
      try { await fill(m.version, m.files); } catch (err) { return; }
      const cs = await self.clients.matchAll({ type: "window" });
      cs.forEach(c => c.postMessage({ contentReady: m.version }));
    }
  })());
});
