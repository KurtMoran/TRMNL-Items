# Wikipedia Trending — TRMNL Display

E-ink display showing Wikipedia articles that are trending well above their normal traffic, with AI-generated explanations of why each article is spiking.

## How it works

1. Fetches yesterday's top 200 Wikipedia pages (by pageviews)
2. Compares each to its 7-day average — articles above 3x are "trending"
3. For the top 5, asks Google Gemini (with web search) to explain *why* it's trending
4. Falls back to Google News headlines, then Wikipedia intro if Gemini is unavailable
5. Pushes results to a TRMNL e-ink display via webhook

## APIs used

| API | Auth | Cost | Rate |
|-----|------|------|------|
| Wikipedia APIs | None | Free | ~600 requests/cycle |
| Google News RSS | None | Free | ~200 requests/cycle |
| Google Gemini 2.5 Flash | API key | Free tier | 5 requests/cycle, 5s apart |
| TRMNL Webhook | Plugin UUID | Included with TRMNL | 1 push/cycle |

Runs every 4 hours (6 cycles/day).

## Setup

### 1. Create TRMNL plugin

- Go to trmnl.com > Plugins > Private Plugin > Create
- Name: "Wiki Trending"
- Strategy: Webhook
- Paste contents of `trmnl_template.html` into the Markup editor
- Set "Remove bleed margin" = Yes
- Copy the webhook UUID

### 2. Get a Gemini API key (optional, free)

- Go to https://aistudio.google.com/apikey
- Create an API key
- The free tier (1,500 requests/day) is more than enough

### 3. Build and run

```bash
docker build -t wiki-trending /path/to/wiki-trending/

docker run -d \
  --name wiki-trending \
  --restart unless-stopped \
  -e TZ=America/Los_Angeles \
  -e TRMNL_WEBHOOK_UUID=your-uuid-here \
  -e GEMINI_API_KEY=your-key-here \
  -v /path/to/data:/data \
  wiki-trending
```

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TRMNL_WEBHOOK_UUID` | Yes | From your TRMNL private plugin |
| `GEMINI_API_KEY` | No | Enables AI-generated "why trending" descriptions |
| `TZ` | No | Timezone for display timestamps (default: UTC) |
| `POLL_INTERVAL_SEC` | No | Seconds between cycles (default: 14400 = 4 hours) |
| `DATA_FILE` | No | State file path (default: /data/wiki_state.json) |

## Files

| File | Purpose |
|------|---------|
| `tracker.py` | Main tracker script |
| `trmnl_template.html` | Liquid template — paste into TRMNL Markup editor |
| `preview.html` | Standalone browser preview with sample data |
| `Dockerfile` | Container build |
| `requirements.txt` | Python dependencies |

## Description fallback chain

1. **Gemini + Google Search** — AI-written explanation with live web context. If the trending cause is unclear, Gemini writes a concise topic summary instead.
2. **Google News headline** — latest news headline about the topic (used if Gemini is unavailable)
3. **Wikipedia intro** — first two sentences of the article (used if both above fail)
