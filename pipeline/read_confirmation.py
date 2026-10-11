#!/usr/bin/env python3
"""Read a confirmation (a screenshot, PDF or .eml) with Claude and file it on the itinerary.

    python3 pipeline/read_confirmation.py mytrip/ docs/delta.eml            # show what it finds
    python3 pipeline/read_confirmation.py mytrip/ docs/delta.eml --apply    # fill the matching event(s), register the document

Claude lists every booking in the document (a round trip is two), matched to existing events where it clearly is one
of them (then only blank fields of that event are filled; extra confirmation numbers are appended), or added as a new
event (id C-<hex>) otherwise. The document itself is registered under docs/ and linked to those events, so the app
shows it. Keep your own copy of the original; this script never deletes anything.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build import read_eml                                               # noqa: E402
from common import MODEL, Trip, claude, say                              # noqa: E402


class Item(BaseModel):
    kind: str = Field(description="flight | train | hotel | activity | restaurant | transport | other")
    title: str = Field(description="what was booked, short, e.g. 'Delta DL0167 Seattle → Tokyo Haneda'")
    confirmation: str = Field(description="confirmation / record locator / ticket numbers, '' if none")
    date: str = Field(description="YYYY-MM-DD where it starts, '' if not stated")
    end_date: str = Field(description="YYYY-MM-DD if it ends on a later day, else ''")
    start: str = Field(description="HH:MM 24h local start/departure, or ''")
    end: str = Field(description="HH:MM 24h local end/arrival, or ''")
    place: str = Field(description="venue, station, airport codes and terminals, or ''")
    city: str = Field(description="city, or 'A -> B' for travel between cities")
    cost: str = Field(description="total with currency, or ''")
    notes: str = Field(description="what matters on the day: seats, cabin, terminal, travellers, cancellation terms")
    matches_event_id: str = Field(description="id of the existing itinerary event this is, else ''")


class Reading(BaseModel):
    is_trip_related: bool
    notes: str
    items: list[Item]


PROMPT = """This document (a screenshot, a PDF or an email) is a confirmation, ticket or receipt for a family trip. Today is {today}.

List every distinct booking in it (a round trip is two items; one per flight or leg; a hotel one item). For each: dates YYYY-MM-DD (the trip runs {start} to {end}; a hotel's date is check-in and end_date check-out; an overnight flight's end_date is the arrival day); times 24-hour HH:MM, local to where each leg starts or ends; travellers, seats, cabin, terminal, meeting point, what to bring and cancellation terms go in notes. Use '' for anything not stated.

The itinerary already has these events; when an item clearly is one of them (the same flight, tour or booking, even if the event has no times yet), give its id in matches_event_id. Tickets and passes for the same outing all belong to that outing's event. Otherwise leave it '' and it will be added as its own event.
{events}

Existing stays: {hotels}"""


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("trip"); ap.add_argument("file", help="path inside the trip folder, e.g. docs/delta.eml")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    t = Trip(a.trip)
    f = t.dir / a.file
    raw = f.read_bytes()
    content: list = []
    subject = sender = ""
    if f.suffix == ".eml":
        m = read_eml(raw); subject, sender = m["subject"], m["sender"]
        import html as h, re
        text = re.sub(r"<[^>]+>", " ", m["html"]) if m["html"] else m["text"]
        content.append({"type": "text", "text": f"The email:\nFrom: {sender}\nSubject: {subject}\n\n{h.unescape(text)[:20000]}"})
        for name, mime, b in m["attachments"]:
            if mime == "application/pdf":
                content.append({"type": "document", "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(b).decode()}}); break
            content.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(b).decode()}}); break
    elif raw[:4] == b"%PDF":
        content.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": base64.b64encode(raw).decode()}})
    else:
        mime = "image/png" if raw[:4] == b"\x89PNG" else "image/jpeg"
        content.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(raw).decode()}})
    events = "\n".join(f"- {e['id']}: {e['date']} {e.get('start') or ''} {e['title']} @ {e.get('place') or ''} ({e.get('city') or ''})" for e in t.events)
    hotels = "; ".join(f"{h['name']} in {h['city']} {h['start']}–{h['end']}" for h in t.hotels)
    content.append({"type": "text", "text": PROMPT.format(today=date.today().isoformat(), start=t.data["start"], end=t.data["end"], events=events, hotels=hotels)})
    r = claude().messages.parse(model=MODEL, max_tokens=2000, output_config={"effort": "low"}, output_format=Reading, messages=[{"role": "user", "content": content}])
    reading = r.parsed_output
    if reading is None:
        sys.exit("could not read the document")
    print(json.dumps(reading.model_dump(), indent=1, ensure_ascii=False))
    if not a.apply or not reading.is_trip_related:
        return
    did = hashlib.sha1(raw).hexdigest()[:12]
    t.data.setdefault("docs", {})[did] = {"kind": "email" if f.suffix == ".eml" else "file", "file": str(f.relative_to(t.dir)), "subject": subject or None, "sender": sender or None}
    for it in reading.items:
        e = t.event(it.matches_event_id) if it.matches_event_id else None
        if e is None:
            e = {"id": "C-" + hashlib.sha1((did + it.title).encode()).hexdigest()[:6], "date": it.date, "start": it.start or None, "end": it.end or None, "title": it.title,
                 "place": it.place, "type": {"flight": "Transit", "train": "Transit", "transport": "Transit", "hotel": "Lodging", "restaurant": "Food"}.get(it.kind, "Activity"),
                 "city": it.city, "status": "booked", "confirmation": it.confirmation, "cost": it.cost, "notes": it.notes, "docs": []}
            t.events.append(e); say(f"  added {e['id']}: {it.title}")
        else:
            for k, v in (("start", it.start), ("end", it.end), ("place", it.place), ("cost", it.cost)):
                if v and not e.get(k):
                    e[k] = v
            if it.confirmation and it.confirmation not in (e.get("confirmation") or ""):
                e["confirmation"] = ", ".join(x for x in (e.get("confirmation"), it.confirmation) if x)
            if it.notes:
                e["notes"] = ((e.get("notes") or "") + "\n" + it.notes).strip()
            e["status"] = "booked"; say(f"  filled {e['id']}: {e['title']}")
        e.setdefault("docs", [])
        if did not in e["docs"]:
            e["docs"].append(did)
    t.save()


if __name__ == "__main__":
    main()
