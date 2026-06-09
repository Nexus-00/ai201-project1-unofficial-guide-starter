"""
clean_docs.py — Normalize scraped documents into ChromaDB-ready text.

Two jobs:
  1. Convert the raw Reddit JSON dumps (scraped externally) into plain-text
     documents under documents/reddit_*/content.txt.
  2. Clean every documents/<source>/content.txt in place:
       - fix smart quotes / dashes / stray unicode
       - strip nav + UI boilerplate lines
       - merge the one-token-per-line fragments that listing pages produce
         (e.g. "$1,995" / "2" / "bds" / "750" / "sqft") back into single
         readable records, so sentence-aware chunking has real units to work on
       - drop residual junk and collapse blank lines

Re-runnable: cleaning is idempotent, so running it again on already-clean
files is a no-op. Run this after every scrape (including any manual Facebook
save) and before chunking/embedding.
"""

import json
import re
from pathlib import Path

DOCUMENTS_DIR = Path("documents")

# Raw Reddit JSON dumps in the project root -> (output source folder, kind).
REDDIT_JSON = {
    "reddit-seattlehousing-subreddit-2026-06-09T02-53-38-521Z.json": ("reddit_housing", "subreddit"),
    "reddit-SeattleWA-post-2026-06-09T02-52-41-489Z.json": ("reddit_pros_cons", "post"),
}

# Multi-page Derby SLU crawl (home + availability + per-unit detail pages).
DERBY_PAGES_FILE = Path("derby_pages.txt")
# Facebook group posts scraped to JSON (list of post objects with a "text" field).
FACEBOOK_JSON = Path("facebook.json")
# Structured Zillow listings (richer than the scraped HTML: specs + description
# + amenities + schools + walkability), scraped externally to JSON.
ZILLOW_JSON = Path("seattle_listings.json")

# Exact lines (case-insensitive, after stripping) that are pure nav/UI chrome.
JUNK_LINES = {
    "toggle navigation", "skip main navigation", "skip to main content",
    "submit search", "clear search text button", "all filters", "applied filters",
    "save search", "save", "saved", "more", "showcase", "button", "loading",
    "loading...", "previous photo", "next photo", "clear", "reset", "read more",
    "read more...", "sort by :", "popular", "channels", "all channels",
    "select all", "deselect all", "pay rent", "apply now", "view availability",
    "google map", "msn map", "osm map", "general map", "use map...",
    "please wait while loading the map...", "search titles only", "has image",
    "posted today", "show duplicates", "for sale", "price", "beds & baths",
    "property type", "filters", "details", "feed", "my company", "community",
    "salaries", "reviews", "layoffs", "jobs", "for business", "resources",
    "best of blind", "trending", "new", "details", "any", "studios", "rent",
    "search by commute time", "choose a destination", "commute", "baths", "beds",
    "show more channels", "why blind", "polls", "blog", "careers", "privacy",
    "terms", "support", "community guidelines", "faqs", "newsroom", "updates",
}

# Substrings that mark a line as boilerplate regardless of the rest.
JUNK_SUBSTRINGS = (
    "skip to", "cookie", "©", "all rights reserved", "sign up", "log in",
    "create account", "create new account", "forgot password",
)

# 2-letter US state codes that appear as standalone nav links on city-data.
STATE_CODES = {
    "ak", "al", "ar", "az", "ca", "co", "ct", "dc", "de", "fl", "ga", "hi",
    "ia", "id", "il", "in", "ks", "ky", "la", "ma", "md", "me", "mi", "mn",
    "mo", "ms", "mt", "nc", "nd", "ne", "nh", "nj", "nm", "nv", "ny", "oh",
    "ok", "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "va", "vt", "wa",
    "wi", "wv", "wy",
}

# City-data dumps huge HMDA mortgage/loan-statistics tables that survive as
# number-only records and add no value for apartment-living questions. Drop a
# record if it carries one of these table markers or is almost entirely numeric.
LOAN_TABLE_MARKERS = (
    "loans originated", "applications withdrawn", "applications approved",
    "applications denied", "files closed for incompleteness", "preapprovals",
    "aggregated statistics for year", "average value, number",
    "home purchase loans", "non-occupant loans", "fha, fsa", "loans on dwellings",
)
NUMERIC_TOKEN_RE = re.compile(r"^[#$]?[\d,.\s%kKmM/()\-]+$")

# A line is a listing fragment if it is short and not a real sentence/label.
FRAGMENT_MAX_LEN = 55
PRICE_RE = re.compile(r"^\$[\d,]")
SENTENCE_END_RE = re.compile(r"[.!?][\"')\]]?$")
# A token counts as "filler" if it is purely numeric/symbolic or <= 2 letters.
FILLER_TOKEN_RE = re.compile(r"^[\$\d.,kKmM\s/\-]+$")

UNICODE_FIXES = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "…": "...", " ": " ",
    "​": "", "﻿": "",
}


def normalize(text: str) -> str:
    for bad, good in UNICODE_FIXES.items():
        text = text.replace(bad, good)
    return text


def is_junk(line: str) -> bool:
    low = line.lower()
    if low in JUNK_LINES or low in STATE_CODES:
        return True
    if any(sub in low for sub in JUNK_SUBSTRINGS):
        return True
    # Pure symbols / empty-ish (no letters and no digits).
    if not re.search(r"[a-z0-9]", low):
        return True
    return False


def is_option_junk(record: str) -> bool:
    """True for dropdown / calendar rows like '400, 500, 600, ...' or '7, 8, 9, ...'.

    Kept records (e.g. Zillow listings) have addresses and words, so their share
    of purely numeric/short tokens stays well below the threshold.
    """
    items = [i.strip() for i in record.split(", ") if i.strip()]
    if len(items) < 6:
        return False
    filler = sum(1 for it in items if FILLER_TOKEN_RE.match(it) or len(it) <= 2)
    return filler / len(items) >= 0.8


def is_loan_table_junk(record: str) -> bool:
    """True for HMDA mortgage-table rows: marker phrases or near-all-numeric.

    Real listings/prose keep words (addresses, neighborhoods, labels), so their
    numeric share stays below the threshold and they survive.
    """
    low = record.lower()
    if any(m in low for m in LOAN_TABLE_MARKERS):
        return True
    tokens = [t.strip() for t in record.split(",") if t.strip()]
    if len(tokens) >= 3:
        numeric = sum(1 for t in tokens if NUMERIC_TOKEN_RE.match(t))
        if numeric / len(tokens) >= 0.8:
            return True
    return False


def is_fragment(line: str) -> bool:
    """Short line that is a listing field, not a complete sentence."""
    if len(line) > FRAGMENT_MAX_LEN:
        return False
    if SENTENCE_END_RE.search(line):
        return False
    return True


def _clean_once(raw: str) -> str:
    raw = normalize(raw)
    lines = [ln.strip() for ln in raw.splitlines()]
    lines = [ln for ln in lines if ln and not is_junk(ln)]

    # Merge consecutive fragment lines into one record. Start a new record when
    # a price line appears (each listing tends to begin with its price) or after
    # a completed sentence/long line.
    records: list[str] = []
    buffer: list[str] = []

    def flush():
        if buffer:
            records.append(", ".join(buffer))
            buffer.clear()

    for line in lines:
        if is_fragment(line):
            if PRICE_RE.match(line) and buffer:
                flush()  # price starts a fresh listing
            buffer.append(line)
            if len(buffer) >= 14:  # avoid runaway merges
                flush()
        else:
            flush()
            records.append(line)

    flush()

    # Drop residual records that carry no real information (too short and no digit)
    # and dropdown/calendar option lists.
    cleaned = [
        r for r in records
        if (len(r) >= 15 or re.search(r"\d", r))
        and not is_option_junk(r)
        and not is_loan_table_junk(r)
    ]

    # Collapse exact consecutive duplicates.
    deduped: list[str] = []
    for r in cleaned:
        if not deduped or deduped[-1] != r:
            deduped.append(r)

    return "\n".join(deduped) + "\n"


def clean_text(raw: str, max_passes: int = 10) -> str:
    """Apply _clean_once repeatedly until the output stops changing.

    A single pass isn't idempotent: it joins short fragments into comma-records,
    and a second pass can re-group those records slightly differently. Iterating
    to a fixed point makes cleaning deterministic, so clean_text(x) always equals
    clean_text(clean_text(x)) — one clean_docs run produces the same corpus as N.
    """
    text = raw
    for _ in range(max_passes):
        nxt = _clean_once(text)
        if nxt == text:
            return text
        text = nxt
    return text


# ---------- Reddit JSON -> text ----------

def _post_block(post: dict) -> str:
    title = post.get("title", "").strip()
    text = post.get("text", "").strip()
    score = post.get("score")
    head = f"# {title}" if title else "# (untitled post)"
    if score is not None:
        head += f"  (score {score})"
    return f"{head}\n{text}".strip()


def convert_reddit() -> None:
    for fname, (source, kind) in REDDIT_JSON.items():
        path = Path(fname)
        if not path.exists():
            print(f"[reddit] SKIP {fname}: not found in project root.")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        parts: list[str] = []

        if kind == "subreddit":
            for post in data.get("posts", []):
                parts.append(_post_block(post))
        elif kind == "post":
            parts.append(_post_block(data["post"]))
            comments = data.get("comments", [])
            if comments:
                parts.append("## Comments")
                for c in comments:
                    body = (c.get("text") or "").strip()
                    if body:
                        parts.append(f"- {body}")

        out_dir = DOCUMENTS_DIR / source
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "content.txt"
        out_file.write_text("\n\n".join(parts), encoding="utf-8")
        print(f"[reddit] {fname} -> {out_file} ({len(parts)} blocks)")


def convert_derby_pages() -> None:
    """Turn the multi-page Derby crawl into documents/derby_slu/content.txt.

    The dump is a series of '====' separated blocks, each with URL: / TITLE: /
    STATUS: headers, a '----' divider, then the page body. We keep each page's
    title (unit detail titles carry the address + unit number) and its body.
    """
    if not DERBY_PAGES_FILE.exists():
        print(f"[derby] SKIP {DERBY_PAGES_FILE}: not found in project root.")
        return
    raw = DERBY_PAGES_FILE.read_text(encoding="utf-8")
    parts: list[str] = []
    for block in re.split(r"^={5,}$", raw, flags=re.MULTILINE):
        title = None
        body: list[str] = []
        for line in block.splitlines():
            s = line.strip()
            if s.startswith(("URL:", "STATUS:")):
                continue
            if s.startswith("TITLE:"):
                title = s[len("TITLE:"):].strip()
                continue
            if s and set(s) == {"-"}:  # header/body divider
                continue
            body.append(line)
        text = "\n".join(body).strip()
        if title:
            parts.append(f"# {title}")
        if text:
            parts.append(text)

    out_file = DOCUMENTS_DIR / "derby_slu" / "content.txt"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("\n\n".join(parts), encoding="utf-8")
    print(f"[derby] {DERBY_PAGES_FILE} -> {out_file}")


def convert_facebook() -> None:
    """Turn the Facebook group JSON into documents/facebook/content.txt."""
    if not FACEBOOK_JSON.exists():
        print(f"[facebook] SKIP {FACEBOOK_JSON}: not found in project root.")
        return
    posts = json.loads(FACEBOOK_JSON.read_text(encoding="utf-8"))
    blocks: list[str] = []
    for post in posts:
        text = (post.get("text") or "").strip()
        if not text:
            continue
        author = (post.get("user") or {}).get("name", "").strip()
        head = f"# Post by {author}" if author else "# Post"
        blocks.append(f"{head}\n{text}")

    out_file = DOCUMENTS_DIR / "facebook" / "content.txt"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("\n\n".join(blocks), encoding="utf-8")
    print(f"[facebook] {FACEBOOK_JSON} -> {out_file} ({len(blocks)} posts)")


def _zillow_listing_block(listing: dict) -> str:
    """Render one structured Zillow listing as period-terminated sentences.

    Each line is a complete sentence (words + trailing period) so the downstream
    clean_text pass treats it as a finished sentence instead of a mergeable
    fragment, and sentence-aware chunking keeps each fact intact.
    """
    addr = (listing.get("address") or "").strip()
    home = (listing.get("homeType") or "home").replace("_", " ").lower()
    beds, baths, sqft = listing.get("beds"), listing.get("baths"), listing.get("sqft")
    price, pps = listing.get("price"), listing.get("pricePerSqft")
    status = (listing.get("status") or "").replace("_", " ").lower()
    days = listing.get("daysOnZillow")
    year = listing.get("yearBuilt")

    lines: list[str] = []

    spec = f"{beds}-bed, {baths}-bath {home} at {addr}"
    if price:
        spec += f" listed for ${price:,}"
        if pps:
            spec += f" (${pps}/sqft)"
    if sqft:
        spec += f", {sqft:,} sqft"
    if year:
        spec += f", built {year}"
    if status:
        spec += f", {status}"
    if days is not None:
        spec += f", {days} days on Zillow"
    lines.append(spec.strip() + ".")

    ga = listing.get("gettingAround") or {}
    parts = []
    for key, label in (("walk", "Walk"), ("transit", "Transit"), ("bike", "Bike")):
        info = ga.get(key) or {}
        if info.get("score") is not None:
            parts.append(f"{label} score {info['score']} ({info.get('label', '').strip()})")
    if parts:
        lines.append("Getting around: " + "; ".join(parts) + ".")

    schools = listing.get("schools") or []
    if schools:
        named = [
            f"{s.get('name', '').strip()} (rating {s.get('rating', 'NA')}, "
            f"grades {s.get('grades', 'NA')}, {s.get('distance', 'NA')})"
            for s in schools if (s.get("name") or "").strip()
        ]
        if named:
            lines.append("Nearby schools: " + "; ".join(named) + ".")

    amen = listing.get("amenities") or {}
    pf = amen.get("parkingFeatures") or []
    if pf or amen.get("parkingCapacity") is not None:
        pieces = []
        if pf:
            pieces.append(", ".join(pf).lower())
        if amen.get("hasGarage") and not any("garage" in p for p in pieces):
            pieces.append("garage")
        cap = amen.get("parkingCapacity")
        if cap is not None:
            pieces.append(f"capacity {cap}")
        if pieces:
            lines.append("Parking: " + "; ".join(pieces) + ".")

    desc = (listing.get("description") or "").strip()
    if desc:
        lines.append(desc)

    return "\n".join(lines)


def convert_zillow() -> None:
    """Turn the structured Zillow JSON into documents/zillow/content.txt."""
    if not ZILLOW_JSON.exists():
        print(f"[zillow] SKIP {ZILLOW_JSON}: not found in project root.")
        return
    data = json.loads(ZILLOW_JSON.read_text(encoding="utf-8"))
    listings = data.get("listings", [])
    blocks = [_zillow_listing_block(l) for l in listings]
    blocks = [b for b in blocks if b.strip()]

    out_file = DOCUMENTS_DIR / "zillow" / "content.txt"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("\n\n".join(blocks), encoding="utf-8")
    print(f"[zillow] {ZILLOW_JSON} -> {out_file} ({len(blocks)} listings)")


def main():
    convert_reddit()
    convert_derby_pages()
    convert_facebook()
    convert_zillow()
    for content_file in sorted(DOCUMENTS_DIR.glob("*/content.txt")):
        raw = content_file.read_text(encoding="utf-8")
        cleaned = clean_text(raw)
        content_file.write_text(cleaned, encoding="utf-8")
        print(f"[clean] {content_file.parent.name}: "
              f"{len(raw):,} -> {len(cleaned):,} chars")


if __name__ == "__main__":
    main()
