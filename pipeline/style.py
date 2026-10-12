"""The house style every brochure is held to: one brief, given to each of Claude's jobs in this pipeline.

The designer (design.py: the app's name, icon, colours, cover words), the copywriter (brochure_copy.py), the place picker
(places.py) and the phrasebook writer (phrases.py) all read the same expectations, so whatever the trip, and however
little of it you write by hand, the result is as considered as the sample. Edit it to change the house's taste.
"""

HOUSE = """The family's trip apps are held to the standard of a beautifully printed travel brochure and a best-in-class \
iPhone app (think Aman, Condé Nast Traveler, Monocle; Apple's own apps): high-end, beautiful, delightful, impeccable. \
Every detail is considered; nothing generic, clip-art, stock or template-like.
- Restraint: paper and ink, one accent colour, and the photographs carry the colour. Generous margins: text and card \
edges never touch the screen's edge; only photographs bleed. Resist adding things; take away what does not earn its place.
- Type: a refined display serif (Instrument Serif) for titles, the system font for reading; a destination's own script \
in a fine face of its own (a mincho for Japanese, a myeongjo for Korean); never two typefaces inside one word.
- Voice: warm and precise, never gushing; present tense; no exclamation marks; facts only from the sources, never \
invented.
- Detail: consistent spacing and alignment, balanced line breaks, real typography (curly apostrophes, en dashes for \
ranges), names spelled as locals spell them, contrast that reads in light and dark mode, at arm's length, in sunlight.
- Delight: small, purposeful touches (the route dock's little vehicle, a seal in the local script), never decoration \
for its own sake.
What every trip's app must do (keep it all working, whatever the trip): work fully offline; open on today's event \
during the trip (times in each place's own time zone); Directions to the exact place (Google Maps, Apple Maps, Naver \
in Korea) and a card in the local script to show a driver; every confirmation one tap away (the original email, its \
PDF, an English translation); weather at a glance with packing notes; a phrasebook with offline audio wherever \
English is not the language; the route dock; updates over the air; large tap targets, one-handed use."""
