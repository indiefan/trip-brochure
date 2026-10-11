#!/usr/bin/env python3
"""English copies of confirmation emails in other languages (the app shows both: English first, the original one tap away).

    python3 pipeline/translate.py mytrip/

For each email document in trip.json (kind "email", file .eml/.html/.txt) not yet marked, Claude decides the language;
if it is not English it writes docs/<id>.en.html and sets translation/language/language_en on the document. Names,
numbers, dates, prices and codes are kept exactly as written.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build import read_eml                                               # noqa: E402
from common import MODEL, Trip, claude, say                              # noqa: E402

PROMPT = """This is a confirmation email a family received for their trip (it may be forwarded, with an English \
forwarding header on top). Decide what language the email's main content (the confirmation itself, not the \
forwarding header) is written in.

If it is English, answer is_english=true and leave the rest empty.

Otherwise translate the whole confirmation into clear, natural English, and answer:
- language: the language's English name ("Japanese")
- native: its name in that language ("日本語")
- html: the translation as a simple HTML fragment (only h3, p, ul, li, table, tr, th, td, b, br), keeping the email's \
order and structure. Keep every name, number, date, time, price, address, phone number and confirmation code exactly \
as written (names of places may get an English gloss in brackets the first time, e.g. 強羅 (Gora)). Leave out the \
forwarding header, links' addresses, and boilerplate such as unsubscribe footers."""


class Translation(BaseModel):
    is_english: bool
    language: str
    native: str
    html: str


def strip_html(s: str) -> str:
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>|</p>|</div>|</tr>|</li>|</h\d>", "\n", s, flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]{2,}", " ", s)).strip()


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("trip"); ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    t = Trip(a.trip)
    client = None
    for did, d in (t.data.get("docs") or {}).items():
        if d.get("kind") != "email" or not d.get("file") or (d.get("language_en") is not None and not a.force):
            continue
        f = t.dir / d["file"]
        if f.suffix == ".eml":
            m = read_eml(f.read_bytes()); text = strip_html(m["html"]) or m["text"]; subject = d.get("subject") or m["subject"]
        else:
            raw = f.read_text(encoding="utf-8", errors="replace"); text = strip_html(raw) if f.suffix in (".html", ".htm") else raw; subject = d.get("subject", "")
        client = client or claude()
        say(f"  {did}: {subject[:60]}")
        r = client.messages.parse(model=MODEL, max_tokens=16000, output_config={"effort": "low"}, output_format=Translation,
                                  messages=[{"role": "user", "content": [{"type": "text", "text": f"The email:\n\nSubject: {subject}\n\n{text[:30000]}"}, {"type": "text", "text": PROMPT}]}])
        tr = r.parsed_output
        if tr is None:
            say("    no answer"); continue
        if tr.is_english:
            d["language_en"] = ""; say("    English"); continue
        out = t.dir / "docs" / f"{did}.en.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(tr.html.strip(), encoding="utf-8")
        d["translation"] = str(out.relative_to(t.dir)); d["language"] = tr.native.strip() or tr.language.strip(); d["language_en"] = tr.language.strip()
        say(f"    {tr.language} → English")
        t.save()
    say("translate: done")


if __name__ == "__main__":
    main()
