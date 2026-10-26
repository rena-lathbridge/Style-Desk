# The Style Desk

A styling coach that teaches you what works on you, instead of just handing you
outfits.

Most styling apps answer *"what should I wear?"*. This one answers *"why does
that work on me?"* — it reads the outfits you keep coming back to, writes down
the principles behind them in language you can argue with, and then cites those
principles every time it builds or critiques an outfit. You leave with judgment,
not just an outfit.

Built for the closet that is already full. Most of us wear a fraction of what we
own and buy more anyway, because it is hard to say why one piece works and the
one beside it does not. Knowing that makes you wear more of what you have — and
buy the next thing more deliberately.

---

## Run it

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then put your key in it
uvicorn app.main:app --port 8000
```

Open <http://127.0.0.1:8000>.

### Keys

The app reads `.env` from **its own folder first, then one folder above**, so
this layout works without any configuration:

```
submissions/
├── .env               <-- your keys can live here
└── style-desk/        <-- this repo
    └── .env           <-- or here; this one wins
```

It needs **one** of:

| Variable | Model used | Notes |
|---|---|---|
| `PORTKEY_API_KEY` | `gpt-6-luna` | the course key |
| `OPENAI_API_KEY` | `gpt-6-luna` | your own key; override with `STYLE_MODEL` |

If both are set, `OPENAI_API_KEY` wins.

### Inspiration by link

Tab 01 takes uploads **or** image links, in any mix. You can also drag a pin
straight out of another browser tab onto the box and its URL is collected for
you.

**A link to a Pinterest board will not work, and the app says so rather than
failing quietly.** Two reasons, both checked rather than assumed:

- Pinterest's `robots.txt` is `User-agent: * / Disallow: /` — everything outside
  their allowlist is disallowed.
- It would not work anyway. A board page served to a non-browser contains **zero
  pins**; the grid is filled in afterwards by an authenticated request. Parsing
  the page's embedded JSON (`__PWS_DATA__`) turns up no pin images at all.

So instead: open the board, right-click a pin, **Copy image address**, and paste
those links. Direct `i.pinimg.com` image URLs serve fine without authentication.

### No photos handy?

Click **"Or load the demo closet"** on tab 02 for a 12-item wardrobe, so you can
try the stylist without uploading anything. You still need inspiration photos
for tab 01 — any few images of outfits will do.

---

## How it works

Four agents, each with one job. Only three of them ever see pixels.

```
  inspiration photos ──▶ ANALYST ──▶ Style Profile ──┐
                                     (P1…P7)         │
                                                     ├──▶ STYLIST ──▶ outfits
  garment photos ──▶ CATALOGER ──▶ Garment ──────────┤              + cited principles
                      │              (cached)        │
                      └── hash hit ──▶ free          │
                                                     │
  outfit photo ──────────────────────────────────────┴──▶ CRITIC ──▶ diagnosis
                                                                   + fixes
```

| Agent | Sees images | Produces | Why it is separate |
|---|---|---|---|
| **Cataloger** | yes | `Garment` | Runs once per item, then cached forever by image hash |
| **Analyst** | yes | `StyleProfile` | The teaching artifact; the user can edit it |
| **Stylist** | **no** | `OutfitSet` | Reads the catalog as text, so outfits are cheap |
| **Critic** | yes | `Critique` | Judges a real outfit against the user's own principles |

Every reply is a strict JSON schema (`app/schemas.py`), so nothing is spent on
prose that gets thrown away.

**The Style Profile is the product.** It is a numbered list of principles with
the evidence for each and a confidence flag. You can edit any of them — the
app saves your version and the stylist uses yours, not its own. That edit loop
is what separates this from a recommender.

---

## Cost

The app shows what it is spending, live, in the right-hand column: tokens in and
out, how many were cached, reasoning tokens, and dollars. Every number in the
report came from that panel.

Two things keep it down:

1. **Images are downscaled to 768px and stripped of metadata before they are
   ever sent.** Vision cost scales with pixels. This also drops EXIF, which is
   where phone photos carry GPS.
2. **Garments are cataloged once.** The result is keyed by the hash of the
   image bytes and kept on disk, so re-uploading the same jacket — by you or by
   the next person — costs nothing. The stylist then works from text alone.

Prices come from `PRICE_*` variables in `app/config.py` and can be overridden in
`.env`.

---

## Safety

Three defenses. None of them asks the model to police itself.

**Prompt injection carried inside an image.** Photos can have writing on them.
Every vision agent is told to copy any text it sees into an `embedded_text`
field and otherwise ignore it; `app/safety.py` then decides, with a regex,
whether that text was an instruction. The model reports, the code judges. When
something is caught it appears in the sidebar and never reaches the stylist.

**Bodies are off limits.** This app talks about clothes. A note like *"something
that hides my belly"* is refused **before** any model call, so it costs nothing,
and the refusal explains what to ask instead. The check is a regex, not a
judgement call, and it runs ahead of every other check so it behaves the same on
a fresh session as on a warm one.

**A URL box is an SSRF hole.** Whatever a user pastes, the server fetches, from
inside whatever network it is running on. So `app/fetching.py` resolves every
hostname and refuses any address that is private, loopback, link-local,
reserved, or multicast; allows `https` only; follows redirects by hand so each
hop is re-checked against a new host; requires an `image/*` content type; and
caps the body at 8 MB. A paste of `https://169.254.169.254/latest/meta-data/`
— the cloud metadata endpoint — is refused before a connection is opened.

**Spend.** Images are capped at 8 MB and 6 per profile, wardrobes at 40 items,
free text at 600 characters, and each session has a 400,000-token ceiling that
refuses the next call rather than truncating it.

Try them: upload a photo with "ignore all previous instructions" written on it,
or type a body-shape question into any of the free-text boxes.

---

## Layout

```
app/
  main.py      HTTP routes, guards applied before state checks
  agents.py    the four agents and their instructions
  schemas.py   structured outputs passed between them
  llm.py       the single model call, image downscaling, token accounting
  safety.py    the body-image, injection and spend defenses
  fetching.py  pasted-URL fetching, with the SSRF checks
  store.py     session state and the garment cache
  config.py    keys, model, limits, prices
web/           index.html, style.css, app.js — no build step
data/
  seed_wardrobe.json   the demo closet
  store.json           garment cache (gitignored, created on first run)
```

## Limits

- The garment cache keys on exact image bytes, so a re-crop of the same jacket
  is a miss.
- Sessions live in memory; restarting the server clears profiles and wardrobes,
  though the garment cache survives on disk.
- The Analyst works from whatever photos it is given. Six photos of one outfit
  produce a confident profile about one outfit.
- Pin links have to be copied one at a time. Reading a whole board would need
  Pinterest's official API and an approved OAuth app.
