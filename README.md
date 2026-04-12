# TRMNL-Items

Custom plugins for the [TRMNL](https://usetrmnl.com/) e-ink display.

## Projects

### [Airport Tracker](airport-tracker/)
Tracks daily flight activity at Montgomery-Gibbs Executive Airport (KMYF) in San Diego. Shows arrivals, departures, aircraft types, hourly activity chart, and weather.

---

## How the Stack Works

### The Display
- **TRMNL** is a 800x480 pixel e-ink display (black and white only, no grayscale)
- It refreshes on its own schedule (~every 15 minutes)
- Each plugin has an HTML/CSS template using [Liquid](https://shopify.github.io/liquid/) syntax for dynamic data
- TRMNL hosts the templates — you paste markup into their web dashboard

### The Server (Unraid)
- An **Unraid server** (KServer) runs Docker containers 24/7
- The GitHub repo is cloned to `/mnt/user/appdata/TRMNL-Items/`
- Each project builds its own Docker image from its subfolder
- Containers run continuously, polling APIs and pushing data to TRMNL
- A **User Scripts** plugin ("trmnl-auto-update") checks GitHub daily and rebuilds containers if there are new commits

### The Data Flow

```
  APIs (airplanes.live, Open-Meteo, etc.)
       |
       | poll every ~2 min
       v
  Docker container (on Unraid)
  - Fetches data from APIs
  - Processes & tracks state (JSON file on disk)
  - Builds payload (must be under 2KB)
       |
       | push every ~10 min
       v
  TRMNL webhook API
  - Receives JSON payload via POST
  - Merges variables into the Liquid template
       |
       | refresh every ~15 min
       v
  TRMNL e-ink display
  - Renders the template with the latest data
```

### Where Each Piece Lives

| What | Where | Notes |
|------|-------|-------|
| Source code | GitHub (`KurtMoran/TRMNL-Items`) | Single repo for all TRMNL projects |
| Server clone | `/mnt/user/appdata/TRMNL-Items/` on Unraid | `git pull` to update |
| Docker containers | Unraid Docker | One container per project, `--restart unless-stopped` |
| Persistent data | `<project>/data/` on Unraid | Mounted as Docker volume, survives rebuilds |
| Liquid templates | TRMNL web dashboard | Pasted manually into the markup editor |
| TRMNL plugin config | TRMNL web dashboard | Webhook strategy, plugin UUID, bleed margin settings |

### TRMNL Plugin Setup (for each project)

1. Create a **Private Plugin** on the TRMNL dashboard
2. Set strategy to **Webhook**
3. Copy the **UUID** — this goes into the Docker container as an env variable
4. Paste the project's HTML/Liquid template into the **Markup Editor**
5. Set **Remove bleed margin** = Yes
6. Uncheck **Show TRMNL logo**

### Server Setup (one-time)

```bash
# Clone the repo
git clone https://github.com/KurtMoran/TRMNL-Items.git /mnt/user/appdata/TRMNL-Items

# Build and run a project (example: airport-tracker)
cd /mnt/user/appdata/TRMNL-Items/airport-tracker
docker build --no-cache -t trmnl-items .
docker run -d --name trmnl-items --restart unless-stopped \
  -e TZ=America/Los_Angeles \
  -e TRMNL_WEBHOOK_UUID=<your-uuid> \
  -e POLL_INTERVAL_SEC=120 \
  -e DATA_FILE=/data/tracker_state.json \
  -v /mnt/user/appdata/TRMNL-Items/airport-tracker/data:/data \
  trmnl-items
```

### Updating After Code Changes

Push changes to GitHub, then on the Unraid terminal:

```bash
cd /mnt/user/appdata/TRMNL-Items && git pull
docker stop trmnl-items && docker rm trmnl-items
cd airport-tracker && docker build --no-cache -t trmnl-items .
docker run -d --name trmnl-items --restart unless-stopped \
  -e TZ=America/Los_Angeles \
  -e TRMNL_WEBHOOK_UUID=<your-uuid> \
  -e POLL_INTERVAL_SEC=120 \
  -e DATA_FILE=/data/tracker_state.json \
  -v /mnt/user/appdata/TRMNL-Items/airport-tracker/data:/data \
  trmnl-items
```

Or just let the auto-update User Script handle it (checks daily).

### Key Constraints
- **2KB payload limit** on TRMNL's standard plan — keep JSON keys short
- **No grayscale** on e-ink — use solid black, white, or CSS patterns (stripes, dots)
- **No external CSS/JS** in templates — TRMNL's own CSS framework conflicts with custom styles
- **Timezone** must be set via `-e TZ=America/Los_Angeles` or Docker defaults to UTC
