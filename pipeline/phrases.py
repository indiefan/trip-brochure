#!/usr/bin/env python3
"""Write the phrasebook (phrases.json) for wherever the trip goes: Claude decides the languages a visitor needs there
(none where English is the everyday language) and writes the everyday phrases in each, the way a polite local says
them (the local variety: Mexican Spanish in Mexico, European Portuguese in Lisbon), with a romanization or an
English-speaker's pronunciation guide and a note where it matters. Each language also gets a voice_style, which
phrase_audio.py uses for its recordings.

    export ANTHROPIC_API_KEY=…
    python3 pipeline/phrases.py mytrip/            # writes mytrip/phrases.json (asks before replacing one)
    python3 pipeline/phrases.py mytrip/ --force    # replace it without asking
    python3 pipeline/phrase_audio.py mytrip/       # then the sound

Read the result once, ideally with someone who speaks the language: a wrong phrase is worse than none. The places it
writes for are the hotels' cities and countries in trip.json, so add the stays first.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import MODEL, Trip, claude, say                                     # noqa: E402
from style import HOUSE                                                         # noqa: E402

BASE = [   # the everyday phrases, by situation; the writer translates and adapts them to each language
    ("essentials", "Essentials", ["Hello", "Thank you", "Excuse me", "I'm sorry", "Yes", "No", "Do you speak English?", "I don't understand", "Goodbye"]),
    ("around", "Getting around", ["Where is the station?", "Where is the restroom?", "Please take me here", "How long does it take?"]),
    ("food", "Eating out", ["A table for {party}, please", "Do you have an English menu?", "This one, please", "Water, please", "It's delicious",
                            "The check, please", "Thank you for the meal"]),
    ("shopping", "Shopping", ["How much is it?", "Can I pay by card?", "Just looking, thank you", "Tax-free, please"]),
    ("hotel", "At the hotel", ["I have a reservation", "Could you keep our bags?", "What's the Wi-Fi password?"]),
    ("help", "Help", ["Help!", "Please call an ambulance", "Where is a hospital?", "I'm lost", "I have a food allergy"]),
]

WRITER = """You are writing the phrasebook in a family's private travel app for their trip: {places}. """ + "{house}" + """

First decide the languages a visitor needs there: the language people will actually speak to them (one per region; a trip through two countries may need two). Leave out English wherever English is the everyday language. For each language give: code (ISO 639-1, e.g. es, fr, it, de, pt, el, th, zh, vi), name in English, native (its own name in its own script: Español, Ελληνικά), countries (as listed above), and voice_style: how a native speaker from the place they are visiting speaks it, for a text-to-speech voice (e.g. "a native Spanish speaker from Mexico City, natural Mexican Spanish, warm and polite, speaking clearly and a little slowly, as if helping a visitor"; keep the words "speaking clearly and a little slowly").

Then, for each phrase below, write it in each language as a polite, natural local would say it to a visitor (the everyday form people really use, not a textbook one; the local variety: Mexican Spanish in Mexico, Brazilian Portuguese in Brazil): text in the language's own script with its proper punctuation; roman: for a non-Latin script, a simple romanization a traveller can read aloud; for a Latin script, a short English-speaker's pronunciation guide (e.g. "GRAH-syahs"); note: only when it matters (when to use it, a politeness nuance, what to point at), else ''. Replace a phrase that makes no sense there with the nearest useful one (and its English), e.g. no tax-free shopping. Exactness matters more than anything: a wrong phrase is worse than none.

The phrases (sections and English):
{phrases}"""


class PLang(BaseModel):
    code: str
    name: str
    native: str
    countries: list[str]
    voice_style: str


class PItem(BaseModel):
    lang: str
    text: str
    roman: str
    note: str


class PPhrase(BaseModel):
    section: str
    en: str
    items: list[PItem]


class PBook(BaseModel):
    languages: list[PLang]
    phrases: list[PPhrase]



def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("trip"); ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    t = Trip(a.trip)
    out_path = t.dir / "phrases.json"
    stops = list(dict.fromkeys(f"{h['city']}, {h.get('country') or ''}".strip(", ") for h in t.hotels))
    if not stops:
        sys.exit("trip.json has no hotels yet: the phrasebook is written for where you stay")
    if out_path.exists() and not a.force and input(f"{out_path} exists; replace it? [y/N] ").strip().lower() != "y":
        return
    party = len(t.data.get("people") or []) or 2
    words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}.get(party, str(party))
    listing = "\n".join(f"[{key}] {title}: " + " | ".join(p.replace("{party}", words) for p in phrases) for key, title, phrases in BASE)
    say(f"writing the phrasebook for {'; '.join(stops)}…")
    r = claude().messages.parse(model=MODEL, max_tokens=16000, output_config={"effort": "high"}, output_format=PBook,
                                messages=[{"role": "user", "content": WRITER.format(places="; ".join(stops), house=HOUSE, phrases=listing)}])
    pb = r.parsed_output or sys.exit(f"no phrasebook (stop_reason={r.stop_reason})")
    langs = {l.code.strip().lower(): l for l in pb.languages if l.code.strip().lower() not in ("en", "")}
    if not langs:
        say("English is spoken everywhere on this trip: no phrasebook needed (the app leaves the view out)")
        return
    book = {"languages": {c: {"name": l.name, "native": l.native, "countries": l.countries, "voice_style": l.voice_style.strip()} for c, l in langs.items()},
            "sections": []}
    for key, title, _ in BASE:
        phrases = []
        for ph in pb.phrases:
            if ph.section.strip("[] ").lower() != key:
                continue
            entry: dict = {"en": ph.en}
            for it in ph.items:
                c = it.lang.strip().lower()
                if c in langs and it.text.strip():
                    entry[c] = [it.text.strip(), it.roman.strip()] + ([it.note.strip()] if it.note.strip() else [])
            if len(entry) > 1:
                phrases.append(entry)
        if phrases:
            book["sections"].append({"key": key, "title": title, "phrases": phrases})
    out_path.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
    say(f"wrote {out_path}: {', '.join(l.name for l in langs.values())}, {sum(len(s['phrases']) for s in book['sections'])} phrases")


if __name__ == "__main__":
    main()
