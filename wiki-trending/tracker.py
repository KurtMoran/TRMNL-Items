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
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import aiohttp
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("wiki-trending")

# Configuration
PAGES_TO_CHECK = 500
TRENDING_THRESHOLD = 3.0
DISPLAY_COUNT = 5
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "21600"))  # 6 hours
TRMNL_WEBHOOK_UUID = os.getenv("TRMNL_WEBHOOK_UUID", "")
TRMNL_API_URL = "https://trmnl.com/api/custom_plugins"
DATA_FILE = os.getenv("DATA_FILE", "/data/wiki_state.json")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Wikimedia Analytics API requires identifying User-Agent in this format:
# https://wikimedia.org/api/rest_v1/ (Access policy → Client identification)
USER_AGENT = (
    "TRMNL-Wiki-Trending/1.0 "
    "(https://github.com/KurtMoran/TRMNL-Items) "
    "python-aiohttp"
)

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
            # Per Wikimedia docs, 404 means "zero views or data not loaded";
            # not an error worth alerting on.
            if resp.status == 404:
                return []
            log.warning("Views fetch returned HTTP %d for %s", resp.status, article)
    except Exception as e:
        log.warning("Views fetch exception for %s: %s", article, e)
    return []


async def get_access_breakdown(session, article):
    """Get desktop vs mobile breakdown for yesterday's views."""
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    date_str = yesterday.strftime("%Y%m%d")
    counts = {}
    for access in ("desktop", "mobile-web", "mobile-app"):
        url = (
            "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
            "en.wikipedia/{}/user/{}/daily/{}/{}"
        ).format(access, article, date_str, date_str)
        try:
            async with session.get(url, headers={"User-Agent": USER_AGENT}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("items", [])
                    if items:
                        counts[access] = items[0].get("views", 0)
        except Exception:
            pass
    total = sum(counts.values())
    if total == 0:
        return ""
    desktop = counts.get("desktop", 0)
    mobile = counts.get("mobile-web", 0) + counts.get("mobile-app", 0)
    desktop_pct = round(100 * desktop / total)
    mobile_pct = round(100 * mobile / total)
    return "Traffic split: {}% desktop, {}% mobile".format(desktop_pct, mobile_pct)


async def get_hourly_pattern(session, article):
    """Get yesterday's hourly pageview pattern to identify when the spike happened."""
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    date_str = yesterday.strftime("%Y%m%d")
    url = (
        "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
        "en.wikipedia/all-access/user/{}/hourly/{}/{}"
    ).format(article, date_str + "00", date_str + "23")
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT}) as resp:
            if resp.status == 200:
                data = await resp.json()
                items = data.get("items", [])
                if not items:
                    return ""
                hourly = [(it.get("timestamp", "")[-4:-2], it.get("views", 0)) for it in items]
                if not hourly:
                    return ""
                peak_hour, peak_views = max(hourly, key=lambda x: x[1])
                total = sum(v for _, v in hourly)
                # Format as compact summary
                parts = ["Hourly views (UTC): " + ", ".join(
                    "{}h:{}".format(h, format_views(v)) for h, v in hourly
                )]
                parts.append("Peak hour: {}:00 UTC ({} views, {:.0f}% of daily total)".format(
                    peak_hour, format_views(peak_views),
                    100 * peak_views / total if total else 0,
                ))
                return "\n".join(parts)
    except Exception as e:
        log.debug("Hourly pattern fetch failed for %s: %s", article, e)
    return ""


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


async def get_wiki_featured(session):
    """Fetch Wikipedia's main page featured content for yesterday (UTC)."""
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    url = "https://api.wikimedia.org/feed/v1/wikipedia/en/featured/{}/{:02d}/{:02d}".format(
        yesterday.year, yesterday.month, yesterday.day,
    )
    featured = {"tfa": "", "news": [], "onthisday": [], "dyk": []}
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT}) as resp:
            if resp.status == 200:
                data = await resp.json()
                # Today's Featured Article
                tfa = data.get("tfa", {})
                if tfa:
                    featured["tfa"] = tfa.get("normalizedtitle", "")
                # In the News
                for item in data.get("news", []):
                    for link in item.get("links", []):
                        featured["news"].append(link.get("normalizedtitle", ""))
                # On This Day
                for item in data.get("onthisday", []):
                    for page in item.get("pages", []):
                        featured["onthisday"].append(page.get("normalizedtitle", ""))
    except Exception as e:
        log.debug("Featured content fetch failed: %s", e)
    return featured


def check_wiki_feature(article_name, featured):
    """Check if an article was featured on Wikipedia's main page."""
    name = article_name.replace("_", " ")
    if name == featured.get("tfa", ""):
        return "Featured as Wikipedia's 'Today's Featured Article'"
    if name in featured.get("news", []):
        return "Featured in Wikipedia's 'In the News' section"
    if name in featured.get("onthisday", []):
        return "Featured in Wikipedia's 'On This Day' section"
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


async def get_reddit_mentions(session, article):
    """Search Reddit for recent posts mentioning this topic."""
    search_term = article.replace("_", " ")
    url = "https://www.reddit.com/search.json"
    params = {"q": search_term, "sort": "relevance", "t": "week", "limit": 5}
    try:
        async with session.get(url, params=params,
                               headers={"User-Agent": USER_AGENT}) as resp:
            if resp.status == 200:
                data = await resp.json()
                posts = data.get("data", {}).get("children", [])
                if not posts:
                    return ""
                results = []
                for post in posts[:3]:
                    d = post.get("data", {})
                    title = d.get("title", "")
                    sub = d.get("subreddit", "")
                    score = d.get("score", 0)
                    comments = d.get("num_comments", 0)
                    if title:
                        results.append("r/{}: \"{}\" ({} upvotes, {} comments)".format(
                            sub, title[:100], score, comments,
                        ))
                if results:
                    return "Reddit posts this week:\n" + "\n".join(results)
    except Exception as e:
        log.debug("Reddit search failed for %s: %s", article, e)
    return ""


async def get_multilang_spike(session, article):
    """Check if this article is also spiking on other language Wikipedias."""
    # First get the Wikidata item to find other language titles
    url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query", "format": "json", "prop": "langlinks",
        "titles": article, "lllimit": "50",
    }
    try:
        async with session.get(url, params=params, headers={"User-Agent": USER_AGENT}) as resp:
            if resp.status != 200:
                return ""
            data = await resp.json()
            page = next(iter(data["query"]["pages"].values()))
            langlinks = page.get("langlinks", [])
    except Exception as e:
        log.debug("Langlinks fetch failed for %s: %s", article, e)
        return ""

    # Check top languages for spikes
    check_langs = {}
    for ll in langlinks:
        lang = ll.get("lang", "")
        if lang in ("de", "fr", "es", "ja", "ru", "pt", "it", "zh"):
            check_langs[lang] = ll.get("*", "")

    if not check_langs:
        return ""

    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    week_ago = yesterday - timedelta(days=7)
    date_y = yesterday.strftime("%Y%m%d")
    date_w = week_ago.strftime("%Y%m%d")

    spiking = []
    for lang, title in check_langs.items():
        try:
            view_url = (
                "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
                "{}.wikipedia/all-access/user/{}/daily/{}/{}"
            ).format(lang, title, date_w, date_y)
            async with session.get(view_url, headers={"User-Agent": USER_AGENT}) as resp:
                if resp.status != 200:
                    continue
                vdata = await resp.json()
                items = vdata.get("items", [])
                if len(items) < 2:
                    continue
                daily = [d["views"] for d in items]
                avg = sum(daily[:-1]) / max(len(daily) - 1, 1)
                if avg > 0 and daily[-1] / avg >= 2.0:
                    spiking.append("{} ({:.0f}x)".format(lang, daily[-1] / avg))
        except Exception:
            pass

    if spiking:
        return "Also spiking on other Wikipedias: {}".format(", ".join(spiking))
    return ""


async def get_wikidata_info(session, article):
    """Get structured data from Wikidata (dates, type) to help identify anniversaries."""
    # Resolve Wikipedia article to Wikidata entity
    url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query", "format": "json", "prop": "pageprops",
        "ppprop": "wikibase_item", "titles": article,
    }
    try:
        async with session.get(url, params=params, headers={"User-Agent": USER_AGENT}) as resp:
            if resp.status != 200:
                return ""
            data = await resp.json()
            page = next(iter(data["query"]["pages"].values()))
            qid = page.get("pageprops", {}).get("wikibase_item", "")
            if not qid:
                return ""
    except Exception as e:
        log.debug("Wikidata resolve failed for %s: %s", article, e)
        return ""

    # Fetch key properties from Wikidata
    wd_url = "https://www.wikidata.org/w/api.php"
    params = {
        "action": "wbgetclaims", "format": "json", "entity": qid,
        # P31=instance of, P569=birth, P570=death, P571=inception,
        # P576=dissolved, P585=point in time, P580=start time
        "property": "P31|P569|P570|P571|P576|P585|P580",
    }
    try:
        async with session.get(wd_url, params=params, headers={"User-Agent": USER_AGENT}) as resp:
            if resp.status != 200:
                return ""
            data = await resp.json()
            claims = data.get("claims", {})
    except Exception as e:
        log.debug("Wikidata claims failed for %s: %s", article, e)
        return ""

    today = datetime.now(timezone.utc)
    parts = []

    # Extract dates and check for anniversaries
    date_props = {
        "P569": "Born", "P570": "Died", "P571": "Founded/created",
        "P576": "Dissolved", "P585": "Occurred", "P580": "Started",
    }
    for prop, label in date_props.items():
        for claim in claims.get(prop, []):
            try:
                tv = claim["mainsnak"]["datavalue"]["value"]["time"]
                # Wikidata format: +YYYY-MM-DDT00:00:00Z
                year = int(tv[1:5])
                month = int(tv[6:8])
                day = int(tv[9:11])
                if month == 0 or day == 0:
                    continue
                years_ago = today.year - year
                if month == today.month and day == today.day:
                    parts.append("{}: {}-{:02d}-{:02d} (exactly {} years ago TODAY)".format(
                        label, year, month, day, years_ago))
                elif abs((today - datetime(today.year, month, day, tzinfo=timezone.utc)).days) <= 3:
                    parts.append("{}: {}-{:02d}-{:02d} ({} years ago this week)".format(
                        label, year, month, day, years_ago))
                else:
                    parts.append("{}: {}-{:02d}-{:02d}".format(label, year, month, day))
            except (KeyError, ValueError, TypeError):
                pass

    if parts:
        return "Wikidata: " + "; ".join(parts)
    return ""


async def get_recent_edits(session, article):
    """Fetch recent edit summaries for an article."""
    url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query", "format": "json", "prop": "revisions",
        "titles": article, "rvlimit": "10", "rvprop": "comment|timestamp",
    }
    try:
        async with session.get(url, params=params, headers={"User-Agent": USER_AGENT}) as resp:
            if resp.status == 200:
                data = await resp.json()
                page = next(iter(data["query"]["pages"].values()))
                revisions = page.get("revisions", [])
                if not revisions:
                    return ""
                # Count recent edits (last 2 days)
                cutoff = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
                recent = [r for r in revisions if r.get("timestamp", "") >= cutoff]
                comments = [r.get("comment", "") for r in recent if r.get("comment")]
                if recent:
                    summary = "{} edits in last 2 days".format(len(recent))
                    if comments:
                        summary += ". Edit notes: " + "; ".join(comments[:3])
                    return summary
    except Exception as e:
        log.debug("Edit history fetch failed for %s: %s", article, e)
    return ""


async def check_trending(session, article_name, current_views):
    """Lightweight check: fetch only historical views to test the threshold.

    Always returns a dict with a 'status' field for diagnostics:
    'trending', 'below_threshold', 'no_history', or 'zero_avg'.
    """
    result = {
        "article": article_name,
        "views": current_views,
        "avg": 0,
        "mult": 0,
        "status": "no_history",
    }
    historical = await get_article_views(session, article_name)
    if not historical or len(historical) <= 1:
        return result

    daily = [day["views"] for day in historical]
    avg = sum(daily[:-1]) / (len(daily) - 1)
    if avg == 0:
        result["status"] = "zero_avg"
        return result

    multiplier = current_views / avg
    result["avg"] = int(avg)
    result["mult"] = round(multiplier, 1)
    result["daily_shape"] = ", ".join(format_views(v) for v in daily)
    result["history_days"] = len(daily)
    result["status"] = "trending" if multiplier >= TRENDING_THRESHOLD else "below_threshold"
    return result


async def enrich_article(session, article):
    """Fill in description, news, edit history, traffic patterns, etc."""
    name = article["article"]
    (description, headline, edits, access,
     hourly, reddit, multilang, wikidata) = await asyncio.gather(
        get_description(session, name),
        get_news_headline(session, name),
        get_recent_edits(session, name),
        get_access_breakdown(session, name),
        get_hourly_pattern(session, name),
        get_reddit_mentions(session, name),
        get_multilang_spike(session, name),
        get_wikidata_info(session, name),
    )
    article["wiki_desc"] = description
    article["news_headline"] = headline
    article["recent_edits"] = edits
    article["access_breakdown"] = access
    article["hourly_pattern"] = hourly
    article["reddit_mentions"] = reddit
    article["multilang_spike"] = multilang
    article["wikidata_info"] = wikidata
    article["desc"] = headline if headline else description


async def fetch_trending():
    async with aiohttp.ClientSession() as session:
        data = None
        for days_back in range(1, 8):
            date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y/%m/%d")
            url = (
                "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/"
                "en.wikipedia/all-access/{}"
            ).format(date)
            log.info("Fetching top pages for %s", date)
            async with session.get(url, headers={"User-Agent": USER_AGENT}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    break
                log.warning("Top pages for %s not available (%d), trying earlier day", date, resp.status)
        if data is None:
            log.error("No top-pages data available in last 7 days")
            return []

        top_pages = data["items"][0]["articles"]
        candidates = [p for p in top_pages if not should_skip(p["article"])][:PAGES_TO_CHECK]

        # Fetch Wikipedia's main page featured content
        featured = await get_wiki_featured(session)
        log.info("Featured article: %s", featured.get("tfa", "none"))

        log.info(
            "Checking %d candidates for trending (threshold %.1fx)",
            len(candidates), TRENDING_THRESHOLD,
        )

        trending = []
        all_results = []
        stats = {"trending": 0, "below_threshold": 0, "no_history": 0, "zero_avg": 0}
        # Wikimedia Analytics API guidance: "wait for each request to finish
        # before sending another request." So no parallel batching here.
        log_every = 25
        for i, p in enumerate(candidates, 1):
            r = await check_trending(session, p["article"], p["views"])
            all_results.append(r)
            stats[r["status"]] += 1
            if r["status"] == "trending":
                trending.append(r)
            if i % log_every == 0 or i == len(candidates):
                log.info(
                    "Progress: %d/%d — trending=%d below=%d no_data=%d zero_avg=%d",
                    i, len(candidates),
                    stats["trending"], stats["below_threshold"],
                    stats["no_history"], stats["zero_avg"],
                )

        log.info(
            "Candidate breakdown: %d trending, %d below threshold, "
            "%d missing history, %d zero-avg (out of %d)",
            stats["trending"], stats["below_threshold"],
            stats["no_history"], stats["zero_avg"], len(candidates),
        )

        # Dump the strongest near-misses so we can see what *almost* trended.
        near_misses = sorted(
            (r for r in all_results if r["status"] == "below_threshold"),
            key=lambda x: -x["mult"],
        )[:10]
        if near_misses:
            log.info(
                "Top below-threshold candidates (under %.1fx):",
                TRENDING_THRESHOLD,
            )
            for r in near_misses:
                log.info(
                    "  %s: %.2fx (%s views vs avg %s, %d days history)",
                    r["article"], r["mult"],
                    format_views(r["views"]), format_views(r["avg"]),
                    r.get("history_days", 0),
                )

        trending.sort(key=lambda x: -x["mult"])

        # Enrich only the articles we'll actually display.
        # Process one at a time so we don't burst Wikimedia endpoints.
        to_enrich = trending[:DISPLAY_COUNT]
        if to_enrich:
            log.info("Enriching top %d trending articles", len(to_enrich))
            for article in to_enrich:
                try:
                    await enrich_article(session, article)
                except Exception as e:
                    log.warning("Enrichment failed for %s: %s", article["article"], e)
                    article.setdefault("desc", "")

        # Tag articles that were featured on Wikipedia's main page
        for article in trending:
            feature = check_wiki_feature(article["article"], featured)
            article["wiki_feature"] = feature
            if feature:
                log.info("Wiki feature: %s — %s", article["article"], feature)

        return trending


GEMINI_SYSTEM_RULES = """You are writing one-line descriptions for an e-ink display that shows Wikipedia articles with unusual traffic spikes.

Your job: write ONE sentence that briefly says WHAT this is, then WHY it's spiking right now. The reader may have never heard of this topic.

Use the data provided AND your web search to investigate. You will be given:
- Daily and hourly traffic patterns (look for sudden spikes vs gradual rises)
- Desktop vs mobile split (heavy mobile = social media; heavy desktop = news/search)
- Reddit posts mentioning this topic (Reddit is a top Wikipedia traffic driver)
- Whether other language Wikipedias are also spiking (global event vs English-only)
- Wikidata dates (check if today is a notable anniversary)
- Wikipedia main page features, news headlines, and recent edit activity

Use these clues together to determine the cause. For example:
- Spike at a single hour + heavy mobile = likely a viral tweet or TikTok
- Spiking across multiple languages = global news event
- Anniversary date from Wikidata matching today = anniversary-driven traffic
- High-upvote Reddit post = Reddit-driven traffic
- Gradual rise + heavy desktop = news article or Wikipedia feature

CRITICAL rules for your response:
- Required format: "<what it is> — <why it's spiking>". The em dash (—) is MANDATORY and must separate the two parts.
- NEVER start with meta-phrases like "The article is about", "This article", "This page describes", "The page is about", "This is an article about". Start with the subject directly.
- Your sentence MUST be about the given article specifically — do not describe a loosely related news story that merely mentions a similar topic.
- Respond with ONLY one sentence. Nothing else.
- Be specific: include names, dates, scores, outcomes when relevant.
- Keep it under 150 characters if possible. Hard cap 200.
- If the cause is genuinely unclear, infer the most likely driver from the data (e.g. "featured on Wikipedia main page", "Reddit-driven interest", "anniversary of a notable event", "gradual organic search interest"). NEVER bail out by paraphrasing the Wikipedia intro. NEVER say the cause is unclear or unknown.

EXAMPLES — format is "what it is — why it's spiking". Use an em dash to separate.

  Article: Ruby Rose
  GOOD: 'Australian actress — accused Katy Perry of sexual assault at a Melbourne nightclub.'
  BAD: 'An Australian model and actress who has been in the news recently.'

  Article: Carrizozo volcanic field
  GOOD: 'Lava field in New Mexico — featured in a NASA Science article about its 40-mile flow.'
  BAD: 'A volcanic field in central New Mexico covering 330 square miles.'

  Article: Dacre railway station
  GOOD: "Closed station in Cumbria, England — featured on Wikipedia's main page as a Did You Know entry."
  BAD: 'The Dacre railway station article is experiencing a traffic spike because...'

  Article: Warren Zevon
  GOOD: 'Werewolves of London singer — would have turned 79 today.'
  BAD: 'An American rock singer and songwriter known for Werewolves of London.'

  Article: 330 West 42nd Street
  GOOD: "Manhattan Art Deco skyscraper, the McGraw-Hill Building — featured on Wikipedia's main page Did You Know section."
  BAD: 'The article is about 330 West 42nd Street, also known as the McGraw-Hill Building, a 485-foot-tall skyscraper...'"""


_BANNED_PREFIXES = (
    "the article is about",
    "the article describes",
    "this article ",
    "this page ",
    "the page is about",
    "the page describes",
    "this is an article about",
)


def _validate_reason(text):
    """Return error string if the reason fails our format rules, else ''."""
    if not text:
        return "empty response"
    stripped = text.lstrip("'\"").lower()
    for prefix in _BANNED_PREFIXES:
        if stripped.startswith(prefix):
            return "starts with meta-phrase '{}'".format(prefix.strip())
    if "—" not in text:
        return "missing em dash"
    if len(text) > 250:
        return "too long ({} chars)".format(len(text))
    return ""


async def _call_gemini(session, user_text):
    """Single Gemini call with system instruction + grounding. Returns text or ''."""
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        "models/gemini-2.5-flash:generateContent?key={}"
    ).format(GEMINI_API_KEY)
    payload = {
        "system_instruction": {"parts": [{"text": GEMINI_SYSTEM_RULES}]},
        "contents": [{"parts": [{"text": user_text}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 4096,
            "thinkingConfig": {
                "thinkingBudget": 2048,
            },
        },
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
                            text = part["text"].strip()
                            text = re.sub(r'\s*\[cite:[^\]]*\]?', '', text)
                            text = re.sub(r'\s*\[\d+(?:,\s*\d+)*\]?', '', text)
                            return text.strip()
                log.warning("Gemini 200 but no text: %s", json.dumps(data)[:300])
            else:
                body = await resp.text()
                log.warning("Gemini returned %d: %s", resp.status, body[:200])
    except Exception as e:
        log.warning("Gemini fetch failed: %s", e)
    return ""


async def get_trending_reason(session, article_name, mult, wiki_desc="",
                              news_headline="", wiki_feature="", recent_edits="",
                              access_breakdown="", daily_shape="", hourly_pattern="",
                              reddit_mentions="", multilang_spike="", wikidata_info=""):
    """Ask Gemini with Google Search grounding why an article is trending."""
    name = article_name.replace("_", " ")
    context_parts = []
    if wiki_feature:
        context_parts.append("Wikipedia main page: {}".format(wiki_feature))
    if wiki_desc:
        context_parts.append("Wikipedia intro: {}".format(wiki_desc[:300]))
    if news_headline:
        context_parts.append("Recent headline: {}".format(news_headline))
    if recent_edits:
        context_parts.append("Recent Wikipedia edits: {}".format(recent_edits[:300]))
    if access_breakdown:
        context_parts.append(access_breakdown)
    if daily_shape:
        context_parts.append("Daily views (oldest to newest): {}".format(daily_shape))
    if hourly_pattern:
        context_parts.append(hourly_pattern)
    if reddit_mentions:
        context_parts.append(reddit_mentions)
    if multilang_spike:
        context_parts.append(multilang_spike)
    if wikidata_info:
        context_parts.append(wikidata_info)
    context = "\n".join(context_parts)
    user_text = (
        "Article: {name}\n"
        "Traffic spike: {mult}x normal\n"
        "{context}"
    ).format(name=name, mult=mult, context=context)

    text = await _call_gemini(session, user_text)
    err = _validate_reason(text)
    if err:
        log.info("Gemini retry for %s (%s): %r", article_name, err, text[:120])
        retry_text = (
            "{user_text}\n\n"
            "IMPORTANT: Your previous response was rejected because it {err}. "
            "Rewrite as ONE sentence in the format "
            "'<what it is> — <why it\\'s spiking>'. "
            "The em dash is required. Do NOT start with 'The article is about' "
            "or any other meta-phrase."
        ).format(user_text=user_text, err=err)
        retry = await _call_gemini(session, retry_text)
        retry_err = _validate_reason(retry)
        if retry_err:
            log.warning("Gemini retry still invalid for %s (%s): %r",
                        article_name, retry_err, retry[:120])
            # Return the better of the two if we have anything; else empty.
            return retry or text
        return retry
    return text


async def enrich_with_reasons(trending):
    """Replace descriptions with AI-generated trending reasons for top articles."""
    top = trending[:DISPLAY_COUNT]
    async with aiohttp.ClientSession() as session:
        for article in top:
            reason = await get_trending_reason(
                session, article["article"], article["mult"],
                wiki_desc=article.get("wiki_desc", ""),
                news_headline=article.get("news_headline", ""),
                wiki_feature=article.get("wiki_feature", ""),
                recent_edits=article.get("recent_edits", ""),
                access_breakdown=article.get("access_breakdown", ""),
                daily_shape=article.get("daily_shape", ""),
                hourly_pattern=article.get("hourly_pattern", ""),
                reddit_mentions=article.get("reddit_mentions", ""),
                multilang_spike=article.get("multilang_spike", ""),
                wikidata_info=article.get("wikidata_info", ""),
            )
            if reason:
                log.info("Gemini: %s -> %s", article["article"], reason)
                article["desc"] = reason
            await asyncio.sleep(5)


def build_trmnl_payload(trending):
    now = datetime.now()
    display = trending[:DISPLAY_COUNT]

    articles = []
    for a in display:
        desc = a.get("desc") or ""
        if len(desc) > 200:
            desc = desc[:197] + "..."
        name = a["article"].replace("_", " ")
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
                    desc = a.get("desc") or "(not enriched)"
                    log.info(
                        "  #%d: %s (%.1fx, %s views) — %s",
                        i, a["article"], a["mult"], format_views(a["views"]),
                        desc[:80],
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
