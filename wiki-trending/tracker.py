#!/usr/bin/env python3
"""Wikipedia Trending Articles tracker for TRMNL e-ink display.

Fetches yesterday's top Wikipedia pages, identifies articles trending
well above their 7-day average, and pushes the results to a TRMNL
e-ink display via webhook.
"""
import asyncio
import json
import logging
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import aiohttp
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("wiki-trending")

# Configuration
PAGES_TO_CHECK = 200
TRENDING_THRESHOLD = 3.0
DISPLAY_COUNT = 6
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "14400"))  # 4 hours
TRMNL_WEBHOOK_UUID = os.getenv("TRMNL_WEBHOOK_UUID", "")
TRMNL_API_URL = "https://trmnl.com/api/custom_plugins"
DATA_FILE = os.getenv("DATA_FILE", "/data/wiki_state.json")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
USER_AGENT = "TRMNL Wikipedia Trending Display (github.com/KurtMoran/TRMNL-Items)"

# Pages to skip (utility/meta/adult pages)
SKIP_PREFIXES = (
    "Special:", "Wikipedia:", "Portal:", "Help:", "Template:",
    "Category:", "File:", "Talk:", "User:", "Draft:",
)
SKIP_EXACT = {
    "Main_Page", "-", "Search", "Undefined",
    "XHamster", "Pornhub", "XNXX", "XXX",
}


def should_skip(title):
    if title in SKIP_EXACT:
        return True
    for prefix in SKIP_PREFIXES:
        if title.startswith(prefix):
            return True
    return False


def format_views(n):
    if n >= 1_000_000:
        return "{:.1f}M".format(n / 1_000_000)
    if n >= 1_000:
        return "{:.0f}K".format(n / 1_000)
    return str(n)


def format_mult(m):
    """Return (number, suffix) for split badge rendering."""
    if m >= 1000:
        return {
            "num": "{:.1f}".format(m / 1000),
            "suf": "Kx",
        }
    if m >= 10:
        return {
            "num": "{:.0f}".format(m),
            "suf": "x",
        }
    return {
        "num": "{:.1f}".format(m),
        "suf": "x",
    }


def load_state():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            log.warning("Could not load state file, starting fresh")
    return {"last_fetch": None, "articles": []}


def save_state(state):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(state, f)


async def get_article_views(session, article, days_back=7):
    end = datetime.now(timezone.utc) - timedelta(days=1)
    start = end - timedelta(days=days_back)
    url = (
        "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
        "en.wikipedia/all-access/user/{}/daily/{}/{}"
    ).format(article, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT}) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("items", [])
    except Exception as e:
        log.debug("Views fetch failed for %s: %s", article, e)
    return []


async def get_description(session, article):
    url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query", "format": "json", "prop": "extracts",
        "exintro": "1", "explaintext": "1", "exsentences": "2",
        "titles": article,
    }
    try:
        async with session.get(url, params=params, headers={"User-Agent": USER_AGENT}) as resp:
            data = await resp.json()
            page = next(iter(data["query"]["pages"].values()))
            if "extract" in page:
                return page["extract"].strip()
    except Exception as e:
        log.debug("Description fetch failed for %s: %s", article, e)
    return ""


async def get_news_headline(session, article):
    """Fetch the most recent news headline from Google News RSS."""
    search_term = article.replace("_", " ")
    url = (
        "https://news.google.com/rss/search"
        "?q={}&hl=en-US&gl=US&ceid=US:en"
    ).format(search_term)
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT}) as resp:
            if resp.status == 200:
                text = await resp.text()
                root = ET.fromstring(text)
                item = root.find(".//item")
                if item is not None:
                    title = item.find("title")
                    if title is not None and title.text:
                        return title.text.strip()
    except Exception as e:
        log.debug("News fetch failed for %s: %s", article, e)
    return ""


async def process_article(session, article_name, current_views):
    views_task = get_article_views(session, article_name)
    desc_task = get_description(session, article_name)
    news_task = get_news_headline(session, article_name)
    historical, description, headline = await asyncio.gather(
        views_task, desc_task, news_task,
    )

    if not historical or len(historical) <= 1:
        return None

    daily = [day["views"] for day in historical]
    avg = sum(daily[:-1]) / (len(daily) - 1)
    if avg == 0:
        return None

    multiplier = current_views / avg
    if multiplier >= TRENDING_THRESHOLD:
        return {
            "article": article_name,
            "views": current_views,
            "avg": int(avg),
            "mult": round(multiplier, 1),
            "desc": headline if headline else description,
        }
    return None


async def fetch_trending():
    date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y/%m/%d")
    url = (
        "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/"
        "en.wikipedia/all-access/{}"
    ).format(date)

    log.info("Fetching top pages for %s", date)

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers={"User-Agent": USER_AGENT}) as resp:
            if resp.status != 200:
                log.error("Top pages fetch failed: %d", resp.status)
                return []
            data = await resp.json()

        top_pages = data["items"][0]["articles"]
        candidates = [p for p in top_pages if not should_skip(p["article"])][:PAGES_TO_CHECK]

        log.info("Checking %d candidates for trending", len(candidates))

        trending = []
        batch_size = 10
        for i in range(0, len(candidates), batch_size):
            batch = candidates[i:i + batch_size]
            tasks = [process_article(session, p["article"], p["views"]) for p in batch]
            results = await asyncio.gather(*tasks)
            for r in results:
                if r:
                    trending.append(r)
            log.info(
                "Progress: %d/%d checked, %d trending so far",
                min(i + batch_size, len(candidates)), len(candidates), len(trending),
            )

        trending.sort(key=lambda x: -x["mult"])
        return trending


async def get_trending_reason(session, article_name, mult):
    """Ask Gemini with Google Search grounding why an article is trending."""
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        "models/gemini-2.5-flash:generateContent?key={}"
    ).format(GEMINI_API_KEY)
    prompt = (
        "The Wikipedia article '{}' is getting {}x its normal daily traffic. "
        "In one short sentence (under 120 characters), explain why it's trending right now. "
        "Be specific about the event or news. "
        "Don't start with 'The Wikipedia article'. Just state what happened."
    ).format(article_name.replace("_", " "), mult)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"maxOutputTokens": 80, "temperature": 0.2},
    }
    try:
        async with session.post(url, json=payload) as resp:
            if resp.status == 200:
                data = await resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    for part in parts:
                        if "text" in part:
                            return part["text"].strip()
            else:
                body = await resp.text()
                log.warning("Gemini returned %d for %s: %s", resp.status, article_name, body[:200])
    except Exception as e:
        log.debug("Gemini fetch failed for %s: %s", article_name, e)
    return ""


async def enrich_with_reasons(trending):
    """Replace descriptions with AI-generated trending reasons for top articles."""
    top = trending[:DISPLAY_COUNT]
    async with aiohttp.ClientSession() as session:
        for article in top:
            reason = await get_trending_reason(session, article["article"], article["mult"])
            if reason:
                log.info("Gemini: %s -> %s", article["article"], reason)
                article["desc"] = reason
            await asyncio.sleep(5)


def build_trmnl_payload(trending):
    now = datetime.now()
    display = trending[:DISPLAY_COUNT]

    articles = []
    for a in display:
        desc = a["desc"]
        if len(desc) > 200:
            desc = desc[:197] + "..."
        name = a["article"].replace("_", " ")
        if len(name) > 30:
            name = name[:27] + "..."
        articles.append({
            "n": name,
            "v": format_views(a["views"]),
            "m": format_mult(a["mult"]),
            "d": desc,
        })

    return {"merge_variables": {
        "date": now.strftime("%A, %B %-d"),
        "updated": now.strftime("%-I:%M %p"),
        "articles": articles,
        "count": len(trending),
    }}


def push_to_trmnl(payload):
    if not TRMNL_WEBHOOK_UUID:
        return
    url = "{}/{}".format(TRMNL_API_URL, TRMNL_WEBHOOK_UUID)
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            log.info("TRMNL updated successfully")
        elif resp.status_code == 429:
            log.warning("TRMNL rate limited, will retry next cycle")
        else:
            log.warning("TRMNL push returned %d: %s", resp.status_code, resp.text)
    except Exception as e:
        log.error("TRMNL push failed: %s", e)


def main():
    log.info("Starting Wikipedia Trending Tracker")
    log.info("Checking top %d pages, threshold %.1fx", PAGES_TO_CHECK, TRENDING_THRESHOLD)
    log.info("Polling every %ds", POLL_INTERVAL_SEC)
    if TRMNL_WEBHOOK_UUID:
        log.info("TRMNL webhook configured")
    else:
        log.info("No TRMNL webhook - console only mode")
    if GEMINI_API_KEY:
        log.info("Gemini API configured - AI descriptions enabled")
    else:
        log.info("No Gemini API key - using news headlines / Wikipedia descriptions")

    while True:
        try:
            trending = asyncio.run(fetch_trending())
            log.info("Found %d trending articles", len(trending))

            if trending:
                if GEMINI_API_KEY:
                    asyncio.run(enrich_with_reasons(trending))
                for i, a in enumerate(trending[:10], 1):
                    log.info(
                        "  #%d: %s (%.1fx, %s views) — %s",
                        i, a["article"], a["mult"], format_views(a["views"]),
                        a["desc"][:80],
                    )

            state = {"last_fetch": datetime.now().isoformat(), "articles": trending}
            save_state(state)

            payload = build_trmnl_payload(trending)
            log.info("Payload size: %d bytes", len(json.dumps(payload)))
            push_to_trmnl(payload)
        except Exception as e:
            log.error("Fetch cycle failed: %s", e)

        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()
