# CLAUDE.md — deltaSimple

## Project Overview

A Python background worker that monitors a Wealthsimple options portfolio via SnapTrade,
detects new/closed positions, tracks underlying price movements, and sends formatted
Discord alerts. Designed to be fully replicable — anyone can clone, fill in `.env`, and deploy.

**What this bot does:**
- Detects when a new options position is opened → sends Discord alert
- Polls underlying price while position is open → alerts on configurable % move
- Detects when a position is closed → sends Discord alert with P&L
- Stores state in SQLite so restarts don't cause duplicate alerts

**What this bot does NOT do:**
- Place or modify trades (read-only)
- Implement Telegram (stubbed for future phase)
- Provide a web UI or dashboard
- Calculate exact option pricing (uses yfinance underlying + estimated value)

---

## File Structure

```
deltaSimple/
├── CLAUDE.md
├── .env.example
├── .env                    # gitignored
├── .gitignore
├── requirements.txt
├── config.py               # loads + validates all env vars
├── database.py             # SQLite setup + queries
├── snaptrade_client.py     # SnapTrade auth + position fetching
├── price_tracker.py        # yfinance underlying price + est. option value
├── notifier.py             # Discord webhook sender (Telegram stub)
├── alerts.py               # formats all 3 alert types as Discord embeds
├── tracker.py              # main polling loop + state diff logic
├── tests/
│   ├── test_database.py
│   ├── test_price_tracker.py
│   ├── test_alerts.py
│   ├── test_notifier.py
│   └── test_tracker.py
├── render.yaml
└── README.md
```

---

## Tech Stack

| Layer | Library | Version |
|---|---|---|
| Language | Python | 3.11+ |
| Brokerage | snaptrade-python-sdk | latest |
| Price data | yfinance | latest |
| Greeks | mibian | latest |
| HTTP client | httpx | latest |
| Database | sqlite3 | stdlib |
| Config | python-dotenv | latest |
| Logging | loguru | latest |
| Testing | pytest + pytest-asyncio | latest |
| Dependency mgmt | uv | latest |

---

## Environment Variables (.env.example)

```bash
# SnapTrade credentials (get from snaptrade.com/dashboard)
SNAPTRADE_CLIENT_ID=your_client_id
SNAPTRADE_CONSUMER_KEY=your_consumer_key
SNAPTRADE_USER_ID=your_chosen_user_id          # any string, e.g. "cai"
SNAPTRADE_USER_SECRET=                          # populated after registration

# Discord
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Telegram (future — leave blank for now)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Tracker settings
POLL_INTERVAL_SECONDS=30
PRICE_ALERT_THRESHOLD_PCT=5.0                  # alert when underlying moves this %

# Environment
ENV=production                                  # or "development" for verbose logging
```

---

## Module Responsibilities

### `config.py`
- Loads all env vars via `python-dotenv`
- Validates required fields are present on startup
- Exposes typed config object used across all modules
- Raises clear error if any required var is missing

### `database.py`
- Creates SQLite DB and tables on first run
- Table: `positions` — tracks all known options positions
- Table: `price_snapshots` — last known underlying price per position
- Functions: `upsert_position`, `get_open_positions`, `mark_position_closed`, `get_last_price`

### `snaptrade_client.py`
- Handles SnapTrade user registration (first run only)
- Authenticates and stores user secret back to `.env`
- `get_options_positions()` → returns list of current open options positions
- Normalizes SnapTrade response into internal `Position` dataclass

### `price_tracker.py`
- `get_underlying_price(ticker: str)` → current price via yfinance
- `estimate_option_value(position, current_price)` → simple intrinsic + basic estimate
- `compute_pct_change(old_price, new_price)` → float
- No live options chain — uses underlying movement as proxy

### `notifier.py`
- `send_discord(embed: dict)` → POST to Discord webhook via httpx
- `send_telegram(message: str)` → stubbed, logs "Telegram not implemented"
- Handles HTTP errors gracefully, logs failures without crashing

### `alerts.py`
- `build_open_alert(position)` → Discord embed dict
- `build_update_alert(position, old_price, new_price)` → Discord embed dict
- `build_close_alert(position, close_price)` → Discord embed dict
- All embeds follow consistent format with color coding (green/yellow/red)

### `tracker.py`
- Entry point — runs the async polling loop
- Every `POLL_INTERVAL_SECONDS`:
  1. Fetch current positions from SnapTrade
  2. Compare against SQLite state
  3. New positions → trigger open alert + insert to DB
  4. Existing positions → check price, trigger update alert if threshold crossed
  5. Missing positions → trigger close alert + mark DB closed
- Graceful shutdown on SIGINT

---

## Position Dataclass

```python
@dataclass
class Position:
    id: str                  # SnapTrade position ID
    ticker: str              # underlying symbol e.g. "AAPL"
    option_type: str         # "call" or "put"
    strike: float
    expiry: str              # "YYYY-MM-DD"
    quantity: int
    avg_cost: float          # per contract (x100 for total)
    opened_at: str           # ISO timestamp
    status: str              # "open" or "closed"
```

---

## Alert Formats

### Open Alert (green embed)
```
🟢 New Option Opened
Contract: AAPL 180C 2026-05-16
Type: Call | Strike: $180.00 | Expiry: May 16, 2026
Qty: 1 contract(s) | Avg Cost: $3.20 ($320.00 total)
Underlying at open: $178.45
```

### Price Update Alert (yellow embed)
```
📊 Position Update — AAPL 180C
Underlying: $178.45 → $187.20 (+4.92%)
Est. Option Value: $3.20 → $4.85
Est. P&L: +$165.00 (+51.6%)
Delta trigger: underlying moved past 5.0% threshold
```

### Close Alert (red embed)
```
🔴 Option Closed — AAPL 180C
Closed avg cost: $3.20 | Close price: $5.10
Est. P&L: +$190.00 (+59.4%)
Held: 3 days
```

---

## Polling + State Diff Logic

```
on each poll tick:
  snaptrade_positions = snaptrade_client.get_options_positions()
  db_positions = database.get_open_positions()

  snaptrade_ids = {p.id for p in snaptrade_positions}
  db_ids = {p.id for p in db_positions}

  newly_opened = snaptrade_ids - db_ids
  still_open   = snaptrade_ids & db_ids
  just_closed  = db_ids - snaptrade_ids

  for id in newly_opened:
      alerts.build_open_alert(position) → notifier.send_discord()
      database.upsert_position(position)

  for id in still_open:
      last_price = database.get_last_price(id)
      current_price = price_tracker.get_underlying_price(ticker)
      pct = price_tracker.compute_pct_change(last_price, current_price)
      if abs(pct) >= PRICE_ALERT_THRESHOLD_PCT:
          alerts.build_update_alert(...) → notifier.send_discord()
          database.upsert_price_snapshot(id, current_price)

  for id in just_closed:
      alerts.build_close_alert(position) → notifier.send_discord()
      database.mark_position_closed(id)
```

---

## Phases

---

### Phase 1 — Project Scaffold + Config

**Goal:** Repo structure, dependency setup, config loading, env validation.

**Tasks:**
- Initialize repo with `uv`, create `requirements.txt`
- Create `.env.example` with all variables
- Create `.gitignore` (exclude `.env`, `*.db`, `__pycache__`)
- Implement `config.py` — load env vars, validate required fields, raise on missing
- Set up `loguru` logger in `config.py`

**Test — `tests/test_config.py`:**
- Test that missing required env var raises `ValueError` with clear message
- Test that all fields load correctly from a mock `.env`
- Test that optional fields (Telegram) default to `None` without error
- Test that `PRICE_ALERT_THRESHOLD_PCT` parses as float

**Done when:** `python config.py` prints loaded config without error. All config tests pass.

---

### Phase 2 — Database Layer

**Goal:** SQLite setup, all CRUD operations for positions and price snapshots.

**Tasks:**
- Implement `database.py` with `init_db()` creating both tables
- Implement `Position` dataclass in `database.py`
- Functions: `upsert_position`, `get_open_positions`, `mark_position_closed`,
  `upsert_price_snapshot`, `get_last_price`
- DB file path configurable (default: `tracker.db`)

**Schema:**
```sql
CREATE TABLE positions (
    id TEXT PRIMARY KEY,
    ticker TEXT,
    option_type TEXT,
    strike REAL,
    expiry TEXT,
    quantity INTEGER,
    avg_cost REAL,
    opened_at TEXT,
    status TEXT DEFAULT 'open'
);

CREATE TABLE price_snapshots (
    position_id TEXT PRIMARY KEY,
    last_price REAL,
    updated_at TEXT
);
```

**Test — `tests/test_database.py`:**
- Test `init_db()` creates both tables
- Test `upsert_position` inserts new position correctly
- Test `upsert_position` updates existing position without duplicate
- Test `get_open_positions` returns only status='open' rows
- Test `mark_position_closed` updates status correctly
- Test `upsert_price_snapshot` inserts and overwrites correctly
- Test `get_last_price` returns `None` for unknown position
- All tests use in-memory SQLite (`:memory:`)

**Done when:** All database tests pass with no real file created.

---

### Phase 3 — SnapTrade Integration

**Goal:** Authenticate with SnapTrade, register user, fetch live options positions.

**Tasks:**
- Implement `snaptrade_client.py`
- `register_user()` — registers user on first run, saves `SNAPTRADE_USER_SECRET` back to `.env`
- `get_options_positions()` — fetches positions, filters to options only, returns `list[Position]`
- Normalize raw SnapTrade response fields into `Position` dataclass
- Handle auth errors gracefully with logged message

**Notes:**
- SnapTrade user registration is one-time; secret must be persisted to `.env`
- If `SNAPTRADE_USER_SECRET` already set, skip registration
- Test with real SnapTrade sandbox credentials (developer account required)

**Test — `tests/test_snaptrade_client.py`:**
- Test `get_options_positions()` with mocked SnapTrade response returns correct `Position` list
- Test that non-options positions (stocks/ETFs) are filtered out
- Test normalization of option type ("call"/"put") from raw response
- Test that missing fields in response raise `ValueError` with clear message
- Use `unittest.mock.patch` to mock SDK calls — no real API calls in tests

**Done when:** Running `python snaptrade_client.py` with real credentials prints current positions.

---

### Phase 4 — Price Tracker

**Goal:** Fetch underlying prices, estimate option value change, compute % move.

**Tasks:**
- Implement `price_tracker.py`
- `get_underlying_price(ticker)` → float via yfinance `.fast_info.last_price`
- `compute_pct_change(old, new)` → float (signed)
- `estimate_option_value(position, old_underlying, new_underlying)` → estimated new contract value
  - Simple approach: scale avg_cost by same % as underlying (directional proxy)
  - Call: positive underlying move = positive option move
  - Put: negative underlying move = positive option move

**Test — `tests/test_price_tracker.py`:**
- Test `compute_pct_change(100, 105)` returns `5.0`
- Test `compute_pct_change(100, 95)` returns `-5.0`
- Test `estimate_option_value` for call increases with positive underlying move
- Test `estimate_option_value` for put increases with negative underlying move
- Test `get_underlying_price` with mocked yfinance (no real network calls)
- Test that yfinance failure raises exception with ticker name in message

**Done when:** `python price_tracker.py AAPL` prints current AAPL price. All tests pass.

---

### Phase 5 — Alerts + Notifier

**Goal:** Build Discord embeds for all 3 alert types, send via webhook.

**Tasks:**
- Implement `alerts.py` — 3 builder functions returning Discord embed dicts
- Color codes: open=`0x00FF00` (green), update=`0xFFFF00` (yellow), close=`0xFF0000` (red)
- Implement `notifier.py`:
  - `send_discord(embed)` → async POST via httpx
  - `send_telegram(message)` → logs "Telegram not yet implemented, skipping"
  - Retry once on HTTP 5xx, log and continue on failure

**Test — `tests/test_alerts.py`:**
- Test `build_open_alert` contains ticker, strike, option type, avg cost
- Test `build_update_alert` contains old price, new price, pct change, est. P&L
- Test `build_close_alert` contains P&L, hold duration
- Test all embeds have correct color field
- Test dollar formatting ($3.20, not $3.2000)

**Test — `tests/test_notifier.py`:**
- Test `send_discord` calls httpx POST with correct URL and payload (mock httpx)
- Test `send_discord` logs error and does not raise on HTTP 500
- Test `send_telegram` logs skip message and returns without error

**Done when:** Running `python notifier.py` sends a test embed to Discord. All tests pass.

---

### Phase 6 — Main Tracker Loop

**Goal:** Wire all modules into the polling loop. Full end-to-end flow.

**Tasks:**
- Implement `tracker.py` as async main loop
- On startup: `init_db()`, validate config, log startup message to Discord
- Poll every `POLL_INTERVAL_SECONDS`, implement state diff logic (see above)
- Graceful shutdown: catch `SIGINT`, log "Tracker shutting down", exit cleanly
- Log every poll tick in development mode, silent in production unless event detected

**Test — `tests/test_tracker.py`:**
- Test new position triggers open alert + DB insert (mock SnapTrade + Discord)
- Test existing position with >threshold% move triggers update alert
- Test existing position with <threshold% move triggers NO alert
- Test position missing from SnapTrade triggers close alert + DB update
- Test no positions returns no alerts
- Test duplicate detection: same position across 2 polls only alerts once

**Done when:** Full integration test passes. Bot runs locally, detects mock position changes, sends correct Discord alerts.

---

### Phase 7 — Deployment + README

**Goal:** Deploy to Render, write replication guide.

**Tasks:**
- Create `render.yaml` as Render worker service config
- Test cold start (fresh DB, first-time SnapTrade registration flow)
- Write `README.md` with:
  - What it does (3 sentences)
  - Prerequisites (SnapTrade dev account, Discord webhook)
  - Step-by-step setup (clone → `.env` → deploy)
  - Screenshot of each alert type
  - Customization guide (threshold, poll interval)
  - Telegram section marked "coming soon"

**render.yaml:**
```yaml
services:
  - type: worker
    name: deltaSimple
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: python tracker.py
    envVars:
      - key: SNAPTRADE_CLIENT_ID
        sync: false
      - key: SNAPTRADE_CONSUMER_KEY
        sync: false
      - key: SNAPTRADE_USER_ID
        sync: false
      - key: SNAPTRADE_USER_SECRET
        sync: false
      - key: DISCORD_WEBHOOK_URL
        sync: false
      - key: POLL_INTERVAL_SECONDS
        value: 30
      - key: PRICE_ALERT_THRESHOLD_PCT
        value: 5.0
```

**Done when:** Bot running on Render, README allows a stranger to set it up in under 15 minutes.

---

## Git Safety — Never Commit Sensitive Data

### `.gitignore` (must be created in Phase 1 before first commit)

```gitignore
# Secrets
.env
*.env
.env.*
!.env.example

# Database
*.db
*.sqlite
*.sqlite3

# Python
__pycache__/
*.py[cod]
*.pyo
.pytest_cache/
.mypy_cache/
dist/
build/
*.egg-info/
.eggs/

# Virtual environments
.venv/
venv/
env/

# uv
.uv/

# Logs
*.log
logs/

# OS
.DS_Store
Thumbs.db

# IDE
.vscode/
.idea/
*.swp
```

### Pre-commit Hook (Phase 1 task)

Create `.git/hooks/pre-commit` to block accidental secret commits:

```bash
#!/bin/sh
# Block commits containing likely secrets

PATTERNS="SNAPTRADE_CLIENT_ID=\w\|SNAPTRADE_CONSUMER_KEY=\w\|DISCORD_WEBHOOK_URL=https\|TELEGRAM_BOT_TOKEN=\w"

if git diff --cached | grep -q "$PATTERNS"; then
  echo "❌ Commit blocked: possible credentials detected in staged changes."
  echo "   Check your diff — never commit real keys or webhook URLs."
  echo "   Only .env.example with placeholder values should be committed."
  exit 1
fi
```

Run `chmod +x .git/hooks/pre-commit` after creating it.

### Rules
- `.env` is **always** gitignored — never commit it under any name except `.env.example`
- `.env.example` contains **only placeholder values** — no real keys, ever
- `tracker.db` is gitignored — contains position state, not for version control
- If `SNAPTRADE_USER_SECRET` gets written to `.env` at runtime, it stays local only
- Never log full credentials even in debug mode — `config.py` must mask secrets in output
- Before first push: run `git status` and verify only safe files are staged

---

## General Rules for Claude Code

- Build one phase at a time. Do not start Phase N+1 until tests for Phase N pass.
- Never hardcode credentials. Everything goes through `config.py`.
- `config.py` must mask secrets when printing config (e.g. show only last 4 chars of keys).
- All functions must have docstrings.
- Use `loguru` for all logging — no `print()` statements in production code.
- Keep modules single-responsibility — no cross-imports except through defined interfaces.
- Mock all external calls (SnapTrade, yfinance, httpx) in tests — no real network calls.
- If a SnapTrade response field is missing or malformed, log the raw response and skip the position rather than crashing.
- Telegram references should exist as stubs only — `notifier.py` logs skip, nothing more.
