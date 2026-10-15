/* The trip, rendered from data.js (window.TRIP) — everything is local; nothing here needs the network. */
(() => {
  const T = window.TRIP;
  const $ = (s, el = document) => el.querySelector(s);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  // Each city's colour comes from the trip's data (cities[name].color); an unlisted city gets one from a small palette.
  const PALETTE = ["#34557a", "#4f7a5a", "#b0662a", "#b8432c", "#6b4f8a", "#5d6b7a", "#8a6d3b"];
  const color = city => { const name = String(city || "").split(/\s*(?:->|→)\s*/).pop().trim();
    const c = Object.entries(T.cities || {}).find(([k]) => k.toLowerCase() === name.toLowerCase())?.[1]?.color; if (c) return c;
    let h = 0; for (const ch of name.toLowerCase()) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return name ? PALETTE[h % PALETTE.length] : "#5d6b7a"; };
  const ev = Object.fromEntries(T.events.map(e => [e.id, e]));
  const hotels = Object.fromEntries(T.hotels.map(h => [h.id, h]));
  const CJK = /[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]/;                 // set vertically, like a seal; anything else across
  const ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII"];

  // --- dates and the clock. Every event is placed in absolute time: its start in the zone of the city it starts in
  //     (Seattle, or Japan/Korea, both UTC+9), its end in the zone of the city it ends in (a flight lands a day later).
  //     The phone's own time zone never matters.
  const D = iso => new Date(iso + "T12:00:00");
  const fmt = (iso, o) => D(iso).toLocaleDateString("en-US", o);
  const dayNo = iso => Math.round((D(iso) - D(T.start)) / 864e5) + 1;
  // UTC offsets by city, from the trip's data: {"default": "+09:00", "Seattle": "-07:00"} (a city not listed = default)
  const ZONE = c => { const z = T.zones || {}; const name = String(c || "").trim().toLowerCase();
    const hit = Object.keys(z).find(k => k !== "default" && name.startsWith(k.toLowerCase())); return (hit && z[hit]) || z.default || "+09:00"; };
  const cities = e => String(e.city || "").split(/\s*(?:->|→)\s*/);
  const pad = t => t.length === 4 ? "0" + t : t;
  function span(e) {                                         // [start, end] in ms, or null for an untimed event
    if (mins(e.start) == null) return null;
    const s = Date.parse(`${e.date}T${pad(e.start.slice(0, 5))}:00${ZONE(cities(e)[0])}`);
    // a flight between zones lands in the other zone's time (maybe the next day); everything else ends where it starts
    // (a day's "Seoul -> Seattle" also covers that afternoon's checkout)
    const flies = kind(e) === "plane" && ZONE(cities(e)[0]) !== ZONE(cities(e).at(-1));
    let f = mins(e.end) != null ? Date.parse(`${e.date}T${pad(e.end.slice(0, 5))}:00${ZONE(cities(e)[flies ? cities(e).length - 1 : 0])}`) : NaN;
    if (flies && f <= s) f += 864e5;
    if (!(f > s)) f = s + 3600e3;                                                // no end, or one before the start: an hour
    if (e.type === "Lodging" && f - s > 6 * 3600e3) f = s + 3600e3;          // a check-in is a moment, not the stay
    return [s, f];
  }
  const FAKE = new URLSearchParams(location.search).get("now");                // ?now=2027-04-17T10:30 (Japan time) to see a day on the road
  const nowMs = () => FAKE ? Date.parse(/[+-]\d\d:\d\d$|Z$/.test(FAKE) ? FAKE : FAKE + ":00+09:00") : Date.now();
  let DEPART = Infinity;                                       // the first event: before it, the day is Seattle's
  function now() {
    const tz = nowMs() < DEPART ? (T.timezone?.home || "UTC") : (T.timezone?.default || "UTC");
    const p = Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
      .formatToParts(new Date(nowMs())).map(x => [x.type, x.value]));
    return { date: `${p.year}-${p.month}-${p.day}`, mins: +p.hour * 60 + +p.minute };
  }
  const mins = t => t && /^\d{1,2}:\d{2}/.test(t) ? +t.split(":")[0] * 60 + +t.split(":")[1].slice(0, 2) : null;
  function clock(t) {
    const m = mins(t); if (m == null) return "";
    const h = Math.floor(m / 60), mm = String(m % 60).padStart(2, "0");
    return `${(h + 11) % 12 + 1}:${mm}<small>${h < 12 ? "AM" : "PM"}</small>`;
  }
  const plainClock = t => clock(t).replace(/<small>(\w+)<\/small>/, " $1");

  // --- icons -----------------------------------------------------------------------------------------------------
  const P = {
    plane: '<path d="M21 15.5v-1.8l-8-5V3.6a1.6 1.6 0 0 0-3.2 0v5.1l-8 5v1.8l8-2.5v4.8l-2.2 1.7V21l3.8-1.1L15.2 21v-1.5L13 17.8V13z" fill="currentColor"/>',
    train: '<rect x="5" y="3" width="14" height="14" rx="4" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M5 10h14M9 14h.01M15 14h.01M8 21l2-4M16 21l-2-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
    bus: '<rect x="4" y="3" width="16" height="15" rx="3" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M4 11h16M8 15h.01M16 15h.01M7 18v2.5M17 18v2.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
    car: '<path d="M5 16V12l2-5h10l2 5v4M5 16h14M5 16v2.5M19 16v2.5M4 12h16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/><circle cx="8" cy="14" r=".9" fill="currentColor"/><circle cx="16" cy="14" r=".9" fill="currentColor"/>',
    bed: '<path d="M3 18V6M3 14h18v4M21 14v-2a3 3 0 0 0-3-3h-7v5M7 11.5h.01" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><circle cx="7" cy="11" r="1.8" fill="currentColor"/>',
    bowl: '<path d="M3 11h18a9 9 0 0 1-18 0zM8 7l1-3M12 7V3M16 7l-1-3" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
    bag: '<rect x="4" y="7" width="16" height="13" rx="2.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M4 12h16" stroke="currentColor" stroke-width="1.8" fill="none"/>',
    star: '<path d="M12 3l2.6 5.6 6.1.7-4.5 4.2 1.2 6L12 16.6 6.6 19.5l1.2-6L3.3 9.3l6.1-.7z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>',
    mail: '<rect x="3" y="5" width="18" height="14" rx="2.5" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M4 7l8 6 8-6" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>',
  };
  const svg = k => `<svg viewBox="0 0 24 24" aria-hidden="true">${P[k]}</svg>`;
  function kind(e) {
    const t = `${e.title} ${e.place || ""}`.toLowerCase();
    if (e.type === "Transit" || (!e.type && e.travel)) {                     // an outing on a travel day keeps its own icon
      if (/\bbus\b|limousine/.test(t)) return "bus";                            // before the airports: the KIX bus
      if (/rental|rent a car|\bsuv\b|hertz|avis|budget|enterprise|alamo|sixt|\bdrive\b/.test(t)) return "car";   // a car picked up at an airport
      if (/flight|\bair\b|delta|korean air|airport|haneda|kix|icn|sea\b/.test(t)) return "plane";
      if (/train|rail|shinkansen|romancecar|\bline\b|tozan|\bjr\b/.test(t)) return "train";    // before "car": Romancecar
      if (/taxi|\bcab\b|\bcar\b/.test(t)) return "car";
      return /checkout|departure/.test(t) ? "bag" : "train";
    }
    return { Lodging: "bed", Food: "bowl", Logistics: "bag" }[e.type] || "star";
  }

  // --- pieces ----------------------------------------------------------------------------------------------------
  const maps = q => `maps://?q=${encodeURIComponent(q)}`;
  // Google Maps directions from wherever the phone is (it opens the Maps app; the network is its business)
  const directions = q => /^https?:/.test(q) ? q                                // an operator's own map pin, as it is
    : `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(q)}`;
  const first = s => String(s || "").split(/\s*(?:->|→)\s*/)[0].trim();          // "Shibuya Pickup -> Daikoku PA": go to the pickup
  function destination(e) {
    if (e.dest) return e.dest;                                                 // Claude's pick: the right station, city and country
    const addr = e.address || (e.copy?.facts || []).find(f => /^address$/i.test(f.label))?.value;
    if (addr) return addr;
    if (!e.place) return null;
    const place = first(e.place), city = first(e.city);
    return city && !place.toLowerCase().includes(city.toLowerCase()) ? `${place}, ${city}` : place;
  }
  // The ways to get there. With an exact place (looked up once on Google Maps): Google by its place id, Naver and
  // Apple Maps by its coordinates (Apple Maps works offline in a downloaded area), and a ride there in the Uber app
  // (its universal link: the app opens with the destination set, or the web page without it). In Korea, Naver Map
  // comes first: Google cannot give walking directions there.
  const uber = (q, place) => `https://m.uber.com/ul/?action=setPickup&pickup=my_location` +
    (place ? `&dropoff[latitude]=${place.lat}&dropoff[longitude]=${place.lng}&dropoff[nickname]=${encodeURIComponent(place.name || q || "")}` : "") +
    (place?.address || q ? `&dropoff[formatted_address]=${encodeURIComponent(place?.address || q)}` : "");
  const DIR_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.5l9.5 9.5-9.5 9.5L2.5 12z" fill="currentColor"/><path d="M9 14.5v-2.5a1.5 1.5 0 0 1 1.5-1.5H15m-2-2l2 2-2 2" fill="none" stroke="var(--card)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const UBER_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 11l1.6-4.2A2 2 0 0 1 8.5 5.5h7a2 2 0 0 1 1.9 1.3L19 11m-14 0h14a1.5 1.5 0 0 1 1.5 1.5V17H3.5v-4.5A1.5 1.5 0 0 1 5 11zm.5 6v1.5m13-1.5v1.5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/><circle cx="7.5" cy="14" r="1" fill="currentColor"/><circle cx="16.5" cy="14" r="1" fill="currentColor"/></svg>';
  function ways(place, q) {
    if (place?.lat != null) {
      const ll = `${place.lat},${place.lng}`;
      return { korea: place.language === "ko",
               google: `https://www.google.com/maps/dir/?api=1&destination=${ll}&destination_place_id=${encodeURIComponent(place.id)}`,
               naver: `nmap://route/public?dlat=${place.lat}&dlng=${place.lng}&dname=${encodeURIComponent(place.local_name || place.name)}&appname=${encodeURIComponent(T.bundle_id || "trip.brochure")}`,
               apple: `maps://?daddr=${ll}`, uber: uber(q, place) };
    }
    if (!q) return null;
    const pin = /^https?:/.test(q);                                            // an operator's map link: nothing to hand a ride app
    return { korea: /korea/i.test(q), google: directions(q), apple: pin ? null : `maps://?daddr=${encodeURIComponent(q)}`,
             naver: /korea/i.test(q) ? `nmap://search?query=${encodeURIComponent(q)}&appname=${encodeURIComponent(T.bundle_id || "trip.brochure")}` : null,
             uber: pin ? null : uber(q) };
  }
  function goButtons(w) {
    if (!w) return "";
    const main = w.korea && w.naver ? `<a class="dir" href="${esc(w.naver)}">${DIR_ICON}Naver Map</a>` : `<a class="dir" href="${esc(w.google)}">${DIR_ICON}Directions</a>`;
    const ride = w.uber ? `<a class="dir alt" href="${esc(w.uber)}">${UBER_ICON}Uber</a>` : "";
    const alt = w.apple ? `<a class="dir alt" href="${esc(w.apple)}">Apple Maps</a>` : "";
    return `<span class="go-ways">${main}${ride}${alt}</span>`;
  }
  // Offline: the little map (tap: Apple Maps), and the name and address in Japanese or Korean, to show a driver.
  function whereHTML(place, w) {
    if (!place || (!place.map && !place.local_name)) return "";
    const lang = ({ ja: "Japanese", ko: "Korean", zh: "Chinese", th: "Thai", vi: "Vietnamese", el: "Greek", he: "Hebrew", ar: "Arabic", ru: "Russian", hi: "Hindi",
                    fr: "French", it: "Italian", es: "Spanish", de: "German", pt: "Portuguese", ...(T.languages || {}) })[String(place.language || "").split("-")[0]] || "";
    const local = place.local_name && lang ? `<div class="local"><div><span>In ${lang}</span><b lang="${place.language}">${esc(place.local_name)}</b>${place.local_address ? `<small lang="${place.language}">${esc(place.local_address)}</small>` : ""}</div>
        <button class="show" data-driver="${esc(JSON.stringify({ name: place.local_name, address: place.local_address, en: place.name, lang: place.language, map: place.map || null }))}">Show driver</button></div>` : "";
    const map = place.map ? `<a class="map" href="${esc(w?.apple || w?.google || "#")}"><img loading="lazy" src="${place.map}" alt="Map of ${esc(place.name)}"></a>` : "";
    return `<div class="where">${map}${local}</div>`;
  }
  const isCode = l => /confirm|reservation|e-?ticket|code|pnr|record|order|booking (no|number|ref)/i.test(l);
  const codeLike = v => /\d/.test(v) && v.length < 70 && v.split(/\s+/).length <= 6;
  const isPlace = l => /address|meeting point/i.test(l);

  function facts(list, extra = []) {
    const all = [...(list || []), ...extra];
    if (!all.length) return "";
    return `<dl class="facts">${all.map(f => {
      const v = esc(f.value), wide = f.value.length > 34 ? " wide" : "";
      const dd = isCode(f.label) && codeLike(f.value)
        ? `<button class="code" data-copy="${v}">${v}</button>`
        : isPlace(f.label) ? `<a href="${maps(f.value)}">${v}</a>` : v;
      return `<div class="${wide}"><dt>${esc(f.label)}</dt><dd>${dd}</dd></div>`;
    }).join("")}</dl>`;
  }

  function docCards(ids, title) {
    if (!ids.length) return "";
    return `<div class="docs">${ids.map(id => {
      const d = T.docs[id]; if (!d) return "";
      const face = d.email && !d.thumb
        ? `<div class="mail">${svg("mail")}<b>${esc((d.subject || "Email").replace(/^(fwd?|re):\s*/i, ""))}</b></div>`
        : `<div class="t" style="background-image:url('${d.thumb}')"></div>`;
      const cap = d.email ? (d.translation ? `${esc(d.language)} · English` : d.sender ? `From ${esc(d.sender.split(" ")[0])}` : "Email") : d.pages.length > 1 ? `${d.pages.length} pages` : "Screenshot";
      return `<button class="doc" data-doc="${id}" data-for="${esc(title)}">${face}<div class="cap">${cap}</div></button>`;
    }).join("")}</div>`;
  }

  function timeCol(e) {
    const s = mins(e.start), f = mins(e.end);
    let html = e.start ? `<b>${clock(e.start)}</b>` : `<b>—</b>`;
    if (f != null && s != null && f > s) html += `<span>to ${plainClock(e.end)}</span>`;
    else if (f != null && s != null && e.type === "Transit") html += `<span>arr. ${plainClock(e.end)}</span>`;
    return html + `<div class="ico">${svg(kind(e))}</div>`;
  }

  function eventHTML(e, c) {
    const cp = e.copy || {};
    const extra = [];
    const have = (cp.facts || []).map(f => f.label.toLowerCase());
    if (e.confirmation && !have.some(l => isCode(l))) extra.push({ label: "Confirmation", value: e.confirmation });
    const tags = [];
    if (e.status === "booked") tags.push('<span class="tag booked">Booked</span>');
    else if (e.status === "critical") tags.push('<span class="tag critical">Don’t miss</span>');
    const place = e.place ? `<div class="place"><a href="${maps(e.place + (e.city && !e.travel ? ", " + e.city : ""))}">${esc(e.place)}</a></div>` : "";
    const w = ways(e.gplace, destination(e));
    const pic = e.photo ? `<figure class="pic"><img loading="lazy" src="${e.photo.sm.replace("-sm", "")}" style="object-position:${e.photo.focus}" alt=""></figure>` : "";
    const notes = e.notes && cp.blurb ? `<details class="notes"><summary>Itinerary notes</summary><p>${esc(e.notes)}</p></details>` : "";
    const body = cp.blurb ? `<p class="blurb">${esc(cp.blurb)}</p>` : e.notes ? `<p class="blurb">${esc(e.notes)}</p>` : "";
    return `<article class="ev${e.photo ? " has-pic" : ""}" id="ev-${e.id}" data-id="${e.id}" data-mode="${kind(e)}" style="--c:${c}">
      <div class="time">${timeCol(e)}</div>
      <div class="main">${pic}<h4>${esc(e.title)}</h4>${place}${body}
        ${tags.length || w ? `<div class="tags">${tags.join("")}${goButtons(w)}</div>` : ""}
        ${facts(cp.facts, extra)}${whereHTML(e.gplace, w)}${docCards(e.docs, e.title)}${notes}</div>
    </article>`;
  }

  // --- weather: the day's forecast where you are (data.js "weather", from Open-Meteo at build time) ---------------
  const WX = {                                   // WMO weather codes → an icon and a word
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
    part: '<path d="M8.5 4.5v1.5M3.6 9H5M5 5.5l1 1M12 6.5l1-1"/><path d="M5.6 12.4a3.5 3.5 0 1 1 6.3-2.9"/><path d="M8 19.5h9.5a3.5 3.5 0 0 0 0-7 5 5 0 0 0-9.6 1.3A2.9 2.9 0 0 0 8 19.5z"/>',
    cloud: '<path d="M7 19h10.5a4 4 0 0 0 .4-8 6 6 0 0 0-11.6 1.6A3.2 3.2 0 0 0 7 19z"/>',
    fog: '<path d="M4 10h16M6 14h12M4 18h16M7 6h10"/>',
    rain: '<path d="M7 15h10.5a4 4 0 0 0 .4-8 6 6 0 0 0-11.6 1.6A3.2 3.2 0 0 0 7 15z"/><path d="M9 18l-1 2.5M13 18l-1 2.5M17 18l-1 2.5"/>',
    snow: '<path d="M7 14h10.5a4 4 0 0 0 .4-8 6 6 0 0 0-11.6 1.6A3.2 3.2 0 0 0 7 14z"/><path d="M8.5 18h.01M12 20h.01M15.5 18h.01M12 17h.01"/>',
    storm: '<path d="M7 14h10.5a4 4 0 0 0 .4-8 6 6 0 0 0-11.6 1.6A3.2 3.2 0 0 0 7 14z"/><path d="M12.5 15.5l-2 3.5h3l-2 3.5"/>',
  };
  function wxKind(code) {
    if (code === 0) return ["sun", "Clear"];
    if (code <= 2) return ["part", "Partly cloudy"];
    if (code === 3) return ["cloud", "Cloudy"];
    if (code === 45 || code === 48) return ["fog", "Fog"];
    if (code >= 51 && code <= 57) return ["rain", "Drizzle"];
    if ((code >= 61 && code <= 67) || (code >= 80 && code <= 82)) return ["rain", code >= 80 ? "Showers" : "Rain"];
    if ((code >= 71 && code <= 77) || code === 85 || code === 86) return ["snow", "Snow"];
    if (code >= 95) return ["storm", "Thunderstorms"];
    return ["cloud", ""];
  }
  function wxHTML(iso) {
    const items = T.weather?.days?.[iso];
    if (!items?.length) return "";
    return `<div class="wx">${items.map(w => { const [k, word] = wxKind(w.code);
      return `<span class="w" title="${esc(word)}"><svg viewBox="0 0 24 24" aria-hidden="true">${WX[k]}</svg>${items.length > 1 ? `<i>${esc(w.city)}</i>` : ""}<b>${w.hi}°</b><small>${w.lo}°</small>${w.rain >= 30 ? `<em>${w.rain}% rain</em>` : ""}<span class="word">${esc(word)}</span></span>`; }).join("")}</div>`;
  }

  function dayHTML(iso, ids, c) {
    const list = ids.map(i => ev[i]).filter(Boolean).filter(e => e.date === iso)
      .sort((a, b) => (mins(a.start) ?? 9999) - (mins(b.start) ?? 9999));
    if (!list.length) return "";
    return `<section class="day" id="day-${iso}" data-date="${iso}">
      <div class="dayhead"><span class="num">Day ${dayNo(iso)}</span><h3>${fmt(iso, { weekday: "long", month: "long", day: "numeric" })}</h3>${wxHTML(iso)}</div>
      ${list.map(e => eventHTML(e, c)).join("")}
    </section>`;
  }

  function stayHTML(leg, n) {
    const c = color(leg.title), h = hotels[leg.hotel_id] || {}, cp = leg.copy || {}, hc = h.copy || {};
    const native = cp.native ? `<div class="native${/[가-힯]/.test(cp.native) ? " ko" : /[\u3040-\u30ff\u3400-\u9fff]/.test(cp.native) ? "" : " h"}">${esc(cp.native)}</div>` : "";
    const range = `${fmt(leg.start, { month: "short", day: "numeric" })} – ${fmt(leg.end, { month: "short", day: "numeric" })}`;
    const dates = [...new Set([...(leg.days || []), ...leg.events.map(i => ev[i]?.date)].filter(Boolean))].sort();
    const hotelFacts = (hc.facts || []).filter(f => !/^(nights|hotel)$/i.test(f.label));
    return `<section class="chapter" id="leg-${n}" data-title="${esc(leg.title)}" style="--c:${c}">
      <figure class="hero">${leg.photo ? `<img src="${leg.photo.lg}" style="object-position:${leg.photo.focus}" alt="">` : ""}
        <div class="nights">${leg.nights} night${leg.nights === 1 ? "" : "s"}</div>${native}
        <div class="in"><div class="kicker">Chapter ${ROMAN[n] || n} · ${range}</div><h2>${esc(leg.title)}</h2><div class="sub">${esc(leg.sub || "")}</div></div>
      </figure>
      <div class="wrap">
        ${cp.blurb ? `<p class="lede">${esc(cp.blurb)}</p>` : ""}
        ${h.name ? `<div class="stay"><div class="kicker">Where we sleep</div><h3>${esc(h.name)}</h3>${h.room ? `<div class="room">${esc(h.room)}</div>` : ""}
          ${hc.blurb ? `<p class="blurb">${esc(hc.blurb)}</p>` : ""}
          <div class="dates"><div><span>Check in</span><b>${fmt(h.start, { weekday: "short", month: "short", day: "numeric" })}</b></div>
          <div><span>Check out</span><b>${fmt(h.end, { weekday: "short", month: "short", day: "numeric" })}</b></div>
          </div><div class="go">${goButtons(ways(h.gplace, h.address || `${h.name}, ${h.city}`))}</div>
          ${whereHTML(h.gplace, ways(h.gplace, h.address || `${h.name}, ${h.city}`))}
          ${facts(hotelFacts.filter(f => !/^room$/i.test(f.label)))}</div>` : ""}
        ${dates.map(d => dayHTML(d, leg.events, c)).join("")}
      </div>
    </section>`;
  }

  function travelHTML(leg, n) {
    const first = leg.events.map(i => ev[i]).filter(Boolean)[0];
    const c = color(first?.city);
    const dates = [...new Set(leg.events.map(i => ev[i]?.date).filter(Boolean))].sort();
    const range = leg.end_date && leg.end_date !== leg.date ? `${fmt(leg.date, { month: "short", day: "numeric" })} – ${fmt(leg.end_date, { month: "short", day: "numeric" })}` : fmt(leg.date, { weekday: "short", month: "short", day: "numeric" });
    return `<section class="journey" id="leg-${n}" data-title="${esc(leg.title)}" data-mode="${first ? kind(first) : "train"}" style="--c:${c}">
      <div class="wrap">
        <div class="band"><div class="ico">${svg(first ? kind(first) : "train")}</div><div><div class="kicker">On the move · ${range}</div><h2>${esc(leg.title)}</h2></div></div>
        ${dates.map(d => dayHTML(d, leg.events, c)).join("")}
      </div>
    </section>`;
  }

  // --- the whole brochure --------------------------------------------------------------------------------------------
  function render() {
    const stays = T.legs.filter(l => l.kind === "stay");
    const cover = T.cover || stays[0]?.photo;
    const nights = Math.round((D(T.end) - D(T.start)) / 864e5);
    const people = T.people.length > 1 ? `${T.people.slice(0, -1).join(", ")} & ${T.people.at(-1)}` : T.people[0] || "";
    const booked = T.events.filter(e => e.status === "booked").length;
    let chapter = 0;
    const legs = T.legs.map((l, i) => l.kind === "stay" ? stayHTML(l, ++chapter) : travelHTML(l, i)).join("");
    const ids = T.legs.map((l, i) => [l, i]);
    $("#app").innerHTML = `
      <section class="cover"${cover?.fit === "wide" ? ` style="background:${cover.tone}"` : ""}>
        ${!cover ? "" : cover.fit === "wide" ? `<img class="backdrop" src="${cover.sm || cover.lg}" alt="" aria-hidden="true"><img class="wide" src="${cover.cover || cover.lg}" style="--r:${cover.ratio};--fill:${cover.fill};--fx:${parseFloat(cover.focus) || 50}" alt="">`
          : `<img src="${cover.cover || cover.lg}" style="object-position:${cover.focus}" alt="">`}
        <div class="top"><div class="kicker">${esc(T.family || "")}<span class="k2">${fmt(T.start, { month: "long", year: "numeric" })}</span></div>${T.seal ? `<div class="seal${CJK.test(T.seal) ? "" : " h"}">${esc(T.seal)}</div>` : ""}</div>
        <div class="in">
          <h1>${T.title_html || esc(T.name)}</h1>
          <div class="dates">${fmt(T.start, { month: "long", day: "numeric" })} – ${fmt(T.end, { month: "long", day: "numeric", year: "numeric" })}</div>
          <div class="who">${esc(people)}</div>
          <div class="status" id="status"></div>
          <ol class="route">${ids.filter(([l]) => l.kind === "stay").map(([l, i]) => `<li style="--c:${color(l.title)}"><button data-jump="leg-${i}"><span class="n">${esc(l.title)}</span><span class="d">${l.nights} night${l.nights === 1 ? "" : "s"}</span></button></li>`).join("")}</ol>
        </div>
      </section>
      <div class="wrap intro">
        <p>${T.intro ? T.intro.replace(/\{nights\}/g, nights).replace(/\{cities\}/g, stays.length) : `${nights} nights, ${stays.length} ${stays.length === 1 ? "city" : "cities"}: ${stays.map(s => esc(s.title)).join(", ")}.`}</p>
        <div class="glance"><div><b>${dayNo(T.end)}</b><span>days</span></div><div><b>${stays.length}</b><span>cities</span></div><div><b>${booked}</b><span>bookings</span></div></div>
      </div>
      ${legs.replace(/id="leg-(\d+)"/g, (m, k) => m)}
      <footer class="end">
        <div class="wrap">
          ${T.seal ? `<div class="mark${CJK.test(T.seal) ? "" : " h"}">${esc(T.seal)}</div>` : ""}
          <h2${T.farewell?.native && T.farewell?.lang ? ` lang="${esc(T.farewell.lang)}"` : ""}>${esc(T.farewell?.native || T.farewell?.english || "Have a wonderful trip.")}</h2>
          ${T.farewell?.native && T.farewell?.english ? `<p>${esc(T.farewell.english)}</p>` : ""}
          <div class="credits">${T.credits.map(c => `<div>Photo: ${esc(c.credit)}, ${esc(c.license || "")}</div>`).join("")}</div>
          <div class="build">Itinerary as of ${new Date(T.built).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}${T.weather?.updated && Object.keys(T.weather.days || {}).length ? ` · forecast ${T.weather.sample ? "(sample)" : `by <a href="https://open-meteo.com/">Open-Meteo</a>, ${new Date(T.weather.updated).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}`}` : ""}<span id="shellv"></span></div>
        </div>
      </footer>
      <nav id="dock" aria-label="Cities">
        <div class="track"><div class="fill"></div></div>
        <div class="rider"><span class="ico"></span></div>
        <ol>${ids.filter(([l]) => l.kind === "stay").map(([l, i]) => `<li style="--c:${color(l.title)}"><button data-jump="leg-${i}"><i></i><span>${esc(l.title)}</span></button></li>`).join("")}</ol>
      </nav>`;
    // the stays' ids follow T.legs' index so the route links land on them
    let k = 0;
    document.querySelectorAll(".chapter, .journey").forEach(s => s.id = `leg-${k++}`);
  }

  // --- where we are in the trip ------------------------------------------------------------------------------------
  function mark() {
    const n = now();
    const s = $("#status");
    const until = Math.round((D(T.start) - D(n.date)) / 864e5);
    if (until > 1) s.textContent = `Leaving in ${until} days`;
    else if (until === 1) s.textContent = "Leaving tomorrow";
    else if (n.date <= T.end) {
      const day = T.days.find(d => d.date === n.date);
      s.textContent = `Day ${dayNo(n.date)} of ${dayNo(T.end)}${day?.city ? " · " + day.city : ""}`;
    } else s.textContent = "Welcome home";
    document.querySelectorAll(".day").forEach(d => {
      const iso = d.dataset.date;
      d.classList.toggle("past", iso < n.date && n.date <= T.end);
      const head = $(".dayhead", d), badge = $(".today", head);
      if (iso === n.date && !badge) head.insertAdjacentHTML("beforeend", '<span class="today">Today</span>');
      if (iso !== n.date && badge) badge.remove();
    });
    const t = nowMs();
    let nextSet = false;
    [...document.querySelectorAll(".ev")].map(a => [a, span(ev[a.dataset.id])]).filter(([, sp]) => sp).sort((x, y) => x[1][0] - y[1][0]).forEach(([a, [s0, s1]]) => {
      a.classList.remove("now", "next", "done");
      $(".tag.now", a)?.remove();
      if (t >= s0 && t < s1) { a.classList.add("now"); $(".main h4", a).insertAdjacentHTML("beforebegin", '<div class="tags" style="margin:0 0 6px"><span class="tag now">Now</span></div>'); }
      else if (t >= s1) { if (ev[a.dataset.id].date === n.date) a.classList.add("done"); }
      else if (!nextSet) { a.classList.add("next"); nextSet = true; }
    });
    $("#bar-today").hidden = !onTrip();
  }

  // On the road, the app opens on what is happening now, or what is next (its day's heading, when it is the day's
  // first). Only on opening and on coming back after a while: scrolling back to look at anything else is yours.
  function onTrip() {
    const all = T.events.map(span).filter(Boolean);
    return all.length && nowMs() > Math.min(...all.map(x => x[0])) - 12 * 3600e3 && nowMs() < Math.max(...all.map(x => x[1]));
  }
  function goNow(smooth) {
    if (VIEW !== "itinerary") showView("itinerary");
    mark();
    const el = $(".ev.now") ? [...document.querySelectorAll(".ev.now")].at(-1) : $(".ev.next");
    if (!el) return false;
    const day = el.closest(".day");
    const target = day && $(".ev", day) === el ? day : el;
    target.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
    return true;
  }
  const goToday = smooth => goNow(smooth);

  // --- the bar: which chapter you are in ---------------------------------------------------------------------------
  function bar() {
    if (VIEW !== "itinerary") {
      $("#bar").classList.add("on");
      const html = esc(VIEWS[VIEW]?.title || "");
      if ($("#bar-title").innerHTML !== html) $("#bar-title").innerHTML = html;
      return;
    }
    const cover = $(".cover").getBoundingClientRect().bottom;
    $("#bar").classList.toggle("on", cover < 60);
    let cur = null;
    document.querySelectorAll(".chapter, .journey").forEach(s => { if (s.getBoundingClientRect().top < 90) cur = s; });
    let day = null;
    document.querySelectorAll(".day").forEach(d => { if (d.getBoundingClientRect().top < 110) day = d; });
    const t = cur ? esc(cur.dataset.title) : esc(T.name);
    const sub = day ? fmt(day.dataset.date, { weekday: "short", month: "short", day: "numeric" }) : "";
    const html = `${t}${sub ? `<small>${sub}</small>` : ""}`;
    if ($("#bar-title").innerHTML !== html) $("#bar-title").innerHTML = html;
  }

  // --- the dock: the route, kept at hand at the bottom once the cover's copy scrolls away ----------------------------
  // A rider travels the line as you read: a plane or a train between cities (the journeys), resting on a city's dot
  // while you are in its chapter. The line fills in each city's colour up to where you are.
  const TRAVEL = new Set(["plane", "train", "bus", "car"]);
  const dock = { el: null, xs: [], cols: [], left: 0, right: 0, mode: "", at: -1 };
  function dockLayout() {
    const el = dock.el = $("#dock"); if (!el) return;
    // layout positions, not on-screen ones: while hidden (or arriving) the dock is drawn scaled, which would shrink them
    const box = { width: el.offsetWidth };
    dock.xs = [...el.querySelectorAll("li")].map(li => li.offsetLeft + li.offsetWidth / 2);
    dock.cols = [...el.querySelectorAll("li")].map(li => li.style.getPropertyValue("--c"));
    dock.left = 14; dock.right = box.width - 14;
    const stops = dock.xs.map((x, i) => `${dock.cols[i]} ${x}px`).join(", ");
    $(".track", el).style.cssText = `left:${dock.left}px; right:${box.width - dock.right}px`;
    $(".fill", el).style.background = `linear-gradient(90deg, ${dock.cols[0]} 0px, ${stops}, ${dock.cols.at(-1)} ${box.width}px)`;
    $(".fill", el).style.backgroundPosition = `-${dock.left}px 0`;
    $(".fill", el).style.backgroundSize = `${box.width}px 100%`;
    dockMove();
  }
  function dockMove() {
    const el = dock.el; if (!el || !dock.xs.length) return;
    const route = $(".cover .route").getBoundingClientRect();
    const end = $(".end").getBoundingClientRect();
    el.classList.toggle("on", VIEW === "itinerary" && route.bottom < 0 && end.top > innerHeight - 90 && viewer.hidden);
    // where the reader is: the section under a line a third of the way down the screen
    const y = innerHeight * .34;
    const secs = [...document.querySelectorAll(".chapter, .journey")];
    let stay = -1, x = dock.left, mode = "", at = 0;
    for (const sec of secs) {
      const r = sec.getBoundingClientRect();
      const isStay = sec.classList.contains("chapter");
      if (isStay) stay++;
      if (r.top > y) break;
      const f = Math.min(1, Math.max(0, (y - r.top) / Math.max(1, r.height)));
      if (isStay) { x = dock.xs[stay]; mode = ""; at = stay; }
      else {
        const from = stay < 0 ? dock.left : dock.xs[stay], to = stay + 1 < dock.xs.length ? dock.xs[stay + 1] : dock.right;
        x = from + (to - from) * (r.bottom <= y ? 1 : f); at = Math.max(0, stay);
        // the way of travel of the leg being read: a taxi, then a train, then a plane (a stop between keeps the last one)
        const legs = [...sec.querySelectorAll(".ev")].filter(a => TRAVEL.has(a.dataset.mode));
        const now = legs.filter(a => a.getBoundingClientRect().top <= y).at(-1) || legs[0];
        mode = now?.dataset.mode || sec.dataset.mode;
      }
    }
    $(".fill", el).style.width = Math.max(0, x - dock.left) + "px";
    const rider = $(".rider", el);
    rider.style.transform = `translateX(${x}px)`;
    rider.style.setProperty("--c", dock.cols[mode ? Math.min(at + (stay < 0 ? 0 : 1), dock.cols.length - 1) : at] || dock.cols[0]);
    if (mode !== dock.mode) { dock.mode = mode; rider.classList.toggle("moving", !!mode); if (mode) $(".ico", rider).innerHTML = svg(mode); }
    if (at !== dock.at) { dock.at = at; el.querySelectorAll("li").forEach((li, i) => li.classList.toggle("here", i === at && !mode)); }
    else el.querySelectorAll("li").forEach((li, i) => li.classList.toggle("here", i === at && !mode));
  }

  // --- show the driver: the destination in its own script, as large as the screen allows -------------------------------
  const PLEASE = { ja: "ここまでお願いします。", ko: "여기로 가 주세요.", zh: "请带我去这里。", th: "ช่วยพาไปที่นี่ค่ะ/ครับ", el: "Εδώ, παρακαλώ.", ...(T.please || {}) };
  function showDriver(d) {
    const el = document.getElementById("driver");
    el.innerHTML = `<button class="x" aria-label="Close">×</button><div class="card">${d.kicker ? `<span class="kicker">${esc(d.kicker)}</span>` : ""}
      ${d.map ? `<img class="map" src="${esc(d.map)}" alt="Map of ${esc(d.en || d.name)}">` : ""}<b lang="${esc(d.lang)}">${esc(d.name)}</b>
      ${d.address ? `<p lang="${esc(d.lang)}">${esc(d.address)}</p>` : ""}${d.en && d.en !== d.name ? `<small>${esc(d.en)}</small>` : ""}
      ${PLEASE[d.lang] ? `<div class="please" lang="${esc(d.lang)}">${esc(PLEASE[d.lang])}</div>` : ""}</div>`;
    el.hidden = false;
    $(".x", el).onclick = () => { el.hidden = true; };
  }

  // The hotel for tonight (the one whose stay covers today; before the trip the first, after it the last, between two
  // stays the next), and its card for a taxi driver, from the "Hotel" button in the bar. There whatever the day.
  function tonightHotel() {
    const hs = [...T.hotels].filter(h => h.start && h.end).sort((a, b) => a.start.localeCompare(b.start));
    if (!hs.length) return null;
    const d = now().date;
    return hs.find(h => h.start <= d && d < h.end) || hs.find(h => h.start > d) || hs.at(-1);
  }
  function showHotel() {
    const h = tonightHotel(); if (!h) return;
    const p = h.gplace || {}, local = !!p.local_name;
    const d = now().date, when = h.start <= d && d < h.end ? "Tonight" : h.start > d ? `From ${fmt(h.start, { month: "short", day: "numeric" })}` : "Last stay";
    showDriver({ name: local ? p.local_name : (p.name || h.name), address: local ? p.local_address : (p.address || h.address || ""),
                 en: local ? (p.name || h.name) : h.city, lang: local ? p.language : "en", map: p.map || null, kicker: `${when} · ${h.city}` });
  }

  // --- the viewer --------------------------------------------------------------------------------------------------
  const viewer = $("#viewer");
  function openDoc(id, title) {
    const d = T.docs[id]; if (!d) return;
    $(".v-kicker", viewer).textContent = title || "";
    $(".v-title", viewer).textContent = (d.subject || (d.pages.length ? "Screenshot" : "Confirmation")).replace(/^(fwd?|re):\s*/i, "");
    const body = $(".v-body", viewer);
    let html = "";
    if (d.translation) html += `<div class="lang" role="tablist"><button class="on" data-src="${d.translation}">English</button><button data-src="${d.email}">${esc(d.language)} <small>original</small></button></div>`;
    if (d.email) html += `<div class="frame"><iframe src="${d.translation || d.email}" title="Email" scrolling="no"></iframe></div>`;
    if (d.email && d.pages.length) html += `<div class="label kicker">Attached</div>`;
    html += d.pages.map(p => `<div class="page"><img src="${p}" alt=""></div>`).join("");
    const when = d.received ? new Date(d.received).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "";
    html += `<div class="meta">${d.sender ? `From ${esc(d.sender)}` : "Saved"}${when ? ` · ${when}` : ""}${d.gmail ? ` · <a href="${esc(d.gmail)}">Open in Gmail</a>` : ""}</div>`;
    body.innerHTML = html;
    body.scrollTop = 0;
    viewer.hidden = false;
    document.body.style.overflow = "hidden";
    statusBar(); dockMove();
    const fr = $("iframe", body);
    if (fr) {
      const fit = () => {
        try {
          const doc = fr.contentDocument; if (!doc?.body) return;
          const box = fr.parentElement.clientWidth;
          fr.style.width = box + "px"; fr.style.transform = "";
          const w = Math.max(box, doc.documentElement.scrollWidth, doc.body.scrollWidth);
          const scale = Math.min(1, box / w);
          fr.style.width = w + "px";
          const h = Math.max(doc.documentElement.scrollHeight, doc.body.scrollHeight);
          fr.style.height = h + "px";
          fr.style.transform = scale < 1 ? `scale(${scale})` : "";
          fr.parentElement.style.height = Math.ceil(h * scale) + "px";
        } catch (e) { fr.style.width = "100%"; fr.style.height = "70vh"; }
      };
      fr.addEventListener("load", () => { fit(); setTimeout(fit, 400); setTimeout(fit, 1500);
        try { fr.contentDocument.addEventListener("click", ev => { const a = ev.target.closest("a[href]"); if (a) { ev.preventDefault(); openLink(a.href); } }); } catch (e) {} });
    }
  }
  function closeDoc() { viewer.hidden = true; document.body.style.overflow = ""; $(".v-body", viewer).innerHTML = ""; statusBar(); dockMove(); }
  $(".v-close", viewer).addEventListener("click", closeDoc);
  viewer.addEventListener("click", e => {
    const p = e.target.closest(".page"); if (p) p.classList.toggle("zoom");
    const l = e.target.closest(".lang button");                      // English ⇄ the original, to show someone there
    if (l && !l.classList.contains("on")) {
      l.parentElement.querySelectorAll("button").forEach(b => b.classList.toggle("on", b === l));
      const fr = $(".v-body iframe", viewer); fr.parentElement.style.height = ""; fr.src = l.dataset.src;
    }
  });

  // --- the native shell, when there is one (webshell): links out, copying, updates ----------------------------------
  const shell = window.webkit?.messageHandlers?.shell;
  function openLink(href) { if (shell) shell.postMessage({ open: href }); else window.open(href, "_blank"); }
  function copy(text) {
    if (shell) shell.postMessage({ copy: text });
    else navigator.clipboard?.writeText(text).catch(() => {});
    toast("Copied");
  }
  let toastTimer;
  function toast(text, action) {
    const t = $("#toast");
    t.innerHTML = esc(text) + (action ? ` <button>${esc(action.label)}</button>` : "");
    if (action) $("button", t).onclick = () => { t.hidden = true; action.run(); };
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.hidden = true, action ? 12000 : 1600);
  }
  window.addEventListener("shell", e => {                      // the shell tells us about updates
    const d = e.detail || {};
    if (d.contentReady) toast("The itinerary was updated", { label: "Show", run: () => shell ? shell.postMessage({ reload: true }) : location.reload() });
    if (d.shellUpdate) toast(`App update ${d.shellUpdate.version} available`, { label: "Install", run: () => openLink(d.shellUpdate.install) });
    if (d.version) { $("#shellv").innerHTML = ` · app ${esc(d.version)} · <button id="check">Check for updates</button>`; $("#check").onclick = () => { toast("Checking…"); shell.postMessage({ checkUpdates: true }); }; }
    if (d.checked === "upToDate") toast("You have the latest itinerary");
    if (d.checked === "failed") toast("No connection — showing the copy on this phone");
  });
  // the status bar's text: white over photographs, ink over paper
  let barStyle = "";
  const dark = matchMedia("(prefers-color-scheme: dark)");
  function statusBar() {
    const overPhoto = VIEW === "itinerary" && viewer.hidden && $("#menu").hidden && $(".cover").getBoundingClientRect().bottom > 40;
    const want = overPhoto || dark.matches ? "light" : "dark";
    if (want !== barStyle) { barStyle = want; shell?.postMessage({ statusBar: want }); }
  }

  // --- as a web app (no native shell): a service worker keeps every file for offline and fetches new versions ---------
  if (!shell && "serviceWorker" in navigator && /^https?:$/.test(location.protocol)) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
    navigator.serviceWorker.addEventListener("message", e => window.dispatchEvent(new CustomEvent("shell", { detail: e.data || {} })));
    setTimeout(() => { const el = $("#shellv"); if (el) el.textContent = " · web app"; }, 0);          // after render()
    const ask = () => navigator.serviceWorker.ready.then(r => r.active?.postMessage({ check: true })).catch(() => {});
    ask(); document.addEventListener("visibilitychange", () => { if (!document.hidden) ask(); });
  }

  // --- views: the itinerary, and other looks at the same trip, chosen from the menu (☰). #weather etc. in the address. ---
  const VIEWS = {
    itinerary: { title: T.name, label: "Itinerary", sub: "The trip, day by day" },
    weather: { title: "The weather", label: "Weather at a glance", sub: "Every day's forecast on one page, for packing", render: weatherView,
               when: () => Object.keys(T.weather?.days || {}).length > 0 },
    phrases: { title: "Phrasebook", label: "Phrasebook", sub: "Say it in the local language: tap to hear it", render: phraseView,
               when: () => !!T.phrases?.sections?.length },
  };
  let VIEW = "itinerary";
  const keep = {};                                          // where each view was scrolled to
  function showView(name, opts = {}) {
    if (!VIEWS[name] || (VIEWS[name].when && !VIEWS[name].when())) name = "itinerary";
    if (name === VIEW && !opts.force) { closeMenu(); return; }
    keep[VIEW] = scrollY;
    VIEW = name;
    document.body.dataset.view = name;
    $("#app").hidden = name !== "itinerary";
    $("#alt").hidden = name === "itinerary";
    if (name !== "itinerary") { $("#alt").innerHTML = VIEWS[name].render(); $("#alt").classList.remove("in"); requestAnimationFrame(() => $("#alt").classList.add("in")); }
    const want = "#" + (name === "itinerary" ? "" : name);
    if ((location.hash || "#") !== want && !opts.fromHash) history.pushState(null, "", name === "itinerary" ? location.pathname + location.search : want);
    closeMenu();
    window.scrollTo(0, name === "itinerary" ? (keep.itinerary || 0) : 0);
    bar(); statusBar(); dockMove();
  }
  addEventListener("popstate", () => showView((location.hash || "").slice(1) || "itinerary", { fromHash: true }));
  addEventListener("hashchange", () => showView((location.hash || "").slice(1) || "itinerary", { fromHash: true }));

  // the menu: a paper panel from the left, the views listed as a brochure's contents
  const menu = $("#menu");
  function openMenu() {
    const items = Object.entries(VIEWS).filter(([, v]) => !v.when || v.when());
    $(".panel", menu).innerHTML = `
      <div class="m-head"><div class="kicker">${esc(T.family || "")}${T.family ? " · " : ""}${fmt(T.start, { month: "short", day: "numeric" })} – ${fmt(T.end, { month: "short", day: "numeric" })}</div>
        <div class="m-title">${esc(T.name)}</div><button class="m-close" type="button" aria-label="Close">${'<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>'}</button></div>
      <button type="button" class="m-search" data-search><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/></svg>Search the trip</button>
      <ol class="m-items">${items.map(([k, v], i) => `<li><button type="button" data-view="${k}" class="${k === VIEW ? "on" : ""}">
        <span class="n">${["I", "II", "III", "IV", "V", "VI"][i] || i + 1}</span><span class="t"><b>${esc(v.label)}</b><small>${esc(v.sub)}</small></span></button></li>`).join("")}</ol>
      ${T.seal ? `<div class="m-seal${CJK.test(T.seal) ? "" : " h"}">${esc(T.seal)}</div>` : ""}`;
    menu.hidden = false;
    requestAnimationFrame(() => menu.classList.add("open"));
    $("#menu-btn").setAttribute("aria-expanded", "true");
    statusBar();
  }
  function closeMenu() {
    if (menu.hidden) return;
    menu.classList.remove("open");
    $("#menu-btn").setAttribute("aria-expanded", "false");
    setTimeout(() => { if (!menu.classList.contains("open")) menu.hidden = true; statusBar(); }, 320);
  }
  $("#menu-btn").addEventListener("click", () => menu.hidden ? openMenu() : closeMenu());
  menu.addEventListener("click", e => {
    const b = e.target.closest("[data-view]");
    if (b) return showView(b.dataset.view);
    if (e.target.closest(".scrim, .m-close")) closeMenu();
  });
  // over the cover the button is white on the photograph; elsewhere ink on paper
  function menuTone() { $("#menu-btn").classList.toggle("over", VIEW === "itinerary" && $(".cover").getBoundingClientRect().bottom > 50); }

  // --- search: everything in the trip, offline. Plans, stays, confirmations (and the emails' own words) and phrases;
  //     every word typed must appear somewhere; a title outranks a place, a place a fact, a fact the small print. ------
  // folded for matching: no accents, no case, no punctuation ("Wi-Fi" = "wifi", "check-in" = "check in"); `at` maps each
  // folded character back to the original one, so a match can be marked where it really is
  function folded(s) {
    let out = "", at = [];
    [...String(s ?? "")].forEach((c, i) => {
      const f = c.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
      for (const ch of f) if (/[\p{L}\p{N}\s]/u.test(ch)) { out += /\s/.test(ch) ? " " : ch; at.push(i); }
    });
    return { s: out, at };
  }
  const fold = s => folded(s).s;
  const arrows = s => String(s || "").replace(/\s*->\s*/g, " → ");
  const distinct = parts => { const kept = [];                  // "The Thousand Kyoto", "Kyoto": the first says it all
    for (const p of parts.map(x => String(x || "").trim()).filter(Boolean)) if (!kept.some(k => fold(k).includes(fold(p)))) kept.push(p);
    return kept.join(" · "); };
  let INDEX = null;
  function searchIndex() {
    if (INDEX) return INDEX;
    const out = [], when = iso => iso ? `${fmt(iso, { weekday: "long", month: "long", day: "numeric" })} ${fmt(iso, { month: "short", day: "numeric" })}` : "";
    const legOf = id => T.legs.find(l => l.kind === "stay" && l.events.includes(id));
    for (const e of T.events) {
      const cp = e.copy || {}, docs = (e.docs || []).map(d => T.docs[d]).filter(Boolean);
      out.push({ kind: "plan", id: e.id, date: e.date, start: e.start, color: color(legOf(e.id)?.title || (e.city || "").split(/\s*(?:->|→)\s*/).pop()),
        title: e.title, fields: [[e.title, 6], [arrows(distinct([e.place, e.gplace?.name, e.city])), 3],
          [(cp.facts || []).map(f => `${f.label}: ${f.value}`).join(" · ") + (e.confirmation ? ` · Confirmation: ${e.confirmation}` : ""), 2],
          [arrows(`${cp.blurb || ""} ${e.notes || ""}`), 1], [when(e.date), 4], [docs.map(d => d.subject || "").join(" · "), 1]] });
    }
    for (const h of T.hotels) {
      const cp = h.copy || {};
      out.push({ kind: "stay", id: h.id, date: h.start, color: color(h.city), title: h.name,
        fields: [[h.name, 6], [distinct([h.address, h.city, h.country]), 3],
          [[...(cp.facts || []).map(f => `${f.label}: ${f.value}`), h.room, h.perks, h.confirmation && `Confirmation: ${h.confirmation}`].filter(Boolean).join(" · "), 2],
          [cp.blurb || "", 1], [`${when(h.start)} ${when(h.end)}`, 4]] });
    }
    for (const d of Object.values(T.docs || {})) {
      const sent = new Date(d.sent || d.received || ""), day = isNaN(sent) ? "" : sent.toISOString().slice(0, 10);
      out.push({ kind: "doc", id: d.id, date: day, title: (d.subject || "Confirmation").replace(/^(fwd?|re):\s*/i, ""),
        fields: [[d.subject || "", 5], [d.sender || "", 3], [d.text || "", 1]] });
    }
    for (const sec of T.phrases?.sections || [])
      for (const ph of sec.phrases)
        for (const [lang, x] of Object.entries(ph))
          if (x && typeof x === "object" && x.text)
            out.push({ kind: "phrase", id: `${lang}:${x.text}`, title: ph.en, lang, x, en: ph.en,
              fields: [[ph.en, 5], [`${x.text} ${x.roman}`, 4], [x.note || ph.note || "", 1]] });
    for (const it of out) it.folded = it.fields.map(([t, w]) => [fold(t), w, t]);
    return INDEX = out;
  }
  function searchFor(q) {
    const words = fold(q).split(/\s+/).filter(Boolean);
    if (!words.length) return [];
    const hits = [];
    for (const it of searchIndex()) {
      let score = 0, best = null;
      const ok = words.every(w => {
        let found = false;
        for (const [f, weight, raw] of it.folded) {
          const i = f.indexOf(w);
          if (i < 0) continue;
          found = true;
          const s = weight * (i === 0 || /[^a-z0-9]/.test(f[i - 1]) ? 2 : 1);
          score += s;
          if (!best || weight > best.weight && weight < 6) best = { raw, i, weight };      // where to quote from (not the title)
        }
        return found;
      });
      if (ok) hits.push({ it, score, best });
    }
    return hits.sort((a, b) => b.score - a.score || String(a.it.date || "").localeCompare(String(b.it.date || "")));
  }
  function marked(text, q, around) {
    // the text with the typed words marked; around = a character to centre a snippet on (long texts)
    let t = String(text || "");
    if (around != null && t.length > 140) {
      const at = folded(t).at[around] ?? around, a = Math.max(0, at - 50);
      t = (a ? "…" : "") + t.slice(a, a + 140).trim() + (a + 140 < t.length ? "…" : "");
    }
    const words = fold(q).split(/\s+/).filter(Boolean).sort((a, b) => b.length - a.length);
    const { s: f, at } = folded(t), on = new Array(t.length).fill(false);
    for (const w of words) for (let i = f.indexOf(w); i >= 0; i = f.indexOf(w, i + 1)) for (let k = i; k < i + w.length; k++) on[at[k]] = true;
    let html = "", open = false;
    for (let i = 0; i < t.length; i++) {
      if (on[i] !== open) { html += on[i] ? "<mark>" : "</mark>"; open = on[i]; }
      html += esc(t[i]);
    }
    return html + (open ? "</mark>" : "");
  }
  const SEARCH_HEADS = { plan: "Plans", stay: "Stays", doc: "Confirmations", phrase: "Phrases" };
  function searchResults(q) {
    const hits = searchFor(q);
    if (!q.trim()) {
      const cities = T.legs.filter(l => l.kind === "stay").map(l => l.title);
      const tries = [...cities.slice(0, 3), "Confirmation", "Check-in", T.phrases ? "Thank you" : null].filter(Boolean);
      return `<p class="s-hint">Plans, stays, confirmation numbers, the emails' own words${T.phrases ? " and the phrasebook" : ""}.</p>
        <div class="s-try">${tries.map(t => `<button type="button" data-try="${esc(t)}">${esc(t)}</button>`).join("")}</div>`;
    }
    if (!hits.length) return `<p class="s-none">Nothing for “${esc(q)}”.</p>`;
    const groups = {};
    for (const h of hits) (groups[h.it.kind] ||= []).push(h);
    const order = Object.keys(SEARCH_HEADS).filter(k => groups[k]).sort((a, b) => groups[b][0].score - groups[a][0].score);   // the best match's group first
    return order.map(k => `<h2 class="kicker sec">${SEARCH_HEADS[k]} <span>${groups[k].length}</span></h2>
      <ol class="s-list">${groups[k].slice(0, 30).map(({ it, best }) => {
        const snip = best && best.weight < 6 ? `<span class="s-snip">${marked(best.raw, q, best.i)}</span>` : "";
        if (it.kind === "phrase") return `<li><button type="button" class="s-row s-ph" data-say="${esc(JSON.stringify({ en: it.en, text: it.x.text, roman: it.x.roman, audio: it.x.audio, lang: it.lang }))}">
            <span class="s-main"><b>${marked(it.en, q)}</b><span class="native" lang="${esc(it.lang)}">${marked(it.x.text, q)}</span><span class="s-snip">${marked(it.x.roman, q)}</span></span></button></li>`;
        const date = it.date ? `<span class="s-date"><b>${fmt(it.date, { month: "short", day: "numeric" })}</b>${it.start ? `<small>${esc(clock(it.start).replace(/<[^>]+>/g, ""))}</small>` : `<small>${fmt(it.date, { weekday: "short" })}</small>`}</span>` : `<span class="s-date"></span>`;
        return `<li><button type="button" class="s-row" data-hit="${it.kind}:${esc(it.id)}" style="--c:${it.color || "var(--ink-3)"}">${date}
            <span class="s-main"><b>${marked(it.title, q)}</b>${snip}</span></button></li>`;
      }).join("")}</ol>`).join("");
  }
  const searchEl = () => document.getElementById("search");
  function openSearch(q = "") {
    const el = searchEl();
    el.innerHTML = `<div class="s-bar"><label class="s-field"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/></svg>
        <input type="search" enterkeyhint="search" autocomplete="off" autocorrect="off" spellcheck="false" placeholder="Search the trip" aria-label="Search the trip"></label>
        <button type="button" class="s-done">Done</button></div><div class="s-out wrap"></div>`;
    el.hidden = false;
    document.body.style.overflow = "hidden";
    requestAnimationFrame(() => el.classList.add("open"));
    const input = $("input", el), out = $(".s-out", el);
    let t;
    const run = () => { out.innerHTML = searchResults(input.value); out.scrollTop = 0; };
    input.value = q; run();
    input.addEventListener("input", () => { clearTimeout(t); t = setTimeout(run, 60); });
    input.addEventListener("keydown", e => { if (e.key === "Escape") closeSearch(); if (e.key === "Enter") input.blur(); });
    setTimeout(() => input.focus({ preventScroll: true }), 60);
    statusBar();
  }
  function closeSearch() {
    const el = searchEl();
    if (el.hidden) return;
    el.classList.remove("open"); document.body.style.overflow = "";
    setTimeout(() => { el.hidden = true; el.innerHTML = ""; statusBar(); }, 220);
  }
  function goTo(el) {                                           // the itinerary, scrolled to it, which glows for a moment
    if (!el) return;
    el.querySelector("details.notes")?.setAttribute("open", "");
    el.scrollIntoView({ behavior: "auto", block: "center" });
    el.classList.remove("found"); void el.offsetWidth; el.classList.add("found");
    setTimeout(() => el.classList.remove("found"), 2400);
  }
  document.addEventListener("click", e => {
    const el = searchEl();
    if (e.target.closest("[data-search]")) { closeMenu(); return openSearch(); }
    if (!el || el.hidden || !el.contains(e.target)) return;
    if (e.target.closest(".s-done")) return closeSearch();
    const tr = e.target.closest("[data-try]");
    if (tr) { const i = $("input", el); i.value = tr.dataset.try; i.dispatchEvent(new Event("input")); return; }
    const hit = e.target.closest("[data-hit]");
    if (!hit) return;
    const [kind, id] = [hit.dataset.hit.slice(0, hit.dataset.hit.indexOf(":")), hit.dataset.hit.slice(hit.dataset.hit.indexOf(":") + 1)];
    closeSearch();
    if (kind === "doc") return openDoc(id, "Search");
    if (VIEW !== "itinerary") showView("itinerary");
    requestAnimationFrame(() => {
      if (kind === "plan") goTo(document.getElementById("ev-" + id));
      if (kind === "stay") goTo([...document.querySelectorAll(".chapter")].find(c => $(".stay h3", c)?.textContent === hotels[id]?.name)?.querySelector(".stay"));
    });
  }, true);
  addEventListener("keydown", e => {
    if ((e.key === "/" || (e.key === "k" && (e.metaKey || e.ctrlKey))) && !/input|textarea/i.test(document.activeElement?.tagName || "")) { e.preventDefault(); openSearch(); }
    if (e.key === "Escape") closeSearch();
  });

  // --- the weather, at a glance: the whole trip on one page, for packing ----------------------------------------------
  function tempColor(t) {                                  // a cool-to-warm ramp, for the range bars
    const stops = [[30, [93, 128, 178]], [45, [104, 154, 196]], [55, [120, 178, 160]], [65, [226, 180, 82]], [75, [226, 132, 66]], [90, [196, 72, 48]]];
    for (let i = 1; i < stops.length; i++) if (t <= stops[i][0]) {
      const [t0, c0] = stops[i - 1], [t1, c1] = stops[i], f = Math.max(0, (t - t0) / (t1 - t0));
      return `rgb(${c0.map((v, j) => Math.round(v + (c1[j] - v) * f)).join(",")})`;
    }
    return "rgb(196,72,48)";
  }
  const dayLabel = iso => fmt(iso, { weekday: "short" });
  const dayNum = iso => fmt(iso, { month: "short", day: "numeric" });
  function weatherView() {
    const W = T.weather?.days || {};
    const rows = [];                                        // one per city per day, in trip order
    const dates = (T.days || []).map(d => d.date);
    dates.forEach(iso => (W[iso] || []).forEach((w, i) => rows.push({ ...w, iso, first: i === 0 })));
    if (!rows.length) return `<div class="wrap wv"><p class="lede">No forecast yet: it reaches about two weeks ahead.</p></div>`;
    const lo = Math.min(...rows.map(r => r.lo)), hi = Math.max(...rows.map(r => r.hi));
    const pad = 2, min = lo - pad, max = hi + pad, pos = t => ((t - min) / (max - min)) * 100;
    const coldest = rows.reduce((a, b) => b.lo < a.lo ? b : a), warmest = rows.reduce((a, b) => b.hi > a.hi ? b : a);
    const wet = rows.filter(r => r.rain >= 50), maybe = rows.filter(r => r.rain >= 30 && r.rain < 50);
    const wetDays = [...new Set(wet.map(r => r.iso))], maybeDays = [...new Set(maybe.map(r => r.iso))].filter(d => !wetDays.includes(d));
    const list = isos => isos.map(d => `${dayLabel(d)} ${fmt(d, { day: "numeric" })}`).join(", ");
    // what to pack, said plainly, from the numbers
    const notes = [];
    if (coldest.lo <= 52) notes.push(["layer", `A warm layer for the evenings`, `lows reach ${coldest.lo}° in ${coldest.city} on ${dayLabel(coldest.iso)} ${dayNum(coldest.iso)}`]);
    if (warmest.hi >= 74) notes.push(["sun", `Light clothes for warm afternoons`, `up to ${warmest.hi}° in ${warmest.city} on ${dayLabel(warmest.iso)} ${dayNum(warmest.iso)}`]);
    if (wetDays.length) notes.push(["rain", `An umbrella or rain jacket`, `rain is likely on ${list(wetDays)}${maybeDays.length ? `, and possible on ${list(maybeDays)}` : ""}`]);
    else if (maybeDays.length) notes.push(["rain", `A compact umbrella, just in case`, `rain is possible on ${list(maybeDays)}`]);
    if (!notes.length) notes.push(["sun", "Pack for mild weather", `highs ${Math.min(...rows.map(r => r.hi))}–${hi}°, lows from ${lo}°`]);
    const NOTE_ICON = { layer: '<path d="M8 4l4 2 4-2 4 3-2 4-2-1v10H8V10l-2 1-2-4z"/>', sun: WX.sun, rain: '<path d="M12 3v1M4 12a8 8 0 0 1 16 0z"/><path d="M12 12v7a2 2 0 0 1-4 0"/>' };
    // the cities: each stay's span of days, in route order
    const stays = T.legs.filter(l => l.kind === "stay");
    const cityCards = stays.map(l => {
      const rs = rows.filter(r => r.city === l.title && r.iso >= l.start && r.iso <= l.end);
      if (!rs.length) return "";
      const h = rs.map(r => r.hi), lw = rs.map(r => r.lo), rainy = rs.filter(r => r.rain >= 50).length;
      const [k] = wxKind(rs.reduce((a, b) => b.code > a.code ? b : a).code);
      return `<li style="--c:${color(l.title)}"><div class="cc-top"><b>${esc(l.title)}</b><svg viewBox="0 0 24 24" aria-hidden="true">${WX[k]}</svg></div>
        <div class="cc-dates">${dayNum(l.start)} – ${dayNum(l.end)}</div>
        <div class="cc-t"><span>${Math.max(...h)}°</span><small>${Math.min(...lw)}°</small></div>
        <div class="cc-r">${rainy ? `${rainy} wet day${rainy > 1 ? "s" : ""}` : "Mostly dry"}</div></li>`;
    }).join("");
    const ticks = []; for (let t = Math.ceil(min / 10) * 10; t <= max; t += 10) ticks.push(t);
    const dayRows = dates.map(iso => {
      const ws = W[iso];
      const today = iso === now().date ? " today" : "";
      if (!ws?.length) return `<li class="d none${today}"><div class="when"><b>${dayLabel(iso)}</b><span>${dayNum(iso)}</span></div><div class="none-t">Not in the forecast yet</div></li>`;
      return `<li class="d${today}"><div class="when"><b>${dayLabel(iso)}</b><span>${dayNum(iso)}</span></div><div class="cities">${ws.map(w => { const [k, word] = wxKind(w.code);
        return `<div class="c" style="--c:${color(w.city)}"><span class="city">${esc(w.city)}</span><span class="ic" title="${esc(word)}"><svg viewBox="0 0 24 24" aria-hidden="true">${WX[k]}</svg></span>
          <span class="rain${w.rain >= 50 ? " wet" : w.rain >= 30 ? " maybe" : ""}">${w.rain >= 10 ? `${w.rain}%` : ""}</span>
          <span class="lo">${w.lo}°</span><span class="track"><i style="left:${pos(w.lo)}%;width:${pos(w.hi) - pos(w.lo)}%;background:linear-gradient(90deg, ${tempColor(w.lo)}, ${tempColor(w.hi)})"></i></span><span class="hi">${w.hi}°</span></div>`; }).join("")}</div></li>`;
    }).join("");
    const when = T.weather.sample ? "a sample forecast" : `forecast by Open-Meteo, updated ${new Date(T.weather.updated).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}`;
    return `<div class="wrap wv">
      <header class="wv-head"><div class="kicker">At a glance · ${dayNum(T.start)} – ${dayNum(T.end)}</div><h1>The weather</h1>
        <p>${rows.length ? `Highs ${Math.min(...rows.map(r => r.hi))}–${hi}°, lows ${lo}–${Math.max(...rows.map(r => r.lo))}°. ` : ""}It firms up as the days come closer; ${esc(when)}.</p></header>
      <section class="pack"><div class="range"><span>${lo}°</span><i style="background:linear-gradient(90deg, ${tempColor(lo)}, ${tempColor((lo + hi) / 2)}, ${tempColor(hi)})"></i><span>${hi}°</span><small>coolest night to warmest afternoon</small></div>
        <h2 class="kicker">What to pack</h2>
        <ul>${notes.map(([k, a, b]) => `<li><svg viewBox="0 0 24 24" aria-hidden="true">${NOTE_ICON[k]}</svg><div><b>${esc(a)}</b><span>${esc(b)}</span></div></li>`).join("")}</ul></section>
      <h2 class="kicker sec">By city</h2><ol class="cities-sum">${cityCards}</ol>
      <h2 class="kicker sec">Day by day <span>${ticks.map(t => `${t}°`).join(" · ")}</span></h2>
      <ol class="days-wx">${dayRows}</ol>
      <p class="wv-foot">Rain is the chance of any rain that day. ${esc(when.charAt(0).toUpperCase() + when.slice(1))}.</p>
    </div>`;
  }

  // --- the phrasebook: tap to hear (naturally, slowly, naturally), hold the card up to show someone ------------------
  const SPEAKER = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9.5h3.5L12 5.5v13L7.5 14.5H4z"/><path d="M15.5 9a4 4 0 0 1 0 6M18.3 6.5a7.5 7.5 0 0 1 0 11"/></svg>';
  const BARS = '<span class="bars" aria-hidden="true"><i></i><i></i><i></i></span>';
  function phraseLang() {
    const langs = Object.keys(T.phrases?.languages || {});
    let pick = null;
    try { pick = sessionStorage.getItem("phrases.lang"); } catch (e) {}
    if (pick && langs.includes(pick)) return pick;
    const today = (T.days || []).find(d => d.date === now().date);           // on the road: the country you are in
    const country = today && (T.hotels.find(h => h.id === today.hotel_id) || {}).country;
    return langs.find(l => (T.phrases.languages[l].countries || []).includes(country)) || langs[0];
  }
  function phraseView() {
    const P = T.phrases, lang = phraseLang(), L = P.languages[lang];
    const tabs = Object.entries(P.languages).map(([k, v]) => `<button type="button" data-plang="${k}" class="${k === lang ? "on" : ""}"><b lang="${k}">${esc(v.native)}</b><small>${esc(v.name)}</small></button>`).join("");
    const sections = P.sections.map(sec => {
      const rows = sec.phrases.filter(ph => ph[lang]).map((ph, i) => { const x = ph[lang];
        return `<li><button type="button" class="ph" data-say="${esc(JSON.stringify({ en: ph.en, text: x.text, roman: x.roman, audio: x.audio, lang }))}">
            <span class="en">${esc(ph.en)}</span><span class="native${[...x.text].length > 8 ? " long" : ""}" lang="${lang}">${esc(x.text)}</span><span class="roman">${esc(x.roman)}</span>${x.note || ph.note ? `<span class="note">${esc(x.note || ph.note)}</span>` : ""}</button>
          ${x.learn ? `<button type="button" class="play" data-play="${x.learn}" aria-label="Hear “${esc(ph.en)}”">${SPEAKER}${BARS}</button>` : ""}</li>`; }).join("");
      return rows ? `<h2 class="kicker sec">${esc(sec.title)}</h2><ol class="phrases">${rows}</ol>` : "";
    }).join("");
    return `<div class="wrap pv">
      <header class="wv-head"><div class="kicker">Phrasebook · ${esc(L.name)}</div><h1>Say it</h1>
        <p>Tap the speaker to hear a phrase said naturally, then slowly, then naturally again. Tap the words to show them to someone.</p></header>
      <div class="ptabs" role="tablist">${tabs}</div>
      ${sections}
      <p class="wv-foot">Voices by Gemini, each recording checked by ear. Phrases are polite and simple: people are kind to visitors who try.</p>
    </div>`;
  }
  // playing: one at a time; the files are read as blobs (plays inside the app, offline, with no media range requests)
  const blobs = {};
  let playing = null;
  async function play(src, btn) {
    if (playing) { playing.audio.pause(); playing.btn?.classList.remove("on"); const was = playing.src; playing = null; if (was === src && btn) return; }
    try {
      if (!blobs[src]) blobs[src] = URL.createObjectURL(await (await fetch(src)).blob());
      const audio = new Audio(blobs[src]);
      playing = { audio, btn, src };
      btn?.classList.add("on");
      audio.onended = audio.onpause = () => { btn?.classList.remove("on"); if (playing?.audio === audio) playing = null; };
      await audio.play();
    } catch (e) { btn?.classList.remove("on"); toast("Couldn't play that one"); }
  }
  function showSay(d) {
    const el = document.getElementById("say");
    el.innerHTML = `<button class="x" type="button" aria-label="Close"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
      <div class="card"><div class="native" lang="${esc(d.lang)}">${esc(d.text)}</div><div class="roman">${esc(d.roman)}</div><div class="en">${esc(d.en)}</div>
        ${d.audio ? `<button class="play big" type="button" data-play="${esc(d.audio)}" aria-label="Play">${SPEAKER}${BARS}<span>Play</span></button>` : ""}</div>`;
    el.hidden = false;
    statusBar();
  }
  document.addEventListener("click", e => {
    const t = e.target.closest("[data-plang]");
    if (t) { try { sessionStorage.setItem("phrases.lang", t.dataset.plang); } catch (err) {} const y = scrollY; $("#alt").innerHTML = phraseView(); window.scrollTo(0, y); return; }
    const pl = e.target.closest("[data-play]");
    if (pl) { e.stopPropagation(); play(pl.dataset.play, pl); return; }
    const sy = e.target.closest("[data-say]");
    if (sy) { showSay(JSON.parse(sy.dataset.say)); return; }
    if (e.target.closest("#say .x")) { if (playing) playing.audio.pause(); $("#say").hidden = true; statusBar(); }
  });

  // --- go ------------------------------------------------------------------------------------------------------------
  document.title = T.name;
  render();
  mark();
  document.addEventListener("click", e => {
    const j = e.target.closest("[data-jump]");
    if (j) { document.getElementById(j.dataset.jump)?.scrollIntoView({ behavior: "smooth" }); return; }
    const d = e.target.closest("[data-doc]");
    if (d) { openDoc(d.dataset.doc, d.dataset.for); return; }
    const dv = e.target.closest("[data-driver]");
    if (dv) { showDriver(JSON.parse(dv.dataset.driver)); return; }
    const c = e.target.closest("[data-copy]");
    if (c) { copy(c.dataset.copy); return; }
    const a = e.target.closest("a[href]");
    if (a && !viewer.contains(a) && /^(https?|maps|nmap):/.test(a.getAttribute("href"))) { e.preventDefault(); openLink(a.href); }
    if (a && viewer.contains(a)) { e.preventDefault(); openLink(a.href); }
  });
  $("#bar-title").addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
  $("#bar-today").addEventListener("click", () => goToday(true));
  $("#bar-hotel").hidden = !tonightHotel();
  $("#bar-hotel").addEventListener("click", showHotel);
  addEventListener("scroll", () => requestAnimationFrame(() => { bar(); statusBar(); dockMove(); menuTone(); }), { passive: true });
  addEventListener("resize", () => requestAnimationFrame(dockLayout));
  document.fonts?.ready.then(dockLayout);
  dark.addEventListener?.("change", statusBar);
  addEventListener("keydown", e => { if (e.key === "Escape") { closeDoc(); closeMenu(); } });
  setInterval(mark, 60e3);
  let hiddenAt = 0;
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { hiddenAt = Date.now(); return; }
    mark();
    const away = hiddenAt && Date.now() - hiddenAt > 10 * 60e3;                // back after a while: to what is on now
    if (away && onTrip() && viewer.hidden && $("#driver").hidden) goNow(true);
  });
  DEPART = Math.min(...T.events.map(span).filter(Boolean).map(x => x[0]));
  const asked = (location.hash || "").slice(1);
  if (VIEWS[asked] && asked !== "itinerary") showView(asked, { fromHash: true, force: true });
  else if (onTrip()) requestAnimationFrame(() => goNow(false));
  menuTone();
  bar();
  statusBar();
  dockLayout();
  shell?.postMessage({ ready: true });
})();
