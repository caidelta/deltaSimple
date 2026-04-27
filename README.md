# deltaSimple

A lightweight Python worker that monitors your **Wealthsimple options portfolio** via SnapTrade, detects position changes, and fires formatted **Discord alerts** — so you never miss an open, a price move, or a close while away from your screen.

> **Read-only.** deltaSimple never places or modifies trades.

---

## What It Does

| Event | Alert |
|---|---|
| New option position detected | 🟢 **New Option Opened** — contract, strike, avg cost, underlying price |
| Underlying moves past your threshold | 📊 **Position Update** — price move %, estimated P&L |
| Position disappears from your account | 🔴 **Option Closed** — close price, P&L, days held |
| Bot starts up | ✅ **deltaSimple Connected** — confirms webhook is live |

---

## Prerequisites

Before you start, you need three things:

1. **SnapTrade developer account** — [sign up free at snaptrade.com](https://snaptrade.com)  
   After signing in, go to **Dashboard → API Keys** and copy your **Client ID** and **Consumer Key**.

2. **Discord webhook URL**  
   In Discord: open a channel → **Edit Channel → Integrations → Webhooks → New Webhook → Copy Webhook URL**.

3. **Python 3.11+** *or* **Docker** (Docker is easier — no Python install required).

---

## Setup (under 15 minutes)

### Step 1 — Clone the repo

```bash
git clone https://github.com/yourname/deltaSimple.git
cd deltaSimple
```

### Step 2 — Create your `.env` file

```bash
cp .env.example .env
```

Open `.env` in any text editor and fill in your values:

```bash
# SnapTrade credentials
SNAPTRADE_CLIENT_ID=your_client_id_here
SNAPTRADE_CONSUMER_KEY=your_consumer_key_here
SNAPTRADE_USER_ID=cai                       # any short identifier for yourself

# Leave SNAPTRADE_USER_SECRET blank on first run — the bot fills it in automatically
SNAPTRADE_USER_SECRET=

# Discord
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR/WEBHOOK

# Telegram (not yet implemented — leave blank)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Tracker settings
POLL_INTERVAL_SECONDS=30
PRICE_ALERT_THRESHOLD_PCT=5.0

# Environment
ENV=production
```

> **Security reminder:** `.env` is gitignored. Never commit it.

---

### Option A — Run with Docker (recommended)

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/).

```bash
# Build the image
docker compose build

# Start the bot (runs in the background)
docker compose up -d

# Watch the logs
docker compose logs -f

# Stop
docker compose down
```

On first start the bot registers your SnapTrade user and writes the generated secret back to your `.env` file. The SQLite database is saved to `./tracker.db` on your host machine so it survives container restarts.

---

### Option B — Run locally without Docker

```bash
pip install -r requirements.txt
python tracker.py
```

---

### Option C — Deploy to Render

Render runs the bot 24/7 in the cloud for free (worker tier).

1. Push this repo to GitHub.
2. Go to [render.com](https://render.com) → **New → Blueprint** → connect your repo.  
   Render reads `render.yaml` and creates the worker automatically.
3. Open the service in the Render dashboard, go to **Environment**, and add each variable from your `.env`.  
   *Do not add `SNAPTRADE_USER_SECRET` yet — the bot registers and sets it on first boot.*
4. Click **Deploy**. Watch the logs. When you see `✅ deltaSimple Connected` in Discord, you're live.

> **Persistence on Render:** Render's free tier has ephemeral storage — the SQLite DB resets on each deploy. For production, upgrade to a paid plan with a persistent disk mounted at `/app/tracker.db`, or migrate to PostgreSQL in a future phase.

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `SNAPTRADE_CLIENT_ID` | Yes | — | SnapTrade API client ID |
| `SNAPTRADE_CONSUMER_KEY` | Yes | — | SnapTrade API consumer key |
| `SNAPTRADE_USER_ID` | Yes | — | Any identifier for your SnapTrade user (e.g. `"cai"`) |
| `SNAPTRADE_USER_SECRET` | No | *(auto-set)* | Set automatically on first run — do not touch after |
| `DISCORD_WEBHOOK_URL` | Yes | — | Discord channel webhook URL |
| `POLL_INTERVAL_SECONDS` | Yes | `30` | How often to check for position changes (seconds) |
| `PRICE_ALERT_THRESHOLD_PCT` | Yes | `5.0` | Underlying % move that triggers a price alert |
| `ENV` | No | `production` | Set to `development` for verbose debug logging |
| `TELEGRAM_BOT_TOKEN` | No | *(unused)* | Coming soon |
| `TELEGRAM_CHAT_ID` | No | *(unused)* | Coming soon |

---

## Customisation

**Change the poll interval** — edit `POLL_INTERVAL_SECONDS` in `.env`.  
A lower number means faster detection but more API calls. 30 seconds is a safe default.

**Change the alert threshold** — edit `PRICE_ALERT_THRESHOLD_PCT` in `.env`.  
`5.0` fires an alert when the underlying moves 5% from the last snapshot. Set lower for tighter tracking, higher to reduce noise.

**Verbose logging** — set `ENV=development` to see every poll tick in the logs.

---

## Project Structure

```
deltaSimple/
├── config.py           # env var loading + validation
├── database.py         # SQLite schema + CRUD
├── snaptrade_client.py # SnapTrade auth + position fetch
├── price_tracker.py    # yfinance price + option value estimate
├── alerts.py           # Discord embed builders
├── notifier.py         # httpx Discord/Telegram senders
├── tracker.py          # main polling loop (Phase 6)
├── Dockerfile
├── docker-compose.yml
├── render.yaml
├── .env.example
└── tests/
```

---

## Telegram (Coming Soon)

Telegram delivery is stubbed — the bot logs `"Telegram not yet implemented, skipping"` and continues. A future phase will add Telegram support alongside a small web dashboard, with a planned migration path to Hugging Face Spaces for hosting the UI.

---

## Running Tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

All tests use mocked external calls — no real SnapTrade, Discord, or yfinance requests are made.

---

## License

MIT
