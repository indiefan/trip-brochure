#!/usr/bin/env python3
"""Exact places for the Directions buttons, and a small offline map of each.

    python3 pipeline/places.py mytrip/            # needs GOOGLE_MAPS_KEY; ANTHROPIC_API_KEY lets Claude pick destinations

Two steps per event and hotel:
1. the destination (events[].dest): where to GO for it — the departure station for a train, the venue otherwise — as
   a Google Maps search ending in city and country. Claude picks one from the event's details when it is missing (or
   you write it yourself; anything you write is kept). An https:// link (an operator's own map pin) is used as it is.
2. the place (events[].gplace): Google's Places API resolves the search to its exact place id, coordinates, and the
   name and address in the local script (for showing a driver); the Maps Static API draws a small map → maps/<id>.png.

Keys: console.cloud.google.com → a project with billing → enable "Places API (New)" and "Maps Static API" → an API key.
At a trip's scale this costs cents. Look every match over once (the list this prints): a search like "ICN Terminal 2"
can land on the terminal's parking lot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

import httpx
from pydantic import BaseModel

from common import MODEL, Trip, claude, say

SEARCH = "https://places.googleapis.com/v1/places:searchText"
DETAILS = "https://places.googleapis.com/v1/places/{id}"
STATIC = "https://maps.googleapis.com/maps/api/staticmap"
STYLE = ["feature:all|element:labels.text.fill|color:0x5b554c", "feature:landscape|color:0xf1ebe0", "feature:water|color:0xc6d3dc",
         "feature:poi|element:geometry|color:0xe6dfd1", "feature:poi.park|element:geometry|color:0xd9e3cf", "feature:road|element:geometry|color:0xffffff",
         "feature:road.highway|element:geometry|color:0xf4dcc4", "feature:transit.line|element:geometry|color:0xb7ad9c", "feature:administrative|element:geometry|visibility:off"]
LANG_HINTS = {"japan": "ja", "korea": "ko", "china": "zh", "taiwan": "zh", "thailand": "th", "vietnam": "vi", "france": "fr", "italy": "it", "spain": "es", "germany": "de", "greece": "el", "portugal": "pt"}

PICK = """The family's trip itinerary ({trip}, {start} to {end}). For each item, give the one Google Maps search that \
best finds where they must GO for it, so "Directions" in the trip app takes them there from wherever they are:
- for a transfer (train, bus, flight, taxi), the departure point: the exact station (with its line or operator when it \
matters), bus stop, airport terminal, or pickup place;
- for anything else, the venue itself (the hotel, the restaurant, the museum, the meeting point);
- prefer an exact street address when the item gives one; otherwise the place's proper name; always end with the city \
and country. Use only the item's details and well-known places; never invent an address;
- empty when there is nowhere to go (it happens where they already are, or the place is unknown).

Answer for every key given.

Items:
{items}"""


class Place(BaseModel):
    key: str
    query: str


class Places(BaseModel):
    items: list[Place]


def pick(t: Trip, todo: list[dict]) -> None:
    client = claude()
    items = "\n".join(f"[{e['id']}] " + "; ".join(f"{k}: {e[k]}" for k in ("date", "title", "type", "city", "place", "address", "notes") if e.get(k))[:1500] for e in todo)
    r = client.messages.parse(model=MODEL, max_tokens=4000, output_config={"effort": "low"}, output_format=Places,
                              messages=[{"role": "user", "content": PICK.format(trip=t.data["name"], start=t.data["start"], end=t.data["end"], items=items)}])
    for p in (r.parsed_output.items if r.parsed_output else []):
        e = t.event(p.key.strip("[] "))
        if e is not None:
            e["dest"] = p.query.strip()
            t.done("dest:" + e["id"], dest_text(e))


def dest_text(e: dict) -> str:
    return "|".join(str(e.get(k) or "") for k in ("title", "city", "place", "address", "notes"))


def find(key: str, query: str, http: httpx.Client) -> dict | None:
    h = {"X-Goog-Api-Key": key, "Content-Type": "application/json"}
    r = http.post(SEARCH, headers={**h, "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.location"},
                  json={"textQuery": query, "languageCode": "en", "pageSize": 1})
    r.raise_for_status()
    hits = r.json().get("places") or []
    if not hits:
        return None
    p = hits[0]
    out = {"id": p["id"], "name": p.get("displayName", {}).get("text", ""), "address": p.get("formattedAddress", ""),
           "lat": round(p["location"]["latitude"], 6), "lng": round(p["location"]["longitude"], 6), "local_name": "", "local_address": "", "language": ""}
    q = (query + " " + out["address"]).lower()
    lang = next((v for k, v in LANG_HINTS.items() if k in q), None)
    if lang:
        d = http.get(DETAILS.format(id=p["id"]), headers={**h, "X-Goog-FieldMask": "displayName,formattedAddress"}, params={"languageCode": lang})
        if d.status_code < 400:
            j = d.json(); out.update(local_name=j.get("displayName", {}).get("text", ""), local_address=j.get("formattedAddress", ""), language=lang)
    return out


def static_map(key: str, t: Trip, place: dict, http: httpx.Client) -> str | None:
    name = hashlib.sha1(f"{place['id']}|{place['lat']},{place['lng']}".encode()).hexdigest()[:16]
    path = t.dir / "maps" / f"{name}.png"
    if path.exists():
        return f"maps/{name}.png"
    params = [("center", f"{place['lat']},{place['lng']}"), ("zoom", "16"), ("size", "640x300"), ("scale", "2"), ("language", "en"),
              ("markers", f"color:0xb8432c|{place['lat']},{place['lng']}"), ("key", key)] + [("style", s) for s in STYLE]
    r = http.get(STATIC, params=params)
    if r.status_code != 200 or not r.content.startswith(b"\x89PNG"):
        say(f"    map refused: {r.status_code} {r.text[:100]}"); return None
    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(r.content)
    return f"maps/{name}.png"


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("trip"); ap.add_argument("--force", action="store_true"); ap.add_argument("--no-maps", action="store_true")
    a = ap.parse_args()
    key = os.environ.get("GOOGLE_MAPS_KEY")
    if not key:
        sys.exit("set GOOGLE_MAPS_KEY")
    t = Trip(a.trip)
    todo = [e for e in t.events if not e.get("dest") or (a.force and t.stale("dest:" + e["id"], dest_text(e), True))]
    todo = [e for e in todo if not e.get("dest") or e["dest"].startswith("http")] if not a.force else todo
    if todo and os.environ.get("ANTHROPIC_API_KEY"):
        say(f"picking destinations for {len(todo)} events…"); pick(t, todo); t.save()
    http = httpx.Client(timeout=30)
    wanted = [(e, e.get("dest")) for e in t.events] + [(h, h.get("dest") or f"{h['name']}, {h['city']}, {h.get('country', '')}") for h in t.hotels]
    for obj, q in wanted:
        if not q or q.startswith(("http://", "https://")):
            continue
        if obj.get("gplace") and not t.stale("gplace:" + obj["id"], q, a.force):
            continue
        p = find(key, q, http)
        if not p:
            say(f"  {obj['id']}: nothing found for {q!r}"); continue
        if not a.no_maps:
            p["map"] = static_map(key, t, p, http)
        obj["gplace"] = p; t.done("gplace:" + obj["id"], q)
        say(f"  {obj['id']:10} {p['name'][:40]:40} | {p['address'][:60]}")
        t.save()
    say("places: done — read the list above once; fix a wrong one by editing its dest in trip.json and running again")


if __name__ == "__main__":
    main()
