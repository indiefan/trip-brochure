#!/usr/bin/env python3
"""Brochure copy: Claude writes a short blurb and the key facts for every city, hotel and event that lacks them.

    python3 pipeline/brochure_copy.py mytrip/            # only what is new or changed since last time
    python3 pipeline/brochure_copy.py mytrip/ --force    # everything again

Writes into trip.json: cities[name].blurb and .native, hotels[].blurb/.facts, events[].blurb/.facts. Your own
blurb or facts are never overwritten unless --force. Facts come only from the item's own text (notes, confirmation,
address…): Claude is told never to invent a number or a place. Still read them once; they go on the phones.
"""

from __future__ import annotations

import argparse
import json

from pydantic import BaseModel

from common import MODEL, Trip, claude, say
from style import HOUSE

BATCH = 10
PROMPT = """You are writing the copy for a beautifully printed travel brochure: a family's own itinerary for {trip}, \
{start} to {end} (travellers: {people}). {house}

For each item below write:

- blurb: one or two sentences (at most 40 words) a reader enjoys: what this is and why it is a highlight. Warm and \
precise, never gushing; no exclamation marks; present tense. Well-known facts about a famous place are welcome; \
details of this family's booking go in facts, not the blurb. For plain logistics (a taxi, a checkout, a bag drop) one \
short practical sentence.
- facts: the details worth having at hand on the day, as short label/value pairs (at most 7), e.g. Confirmation, \
Seats, Flight, Terminal, Meeting point, Check-in, Check-out, Room, Includes, Tickets, Address, Phone, Cost, Note. Take \
them ONLY from the item's text: never invent or guess a number, time, place or name. Merge repeats. Values short \
(under 90 characters). Leave out the date and start/end time (shown elsewhere) and the status. No facts is fine.
- native: for a "city:" item only, the city's name in its own script when that script is not the Latin alphabet (東京, 서울, Αθήνα); otherwise empty.

Answer for every key given.

Items:
{items}"""


class Fact(BaseModel):
    label: str
    value: str


class Copy(BaseModel):
    key: str
    blurb: str
    facts: list[Fact]
    native: str


class Copies(BaseModel):
    items: list[Copy]


def subjects(t: Trip) -> list[dict]:
    out = []
    for name, c in (t.data.get("cities") or {}).items():
        stays = [h for h in t.hotels if h["city"] == name]
        evs = [e for e in t.events if (e.get("city") or "").split("->")[-1].strip() == name and e.get("type") not in ("Transit", "Lodging")]
        out.append({"key": f"city:{name}", "target": c, "text": f"City stop: {name}, {c.get('country', '')}; {sum(h.get('nights', 0) or 0 for h in stays)} nights at "
                    f"{', '.join(h['name'] for h in stays) or '?'}; highlights: {', '.join(e['title'] for e in evs[:5])}"})
    for h in t.hotels:
        text = "; ".join(f"{k}: {h[k]}" for k in ("name", "city", "room", "booking", "perks", "confirmation", "address", "cost", "notes") if h.get(k))
        out.append({"key": f"stay:{h['id']}", "target": h, "text": f"Hotel stay {h['start']} to {h['end']}. {text}"})
    for e in t.events:
        text = "; ".join(f"{k}: {e[k]}" for k in ("title", "type", "city", "place", "address", "confirmation", "cost", "notes") if e.get(k))
        out.append({"key": f"event:{e['id']}", "target": e, "text": text})
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("trip"); ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    t = Trip(a.trip)
    subs = subjects(t)
    todo = [s for s in subs if t.stale("copy:" + s["key"], s["text"], a.force) and (a.force or not s["target"].get("blurb"))]
    if not todo:
        return say("copy: nothing new")
    client = claude()
    for i in range(0, len(todo), BATCH):
        group = todo[i:i + BATCH]
        items = "\n\n".join(f"[{s['key']}]\n{s['text'][:5000]}" for s in group)
        r = client.messages.parse(model=MODEL, max_tokens=12000, output_config={"effort": "low"}, output_format=Copies,
                                  messages=[{"role": "user", "content": PROMPT.format(house=HOUSE, trip=t.data["name"], start=t.data["start"], end=t.data["end"],
                                                                                      people=", ".join(t.data.get("people") or []) or "the family", items=items)}])
        by_key = {s["key"]: s for s in group}
        short = {k.split(":", 1)[1]: k for k in by_key}
        for c in (r.parsed_output.items if r.parsed_output else []):
            key = c.key.strip("[] "); key = key if key in by_key else short.get(key)
            if not key:
                continue
            s = by_key[key]; tgt = s["target"]
            tgt["blurb"] = c.blurb.strip(); tgt["facts"] = [f.model_dump() for f in c.facts if f.value.strip()]
            if key.startswith("city:") and c.native.strip():
                tgt["native"] = c.native.strip()
            t.done("copy:" + key, s["text"])
            say(f"  {key}: {tgt['blurb'][:70]}")
        t.save()
    say(f"copy: {len(todo)} written")


if __name__ == "__main__":
    main()
