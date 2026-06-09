"""
retrieve_docs.py — Document ingestion for the Seattle apartments RAG pipeline.

Three acquisition strategies, chosen per source after testing what each site allows:

  1. requests + BeautifulSoup      — plain static pages (city-data).
  2. Playwright + stealth (headed) — JS-rendered / bot-walled sites (Zillow, etc.).
     PerimeterX/Akamai detect headless Chromium, so we run a *real* (headed)
     browser with the stealth plugin to pass the bot challenge.
  3. PRAW (official Reddit API)    — Reddit hard-blocks the public .json endpoint
     and the headless HTML page (403 / JS challenge), so we use OAuth instead.

Every fetch is validated (see looks_blocked) so bot-wall / login pages are
reported and skipped instead of being saved as poisoned chunks.

Setup:
    uv add requests beautifulsoup4 playwright playwright-stealth praw
    playwright install chromium
    # Reddit: create a free "script" app at https://www.reddit.com/prefs/apps,
    # then fill REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET / REDDIT_USER_AGENT in .env
"""

import os
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

DOCUMENTS_DIR = Path("documents")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Static pages that respond to a plain HTTP GET.
REQUESTS_SOURCES = {
    "city_data": "https://www.city-data.com/city/Seattle-Washington.html",
    "wikivoyage": "https://en.wikivoyage.org/wiki/Seattle",
}

# JS-rendered or bot-protected sites — fetched with a headed stealth browser.
BROWSER_SOURCES = {
    "zillow": "https://www.zillow.com/seattle-wa/",
    "derby_slu": "https://www.liveatderbyslu.com/",
    "apartments_com": "https://www.apartments.com/seattle-wa/",
    "craigslist": "https://seattle.craigslist.org/search/apa",
    "facebook": "https://www.facebook.com/groups/150655681825/",
    "teamblind": "https://www.teamblind.com/",
}

# Reddit sources go through PRAW (the .json endpoint is blocked). Each entry is
# either a subreddit name or a full submission URL.
REDDIT_SUBREDDITS = {
    "reddit_housing": "seattlehousing",
}
REDDIT_POSTS = {
    "reddit_pros_cons": (
        "https://www.reddit.com/r/SeattleWA/comments/188kibg/"
        "the_pros_and_cons_of_living_in_seattle/"
    ),
}

# Phrases that mean we got a bot wall / login page rather than real content.
BLOCK_PHRASES = (
    "access to this page has been denied",
    "access denied",
    "you don't have permission to access",
    "are you a robot",
    "checking your browser",
    "enable javascript and cookies",
    "attention required",
    "just a moment",
    "log into facebook",
)
MIN_CONTENT_CHARS = 600


def save_text(source_name: str, text: str) -> Path:
    out_dir = DOCUMENTS_DIR / source_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "content.txt"
    out_file.write_text(text, encoding="utf-8")
    print(f"  Saved {len(text):,} chars -> {out_file}")
    return out_file


def looks_blocked(title: str, text: str) -> str | None:
    """Return a reason string if the page looks like a block/login wall, else None."""
    haystack = f"{title}\n{text}".lower()
    for phrase in BLOCK_PHRASES:
        if phrase in haystack:
            return f"matched block phrase: {phrase!r}"
    if len(text.strip()) < MIN_CONTENT_CHARS:
        return f"only {len(text.strip())} chars of text (< {MIN_CONTENT_CHARS})"
    return None


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


def fetch_with_requests(source_name: str, url: str) -> None:
    print(f"[requests] {source_name} ...")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  ERROR: {e}")
        return
    text = html_to_text(resp.text)
    reason = looks_blocked("", text)
    if reason:
        print(f"  BLOCKED ({reason}) — not saving. Consider the browser path or a manual save.")
        return
    save_text(source_name, text)
    time.sleep(1)


def fetch_browser_sources(sources: dict[str, str]) -> None:
    """Fetch JS/bot-walled sites with one headed stealth browser session."""
    pending = {n: u for n, u in sources.items()
               if not (DOCUMENTS_DIR / n / "content.txt").exists()}
    for n in sources:
        if n not in pending:
            print(f"[browser] SKIP {n}: content.txt already present.")
    if not pending:
        return

    try:
        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth
    except ImportError:
        print("  Playwright/stealth not installed. Run:")
        print("    uv add playwright playwright-stealth && playwright install chromium")
        return

    # headless=False is deliberate: PerimeterX/Akamai flag headless Chromium.
    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(headless=False)
        # Do NOT override user_agent here: the stealth plugin sets a coordinated
        # fingerprint (UA + sec-ch-ua client hints + navigator.platform). Supplying
        # our own UA desyncs those and gets us flagged by PerimeterX/Akamai.
        context = browser.new_context(
            locale="en-US",
            viewport={"width": 1366, "height": 900},
        )
        for name, url in pending.items():
            print(f"[browser] {name} ...")
            page = context.new_page()
            try:
                page.goto(url, timeout=45_000, wait_until="domcontentloaded")
                page.wait_for_timeout(4000)  # let client-side content render
                title = page.title()
                text = html_to_text(page.content())
            except Exception as e:
                print(f"  ERROR: {type(e).__name__}: {str(e)[:120]}")
                page.close()
                continue
            page.close()

            reason = looks_blocked(title, text)
            if reason:
                print(f"  BLOCKED ({reason}) — not saving. Manual save to "
                      f"documents/{name}/content.txt will be picked up next run.")
                continue
            save_text(name, text)
            time.sleep(2)
        browser.close()


def _format_submission(sub, include_comments: int = 10) -> str:
    parts = [f"# {sub.title}", ""]
    if getattr(sub, "selftext", ""):
        parts.append(sub.selftext)
    if include_comments:
        sub.comments.replace_more(limit=0)
        parts.append("\n## Comments")
        for c in sub.comments[:include_comments]:
            body = getattr(c, "body", "").strip()
            if body:
                parts.append(f"- {body}")
    return "\n".join(parts)


def fetch_reddit() -> None:
    if not REDDIT_SUBREDDITS and not REDDIT_POSTS:
        return
    cid = os.getenv("REDDIT_CLIENT_ID")
    secret = os.getenv("REDDIT_CLIENT_SECRET")
    ua = os.getenv("REDDIT_USER_AGENT")
    if not cid or cid == "your_client_id_here" or not secret:
        print("[reddit] SKIP: set REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET in .env "
              "(create a free 'script' app at https://www.reddit.com/prefs/apps).")
        return

    import praw

    reddit = praw.Reddit(
        client_id=cid,
        client_secret=secret,
        user_agent=ua or "seattle-rag-research/0.1",
    )
    reddit.read_only = True

    for name, sr in REDDIT_SUBREDDITS.items():
        print(f"[reddit] r/{sr} ...")
        try:
            blocks = [_format_submission(s, include_comments=5)
                      for s in reddit.subreddit(sr).hot(limit=25)]
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {str(e)[:120]}")
            continue
        save_text(name, "\n\n---\n\n".join(blocks))

    for name, post_url in REDDIT_POSTS.items():
        print(f"[reddit] post {name} ...")
        try:
            text = _format_submission(reddit.submission(url=post_url), include_comments=30)
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {str(e)[:120]}")
            continue
        save_text(name, text)


def main():
    DOCUMENTS_DIR.mkdir(exist_ok=True)
    for name, url in REQUESTS_SOURCES.items():
        fetch_with_requests(name, url)
    fetch_browser_sources(BROWSER_SOURCES)
    fetch_reddit()


if __name__ == "__main__":
    main()
