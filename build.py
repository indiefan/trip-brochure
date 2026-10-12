#!/usr/bin/env python3
"""Build the brochure: a trip folder (trip.json + photos + documents) → a static app folder (dist/) that works offline.

    python3 build.py sample/                 # → sample/dist
    python3 build.py mytrip/ --out /srv/trip # anywhere you like
    python3 build.py mytrip/ --fonts         # re-fetch the fonts, subset for this trip's own scripts (needs network)

What it does, in order: reads trip.json; derives the days and the legs (stays and the journeys between them);
copies and resizes the photographs; turns each document into pages (a PDF → one JPEG per page, a screenshot → a JPEG,
an email .eml/.html/.txt → a clean HTML page of its own, pictures inlined) plus a thumbnail; copies the app (index.html,
app.css, app.js, sw.js, fonts); writes data.js (everything the page needs) and manifest.json (the version and every
file's SHA-256, for updates); fetches each day's forecast from Open-Meteo (free, no key). Nothing here needs a key
or an account. The optional pipeline/ scripts add Claude-written
copy, translations and exact map places to trip.json before you build; see HANDBOOK.md.

Needs: Python 3.10+, pillow, pymupdf (PDFs), beautifulsoup4 (emails), requests (only for --fonts and remote pictures).
"""

from __future__ import annotations

import argparse
import email
import email.policy
import hashlib
import html
import io
import json
import re
import shutil
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
APP = HERE / "app"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"}
FLIGHT = re.compile(r"\b(flight|fly|airport|airline|air)\b", re.I)
TRAIN = re.compile(r"\b(train|rail|railway|shinkansen|romancecar|express)\b", re.I)


def say(*a):
    print(*a, file=sys.stderr, flush=True)


# --- pictures ------------------------------------------------------------------------------------------------------

def jpeg(data: bytes, width: int, quality: int = 84) -> bytes:
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    im = im.convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


def thumb(data: bytes, width: int = 420, ratio: float = 1.25) -> bytes:
    """The top of a page or screenshot, where the booking's name and number usually are."""
    from PIL import Image
    im = Image.open(io.BytesIO(data)).convert("RGB")
    im = im.resize((width, max(1, round(im.height * width / im.width))), Image.LANCZOS)
    im = im.crop((0, 0, width, min(im.height, round(width * ratio))))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=78, optimize=True)
    return out.getvalue()


def pdf_pages(data: bytes) -> list[bytes]:
    import pymupdf
    doc = pymupdf.open(stream=data, filetype="pdf")
    return [p.get_pixmap(dpi=170).tobytes("png") for p in doc]


# --- emails --------------------------------------------------------------------------------------------------------

def page(body: str, head: str = "") -> str:
    """A document page of the app's own: a white sheet, the system's font."""
    return ("<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\">"
            "<style>html{background:#fff}body{margin:0;padding:14px;color:#222;font:15px/1.45 -apple-system,system-ui,sans-serif;"
            "-webkit-text-size-adjust:100%;overflow-wrap:break-word}pre.plain{white-space:pre-wrap;font:inherit;margin:0}</style>"
            f"{head}</head><body>{body}</body></html>")


TRANSLATION_STYLE = ("<style>.tr{font-size:15.5px;line-height:1.5}.tr h3{font-size:17px;margin:18px 0 6px}.tr h3:first-child{margin-top:4px}"
                     ".tr table{border-collapse:collapse;width:100%;margin:8px 0}.tr td,.tr th{border-top:1px solid #e6e1d8;padding:6px 8px 6px 0;"
                     "text-align:left;vertical-align:top}.tr th{color:#6b645a;font-weight:600;width:38%}.tr ul{padding-left:20px}</style>")


def read_eml(data: bytes) -> dict:
    """An .eml (Gmail's "Show original" → Download, or Apple Mail's "Save As…"): subject, sender, date, HTML with cid
    pictures inlined, and the plain text; also PDF/image attachments as (name, mime, bytes)."""
    msg = email.message_from_bytes(data, policy=email.policy.default)
    out = {"subject": msg.get("subject", ""), "sender": msg.get("from", ""), "date": msg.get("date", ""), "html": "", "text": "", "attachments": []}
    cids = {}
    for part in msg.walk():
        ct = part.get_content_type()
        if part.get_content_disposition() == "attachment" or (part.get_filename() and ct in ("application/pdf", "image/png", "image/jpeg")):
            if ct in ("application/pdf", "image/png", "image/jpeg"):
                out["attachments"].append((part.get_filename() or "attachment", ct, part.get_payload(decode=True)))
            continue
        if ct == "text/html" and not out["html"]:
            out["html"] = part.get_content()
        elif ct == "text/plain" and not out["text"]:
            out["text"] = part.get_content()
        elif ct.startswith("image/") and part.get("Content-ID"):
            cids[part.get("Content-ID").strip("<> ")] = (ct, part.get_payload(decode=True))
    for cid, (ct, b) in cids.items():
        out["html"] = out["html"].replace(f"cid:{cid}", f"data:{ct};base64,{__import__('base64').b64encode(b).decode()}")
    return out


def email_page(raw_html: str | None, text: str, files: dict, cache: Path, fetch_remote: bool) -> str:
    """The email as a page: its HTML made safe and self-contained (scripts out, pictures brought in), or its text."""
    if not raw_html:
        clean = re.sub(r"\[image:[^\]]*\]\s*", "", text or "")
        clean = re.sub(r"\s*<(https?|mailto):[^>]*>", "", clean)
        clean = re.sub(r"\n[ \t]*\n(\s*\n)+", "\n\n", clean).strip()
        return page(f"<pre class=\"plain\">{html.escape(clean)}</pre>")
    from bs4 import BeautifulSoup

    def keep_image(url: str) -> str | None:
        if url.startswith("data:"):
            return url
        if not (url.startswith(("http://", "https://")) and fetch_remote):
            return None
        key = hashlib.sha1(url.encode()).hexdigest()[:20]
        path, miss = cache / "img" / key, cache / "img" / (key + ".none")
        if miss.exists():
            return None
        if not path.exists():
            try:
                import requests
                r = requests.get(url, headers=UA, timeout=30)
                data = r.content if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/") else None
            except Exception:
                data = None
            if not data or len(data) < 120:                        # a tracking pixel is not a picture
                miss.parent.mkdir(parents=True, exist_ok=True); miss.touch(); return None
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        data = path.read_bytes()
        ext = {b"\x89PNG": "png", b"\xff\xd8": "jpg", b"GIF8": "gif", b"RIFF": "webp"}.get(data[:4] if data[:4] == b"\x89PNG" else data[:2] if data[:2] == b"\xff\xd8" else data[:4], "img")
        name = f"docs/img/{hashlib.sha1(data).hexdigest()[:20]}.{ext}"
        files[name] = data
        return "img/" + name.split("/")[-1]

    soup = BeautifulSoup(raw_html, "html.parser")
    for t in soup(["script", "base", "iframe", "object", "embed", "form", "noscript", "link"]):
        t.decompose()
    for t in soup.find_all("meta"):
        if (t.get("http-equiv") or "").lower() == "refresh":
            t.decompose()
    for t in soup.find_all(True):
        for a in list(t.attrs):
            if a.lower().startswith("on"):
                del t[a]
        if t.name == "img":
            w, h = str(t.get("width", "")).strip("px"), str(t.get("height", "")).strip("px")
            if w in ("0", "1", "2") or h in ("0", "1", "2"):
                t.decompose(); continue
            src = keep_image(t.get("src", ""))
            if src is None:
                t.decompose(); continue
            t["src"] = src; t.attrs.pop("srcset", None)
        if t.get("style") and "url(" in t["style"]:
            t["style"] = re.sub(r"url\(['\"]?(http[^'\")]+)['\"]?\)", lambda m: f"url({keep_image(m.group(1)) or ''})", t["style"])
    for s in soup.find_all("style"):
        if s.string and "url(" in s.string:
            s.string = re.sub(r"url\(['\"]?(http[^'\")]+)['\"]?\)", lambda m: f"url({keep_image(m.group(1)) or ''})", s.string)
    for a in soup.find_all("a"):
        a["target"] = "_blank"
    head = "".join(str(x) for x in (soup.head.contents if soup.head else []) if getattr(x, "name", None) == "style")
    body = "".join(str(x) for x in soup.body.contents) if soup.body else str(soup)
    return page(body, head)


# --- the trip's shape: days and legs ---------------------------------------------------------------------------------

def days_of(trip: dict) -> list[dict]:
    d0, d1 = date.fromisoformat(trip["start"]), date.fromisoformat(trip["end"])
    out = []
    for i in range((d1 - d0).days + 1):
        d = d0 + timedelta(days=i); iso = d.isoformat()
        evs = [e for e in trip["events"] if e["date"] == iso]
        night = next((h for h in trip["hotels"] if h["start"] <= iso < h["end"]), None)
        cities = []
        for e in evs:
            for c in re.split(r"\s*(?:->|→)\s*", e.get("city") or ""):
                if c and c not in cities:
                    cities.append(c)
        out.append({"date": iso, "weekday": d.strftime("%a"), "label": d.strftime("%b ") + str(d.day), "cities": cities,
                    "travel": any("->" in (e.get("city") or "") or "→" in (e.get("city") or "") for e in evs),
                    "city": night["city"] if night else (cities[-1] if cities else None), "hotel": night["name"] if night else None,
                    "hotel_id": night["id"] if night else None, "events": [e["id"] for e in evs], "count": len(evs)})
    return out


def legs_of(trip: dict, days: list[dict]) -> list[dict]:
    """The trip as a chain: travel → stay → travel → stay … → home. A stay owns the days you sleep there; the transit
    events between two stays make the journey; what is left on the last day goes with the trip home."""
    events, hotels = trip["events"], trip["hotels"]
    by_id = {e["id"]: e for e in events}
    out, used, prev_end = [], set(), None
    transit = [e for e in events if e.get("type") == "Transit" or e.get("travel")]
    cities = trip.get("cities") or {}
    for h in hotels:
        before = [e for e in transit if e["id"] not in used and e["date"] <= h["start"] and (prev_end is None or e["date"] >= prev_end)]
        if before:
            used.update(e["id"] for e in before)
            text = " ".join((e["title"] or "") + " " + (e.get("place") or "") for e in before)
            out.append({"kind": "travel", "title": ("Fly" if FLIGHT.search(text) else "Train" if TRAIN.search(text) else "Travel") + " to " + h["city"],
                        "date": before[0]["date"], "end_date": before[-1]["date"], "events": [e["id"] for e in before]})
        stay_days = [d for d in days if h["start"] <= d["date"] < h["end"]]
        evs = [by_id[i] for d in stay_days for i in d["events"] if i not in used and by_id[i].get("type") != "Transit"]
        used.update(e["id"] for e in evs)
        picks = sorted([e for e in evs if e.get("type") != "Lodging"], key=lambda e: (e.get("status") != "booked", e["date"], e.get("start") or "99"))
        city = cities.get(h["city"], {})
        out.append({"kind": "stay", "title": h["city"], "sub": h.get("country") or city.get("country"), "nights": h.get("nights") or (date.fromisoformat(h["end"]) - date.fromisoformat(h["start"])).days,
                    "hotel": h["name"], "hotel_id": h["id"], "start": h["start"], "end": h["end"], "days": [d["date"] for d in stay_days],
                    "events": [e["id"] for e in evs], "highlights": [e["title"] for e in picks[:3]],
                    "copy": {"blurb": city.get("blurb", ""), "native": city.get("native", ""), "facts": []}, "photo": None, "_city": city})
        prev_end = h["end"]
    tail = [e for e in events if e["id"] not in used and (prev_end is None or e["date"] >= prev_end)]
    if tail:
        text = " ".join((e["title"] or "") + " " + (e.get("place") or "") + " " + (e.get("notes") or "") for e in tail)
        out.append({"kind": "travel", "title": "Fly home" if FLIGHT.search(text) else "Travel home", "date": tail[0]["date"], "end_date": tail[-1]["date"], "events": [e["id"] for e in tail]})
    return out


# --- the build -------------------------------------------------------------------------------------------------------

def build(src: Path, out: Path, refetch_fonts: bool = False, fetch_remote: bool = True, refresh_weather: bool = False, with_weather: bool = True) -> dict:
    trip = json.loads((src / "trip.json").read_text(encoding="utf-8"))
    cache = src / ".cache"
    files: dict[str, bytes] = {}
    credits: list[dict] = []

    def photo(p: dict | None, with_cover: bool = False) -> dict | None:
        """A photograph {file, focus, credit, license, page}: copied in at 1280 px (and 2400 for a cover), plus a 500 px copy."""
        if not p or not p.get("file"):
            return None
        raw = (src / p["file"]).read_bytes()
        key = hashlib.sha1(raw).hexdigest()[:16]
        files[f"photos/{key}.jpg"] = jpeg(raw, 1280, 84)
        files[f"photos/{key}-sm.jpg"] = jpeg(raw, 500, 80)
        o = {"lg": f"photos/{key}.jpg", "sm": f"photos/{key}-sm.jpg", "focus": p.get("focus") or "50% 50%"}
        if with_cover:
            files[f"photos/{key}-xl.jpg"] = jpeg(raw, 2400, 82); o["cover"] = f"photos/{key}-xl.jpg"
        if p.get("credit") and not any(c.get("page") == p.get("page") and c["credit"] == p["credit"] for c in credits):
            credits.append({"credit": p["credit"], "license": p.get("license", ""), "page": p.get("page", "")})
        return o

    def gplace(g: dict | None) -> dict | None:
        if not g:
            return None
        o = {k: g.get(k) for k in ("id", "name", "address", "lat", "lng", "local_name", "local_address", "language")}
        if g.get("map") and (src / g["map"]).exists():
            raw = (src / g["map"]).read_bytes(); key = hashlib.sha1(raw).hexdigest()[:16]
            files[f"maps/{key}.jpg"] = jpeg(raw, 1280, 86); o["map"] = f"maps/{key}.jpg"
        return o

    # documents
    docs_out = {}
    for did, d in (trip.get("docs") or {}).items():
        say(f"  document {did} ({d.get('kind', 'file')})")
        o = {"id": did, "kind": "email" if d.get("kind") == "email" else "screenshot", "subject": d.get("subject"), "sender": d.get("sender"),
             "received": d.get("received"), "pages": [], "email": None, "gmail": d.get("link")}
        pages: list[bytes] = []
        attachments = list(d.get("attachments") or [])
        f = d.get("file")
        if d.get("kind") == "email":
            raw_html = text = None
            if f and f.endswith(".eml"):
                m = read_eml((src / f).read_bytes())
                raw_html, text = m["html"], m["text"]
                o["subject"] = o["subject"] or m["subject"]; o["sender"] = o["sender"] or m["sender"]; o["sent"] = m["date"]
                for name, mime, b in m["attachments"]:
                    attachments.append(("mem", mime, b))
            elif f and f.endswith((".html", ".htm")):
                raw_html = (src / f).read_text(encoding="utf-8", errors="replace")
            elif f:
                text = (src / f).read_text(encoding="utf-8", errors="replace")
            files[f"docs/{did}.html"] = email_page(raw_html, text or "", files, cache, fetch_remote).encode()
            o["email"] = f"docs/{did}.html"; o["original"] = bool(raw_html)
            if d.get("translation"):
                t = (src / d["translation"]).read_text(encoding="utf-8")
                files[f"docs/{did}-en.html"] = (t if t.lstrip().lower().startswith("<!doctype") else page(f"<div class=\"tr\">{t}</div>", TRANSLATION_STYLE)).encode()
                o["translation"] = f"docs/{did}-en.html"; o["language"] = d.get("language") or d.get("language_en", ""); o["language_en"] = d.get("language_en", "")
        elif f:
            attachments.insert(0, f)
        for a in attachments:
            if isinstance(a, tuple):
                _, mime, b = a
            else:
                b = (src / a).read_bytes(); mime = "application/pdf" if b[:4] == b"%PDF" else "image/*"
            pages += [jpeg(p, 1400, 82) for p in pdf_pages(b)] if mime == "application/pdf" else [jpeg(b, 1290, 85)]
        for i, p in enumerate(pages, 1):
            files[f"docs/{did}-{i}.jpg"] = p; o["pages"].append(f"docs/{did}-{i}.jpg")
        if pages:
            files[f"docs/{did}-t.jpg"] = thumb(pages[0]); o["thumb"] = f"docs/{did}-t.jpg"
        docs_out[did] = o

    days = days_of(trip)
    legs = legs_of(trip, days)
    for leg in legs:
        if leg["kind"] == "stay":
            leg["photo"] = photo(leg.pop("_city").get("photo"))
    match = re.compile(re.escape(trip["cover_match"]), re.I) if trip.get("cover_match") else None   # or the photo of the event it names
    named = next((e.get("photo") for e in trip["events"] if match and e.get("photo") and match.search(e["title"])), None)
    cover = photo(trip.get("cover") or named, with_cover=True) or next((l["photo"] for l in legs if l.get("photo")), None)
    events = []
    for e in trip["events"]:
        cities = re.split(r"\s*(?:->|→)\s*", e.get("city") or "")
        events.append({"id": e["id"], "date": e["date"], "start": e.get("start"), "end": e.get("end"), "title": e["title"], "place": e.get("place"),
                       "type": e.get("type") or "Activity", "status": e.get("status") or "planned", "confirmation": e.get("confirmation"), "address": e.get("address"),
                       "link": e.get("link"), "cost": e.get("cost"), "notes": e.get("notes"), "city": e.get("city"), "travel": len([c for c in cities if c]) > 1,
                       "copy": {"blurb": e.get("blurb", ""), "facts": e.get("facts") or [], "native": ""} if e.get("blurb") or e.get("facts") else None,
                       "dest": e.get("dest"), "gplace": gplace(e.get("gplace")), "docs": [d for d in (e.get("docs") or []) if d in docs_out], "photo": photo(e.get("photo"))})
    hotels = []
    for h in trip["hotels"]:
        hotels.append({k: h.get(k) for k in ("id", "city", "country", "start", "end", "name", "room", "booking", "perks", "confirmation", "address")}
                      | {"nights": h.get("nights") or (date.fromisoformat(h["end"]) - date.fromisoformat(h["start"])).days,
                         "copy": {"blurb": h.get("blurb", ""), "facts": h.get("facts") or [], "native": ""}, "gplace": gplace(h.get("gplace"))})
    wx = weather(trip, days, cache, refresh_weather) if with_weather else None
    built = datetime.now(timezone.utc)
    data = {k: trip.get(k) for k in ("name", "title_html", "family", "seal", "farewell", "intro", "start", "end", "people", "zones", "timezone", "bundle_id", "please", "languages")}
    book = phrasebook(src, files)
    if (data.get("farewell") or {}).get("native") and book and not data["farewell"].get("lang"):   # its language, for its face
        data["farewell"] = {**data["farewell"], "lang": next(iter(book.get("languages") or {}), "")}
    data.update({"phrases": book, "weather": wx, "cities": {k: {"color": v.get("color")} for k, v in (trip.get("cities") or {}).items()}, "days": days, "legs": legs, "events": events, "hotels": hotels,
                 "docs": docs_out, "cover": cover, "credits": credits + list(trip.get("credits") or []),
                 "built": built.strftime("%Y-%m-%dT%H:%M:%SZ"), "version": built.strftime("%Y%m%d.%H%M%S")})
    files["data.js"] = ("window.TRIP = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n").encode()

    # the app itself, the fonts, the icon
    for f in APP.rglob("*"):
        if f.is_file():
            files[str(f.relative_to(APP))] = f.read_bytes()
    chars, langs, chinese = shown_chars(trip, book)
    if refetch_fonts:
        files["fonts.css"] = fonts(files, chars).encode()
    files["theme.css"] = theme_css(trip, chars, langs, chinese).encode()
    icon = src / "icon.png"
    if icon.exists():
        files["icon.png"] = icon.read_bytes()
    wm = json.loads(files["manifest.webmanifest"]); wm["name"] = wm["short_name"] = trip["name"]
    files["manifest.webmanifest"] = json.dumps(wm, indent=1).encode()

    if out.exists():
        shutil.rmtree(out)
    for name, b in files.items():
        p = out / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b)
    manifest = {"version": data["version"], "entry": "index.html", "built": data["built"],
                "files": {n: {"sha256": hashlib.sha256(b).hexdigest(), "size": len(b)} for n, b in sorted(files.items())}}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    say(f"built {len(files)} files, {sum(len(b) for b in files.values()) / 1e6:.1f} MB, version {data['version']} → {out}")
    return manifest


# --- weather: each day's forecast where you are (Open-Meteo: free, no key, about 16 days ahead) -----------------------

WEATHER_TTL = 20 * 3600            # a forecast this old is fetched again on the next build (--weather forces it)


def day_cities(day: dict) -> list[str]:
    """Where you are on a day: where you wake up, and where you sleep when that is somewhere else."""
    woke = (day.get("cities") or [None])[0]
    sleep = day.get("city") if day.get("hotel_id") else None
    return list(dict.fromkeys(c for c in (woke, sleep) if c)) or ([day["city"]] if day.get("city") else [])


def weather(trip: dict, days: list[dict], cache: Path, refresh: bool = False) -> dict:
    """{updated, days: {date: [{city, code, hi, lo, rain}]}} for the trip's days, in °F (trip.json "units": "celsius"
    for °C). trip.json may give its own "weather" block instead (a demo, or typed by hand). Kept in the trip's cache;
    asked again when older than WEATHER_TTL. Days past the forecast's reach simply have none, and a failed fetch keeps
    the last forecast."""
    if trip.get("weather"):
        return trip["weather"]
    import requests
    path = cache / "weather.json"
    old = json.loads(path.read_text()) if path.exists() else None
    key = trip["start"] + trip["end"] + trip.get("units", "")
    if old and not refresh and time.time() - old.get("at", 0) < WEATHER_TTL and old.get("key") == key:
        return old["data"]
    where = {}
    for h in trip.get("hotels", []):                                   # the hotel's own spot, when places.py found it
        g = h.get("gplace") or {}
        if g.get("lat") is not None:
            where.setdefault(h["city"], (g["lat"], g["lng"]))
    for name, c in (trip.get("cities") or {}).items():                 # or coordinates you gave the city
        if c.get("lat") is not None:
            where.setdefault(name, (c["lat"], c["lng"]))
    wanted = {d["date"]: day_cities(d) for d in days}
    today = datetime.now(timezone.utc).date()
    first, last = max(date.fromisoformat(trip["start"]), today - timedelta(days=60)), min(date.fromisoformat(trip["end"]), today + timedelta(days=15))
    out = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "days": {}}
    if first > last:
        return out
    try:
        for city in sorted({c for cs in wanted.values() for c in cs}):
            if city not in where:
                g = requests.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": city, "count": 1, "language": "en"}, timeout=30).json()
                hit = (g.get("results") or [None])[0]
                if not hit:
                    say(f"  weather: no place called {city!r}; give the city lat/lng in trip.json"); continue
                where[city] = (hit["latitude"], hit["longitude"])
            lat, lng = where[city]
            f = requests.get("https://api.open-meteo.com/v1/forecast", timeout=30, params={
                "latitude": lat, "longitude": lng, "timezone": "auto", "temperature_unit": "celsius" if trip.get("units") == "celsius" else "fahrenheit",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "start_date": first.isoformat(), "end_date": last.isoformat()}).json()["daily"]
            for i, d in enumerate(f["time"]):
                if city in wanted.get(d, []) and f["temperature_2m_max"][i] is not None:
                    out["days"].setdefault(d, []).append({"city": city, "code": f["weather_code"][i], "hi": round(f["temperature_2m_max"][i]),
                                                          "lo": round(f["temperature_2m_min"][i]), "rain": f["precipitation_probability_max"][i]})
    except Exception as e:                                               # noqa: BLE001 - no network, say: the last forecast stands
        say(f"  weather: {e}; keeping the last forecast")
        return old["data"] if old else out
    for d, items in out["days"].items():
        items.sort(key=lambda x: wanted[d].index(x["city"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"at": time.time(), "key": key, "data": out}))
    return out


# --- the phrasebook: phrases.json in the trip folder, with sound from pipeline/phrase_audio.py ----------------------

def phrasebook(src: Path, files: dict) -> dict | None:
    """phrases.json brought in (see HANDBOOK.md): each phrase per language as {text, roman, note?, audio?, learn?}
    (a ["text", "roman", "note"] list works too); its recordings copied into audio/."""
    path = src / "phrases.json"
    if not path.exists():
        return None
    book = json.loads(path.read_text(encoding="utf-8"))
    for sec in book.get("sections", []):
        for ph in sec.get("phrases", []):
            for lang in book.get("languages", {}):
                x = ph.get(lang)
                if isinstance(x, list):
                    x = ph[lang] = {"text": x[0], "roman": x[1] if len(x) > 1 else "", "note": x[2] if len(x) > 2 else None}
                if not x:
                    continue
                for k in ("audio", "learn"):
                    f = x.get(k)
                    if f and (src / f).exists():
                        b = (src / f).read_bytes(); name = f"audio/{hashlib.sha1(b).hexdigest()[:16]}.m4a"
                        files[name] = b; x[k] = name
                    else:
                        x[k] = None
    return book


DISPLAY = ("Instrument+Serif:ital@0;1", "instrument", None)      # the serif, whole (Latin)
# A face per script for the destination's own words (city names, the seal, the phrasebook, the send-off), cut down to
# the characters shown: (Google Fonts family query, file stem, CSS family, weight).
FACES = {
    "kana": ("Shippori+Mincho:wght@600", "mincho", "Shippori Mincho", 600),          # Japanese (and Han, unless the trip is Chinese)
    "hangul": ("Nanum+Myeongjo:wght@700", "myeongjo", "Nanum Myeongjo", 700),
    "han-sc": ("Noto+Serif+SC:wght@600", "notosc", "Noto Serif SC", 600),
    "han-tc": ("Noto+Serif+TC:wght@600", "notatc", "Noto Serif TC", 600),
    "thai": ("Noto+Serif+Thai:wght@500", "thai", "Noto Serif Thai", 500),
    "greek": ("Noto+Serif:wght@500", "notoserif", "Noto Serif", 500),                 # Greek, Cyrillic, Vietnamese
    "hebrew": ("Frank+Ruhl+Libre:wght@500", "frankruhl", "Frank Ruhl Libre", 500),
    "arabic": ("Amiri:wght@700", "amiri", "Amiri", 700),
    "devanagari": ("Noto+Serif+Devanagari:wght@600", "devanagari", "Noto Serif Devanagari", 600),
}
LATIN_LANGS = {"es", "fr", "it", "de", "pt", "nl", "sv", "da", "no", "nb", "fi", "is", "pl", "cs", "sk", "hu", "ro", "hr", "sl", "tr", "id", "ms",
               "tl", "sw", "ca", "eu", "gl", "et", "lv", "lt", "mt", "ga", "cy", "haw", "mi", "af"}


def script_of(ch: str, chinese: str | None = None) -> str | None:
    """The face a character is set in: None for Latin (the display serif)."""
    o = ord(ch)
    if 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F:
        return "hangul"
    if 0x3040 <= o <= 0x30FF:
        return "kana"
    if 0x3400 <= o <= 0x9FFF or 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF:
        return {"sc": "han-sc", "tc": "han-tc"}.get(chinese or "", "kana")
    if 0x0E00 <= o <= 0x0E7F:
        return "thai"
    if 0x0370 <= o <= 0x03FF or 0x1F00 <= o <= 0x1FFF or 0x0400 <= o <= 0x04FF or 0x1EA0 <= o <= 0x1EF9:
        return "greek"
    if 0x0590 <= o <= 0x05FF:
        return "hebrew"
    if 0x0600 <= o <= 0x06FF:
        return "arabic"
    if 0x0900 <= o <= 0x097F:
        return "devanagari"
    return None


def shown_chars(trip: dict, book: dict | None) -> tuple[dict, list, str | None]:
    """Every character the app shows in the destination's scripts, by face; the phrasebook's languages; and whether Han
    characters are Chinese (simplified "sc" / traditional "tc") rather than Japanese."""
    langs = list((book or {}).get("languages") or {})
    chinese = "tc" if any(l in ("zh-TW", "zh-HK") for l in langs) else "sc" if any(l.startswith("zh") for l in langs) and "ja" not in langs else None
    shown = trip.get("seal", "") + (trip.get("farewell") or {}).get("native", "") + "".join(c.get("native", "") for c in (trip.get("cities") or {}).values())
    for sec in (book or {}).get("sections", []):
        for ph in sec.get("phrases", []):
            shown += "".join((ph.get(l) or {}).get("text", "") for l in langs if isinstance(ph.get(l), dict))
    shown += "".join(v.get("native", "") for v in ((book or {}).get("languages") or {}).values())
    chars: dict[str, str] = {}
    for ch in shown:
        if (k := script_of(ch, chinese)):
            chars[k] = chars.get(k, "") + ch
    return chars, langs, chinese


def fonts(files: dict, chars: dict) -> str:
    """Google Fonts, brought in: the serif whole, each script's face cut down to the characters the app shows in it
    (a full CJK face is megabytes; the subset is kilobytes), so no word mixes two typefaces. Anything not in a subset
    falls back to the phone's own font."""
    import requests
    for k in [n for n in files if n.startswith("fonts/")]:
        del files[k]
    css_all = []
    for family, stem, text in [DISPLAY] + [(FACES[k][0], FACES[k][1], t) for k, t in chars.items() if t.strip()]:
        text = "".join(sorted(set(text))) if text is not None else None
        url = f"https://fonts.googleapis.com/css2?family={family}&display=swap" + (f"&text={quote(text)}" if text else "")
        css = requests.get(url, headers=UA, timeout=30).text
        def local(m):
            src = m.group(1); name = f"fonts/{stem}-{hashlib.sha1(src.encode()).hexdigest()[:10]}.woff2"
            files[name] = requests.get(src, timeout=30).content
            return f"url({name})"
        css_all.append(re.sub(r"url\((https://[^)]+)\)", local, css))
    return "\n".join(css_all)


def theme_css(trip: dict, faces: dict, langs: list[str], chinese: str | None) -> str:
    """The trip's accent (trip.json "accent", "accent_dark"), and each language's face where the app shows its words."""
    out = []
    if trip.get("accent"):
        out.append(f":root {{ --accent: {trip['accent']}; }}")
        out.append(f"@media (prefers-color-scheme: dark) {{ :root {{ --accent: {trip.get('accent_dark') or trip['accent']}; }} }}")
    stack = lambda k: f'"{FACES[k][2]}", var(--serif)'                          # noqa: E731
    natives = [k for k in faces if k not in ("kana", "hangul")]
    if natives:
        out.append(f":root {{ --native: {stack(natives[0])}; }}")
    if chinese:
        out.append(f':root {{ --mincho: "{FACES["han-" + chinese][2]}", "Shippori Mincho", serif; }}')
    for lang in langs:
        if lang in ("ja", "ko"):
            continue
        sel = ", ".join(x.format(l=lang) for x in (".phrases .native:lang({l})", "#say .native:lang({l})", ".ptabs button b:lang({l})", ".where .local b:lang({l})",
                                                    ".end h2:lang({l})"))
        if lang.split("-")[0] in LATIN_LANGS:
            out.append(f"{sel} {{ font-family: var(--serif); font-weight: 400; }}")
            out.append(f".phrases .native:lang({lang}) {{ font-size: 28px; line-height: 1.2; }} .phrases .native.long:lang({lang}) {{ font-size: 24px; }}")
        elif natives:
            out.append(f"{sel} {{ font-family: {stack(natives[0])}; font-weight: {FACES[natives[0]][3]}; }}")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("trip", help="the trip folder (holds trip.json)")
    ap.add_argument("--out", help="where to write the app (default: <trip>/dist)")
    ap.add_argument("--fonts", action="store_true", help="re-fetch the fonts from Google Fonts, subset for this trip")
    ap.add_argument("--no-remote", action="store_true", help="do not fetch an email's remote pictures")
    ap.add_argument("--weather", action="store_true", help="fetch a fresh forecast even if the cached one is recent (for a nightly run)")
    ap.add_argument("--no-weather", action="store_true", help="leave the forecast out")
    a = ap.parse_args()
    src = Path(a.trip).resolve()
    build(src, Path(a.out).resolve() if a.out else src / "dist", a.fonts, not a.no_remote, a.weather, not a.no_weather)
