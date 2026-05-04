# optionsminer

Self-hosted options analytics dashboard for SPY and SPX. Pulls option chains from Yahoo Finance,
snapshots them to SQLite, and exposes a set of practitioner-focused signals through a Streamlit UI.

Built to be deployed to a self-hosted [Coolify](https://coolify.io) instance via GitHub.

## Signals computed

| Signal | What it tells you |
|---|---|
| Black-Scholes greeks (delta, gamma, vega, theta, charm, vanna) | Per-strike risk, recomputed from mid quotes |
| **Gamma Exposure (GEX)** + zero-gamma flip | Dealer hedging regime — above flip = vol suppression, below = vol expansion |
| **IV skew** (25Δ risk reversal, 90/110 moneyness) | Crash fear vs upside chase |
| **IV term structure** (7D / 30D / 90D ATM) | Backwardation = acute stress, steep contango = complacency |
| **Volatility risk premium (VRP)** | IV − realised vol (Yang-Zhang) — premium-selling regime indicator |
| **Max pain** + OI / gamma walls | Confluence levels for pin / support / resistance |
| **Put/Call ratio** (volume + OI) | Sentiment, with equity vs index distinction |
| **Unusual options activity** | Volume / OI &gt; threshold filters within yfinance limits |
| **Implied move** | Straddle-derived expected move into expiry |

## Stack

- Python 3.12, [`uv`](https://docs.astral.sh/uv/) for env + dependency management
- `streamlit` UI, `plotly` charts
- `yfinance` data source (with a `DataProvider` abstraction so Schwab / Polygon / Tradier can slot in later)
- `SQLAlchemy` over SQLite for snapshot history
- Disk-usage guard with a configurable cap (default 150 GB) and oldest-first auto-prune
- Dockerised for one-shot Coolify deploy

## Local development

```bash
# Install deps (creates .venv, downloads Python 3.12 if needed)
uv sync

# Initialise the SQLite schema
uv run optionsminer-init-db

# Take an EOD snapshot of SPY + SPX option chains
uv run optionsminer-snapshot

# Run the dashboard
uv run streamlit run src/optionsminer/ui/app.py
```

The app will be available at <http://localhost:8501>.

## Deployment to Coolify

The repo includes a multi-stage `Dockerfile` and a reference `compose.yaml`.
Two valid paths in the Coolify dashboard:

### Path A — Dockerfile build pack (simpler)

1. New Resource → Public Repository → paste `https://github.com/norsay-cap/optionsminer`
2. Build pack: **Dockerfile**
3. Port: `8501`
4. Domain: `optionsminer.<yourdomain>` (your wildcard DNS already covers it)
5. Persistent storage: add a volume mount at `/app/data` (this is where SQLite lives — without it, every redeploy wipes your history)
6. Environment variables (all optional, defaults shown):
   ```
   OPTIONSMINER_DISK_CAP_GB=150
   OPTIONSMINER_DISK_WARN_PCT=0.80
   OPTIONSMINER_RISK_FREE_RATE=0.045
   OPTIONSMINER_TICKERS=["SPY","^SPX"]
   OPTIONSMINER_ENABLE_SCHEDULER=true
   OPTIONSMINER_SCHEDULE_TZ=America/New_York
   OPTIONSMINER_SCHEDULE_CRON=0 23 * * sun,mon,tue,wed,thu
   ```

   **Note on the cron syntax:** APScheduler uses a non-POSIX day-of-week
   numbering (0=Mon..6=Sun). To avoid surprises, always specify weekdays as
   lowercase **names** (`sun,mon,tue,wed,thu`) rather than numeric ranges
   (`0-4` does NOT mean Sun-Thu in APScheduler — it means Mon-Thu).
7. Deploy. Healthcheck (`GET /_stcore/health`) is already built into the image.

### Path B — Docker Compose build pack

Use `compose.yaml` as-is. Coolify reads it directly and provisions the named volume `optionsminer_data`.

### Snapshot scheduling

With `OPTIONSMINER_ENABLE_SCHEDULER=true`, the container runs an in-process APScheduler that calls `optionsminer-snapshot` and records today's DT15 prediction on the configured cron. Default is `0 23 * * sun,mon,tue,wed,thu` in `America/New_York` = **11 PM ET on Sun-Thu evenings**. Each evening's run captures the 6 PM ET ETH session open of the upcoming trading day (Sun → Mon's anchor, Mon → Tue's, etc.), giving yfinance ~5 hours past the open to publish the new bar. The `America/New_York` timezone means DST is handled automatically — the run time stays at 11 PM ET year-round.

If you'd rather run snapshots externally, leave the scheduler off and use Coolify's scheduled-tasks feature, or `docker exec` `optionsminer-snapshot` from a host cron.

## Data source caveats

Yahoo Finance options data is delayed, snapshot-style, and lacks NBBO / trade tape. This means:

- IV and greeks are recomputed from mid quotes (yfinance's own IVs are inconsistent)
- 0DTE intraday GEX, sweep detection, and aggressor classification are **not** possible from yfinance alone
- All "EOD" analytics (skew, GEX, max pain, walls, VRP, PCR) work fine

The roadmap is to swap the `YahooProvider` for a `SchwabProvider` once broker access is wired up.

## Disk-space guard

SQLite history grows over time. The app includes a guard that:

- Reports current DB size on the dashboard
- Warns at 80% of the configured cap
- Auto-prunes the oldest snapshots (oldest `snapshot_ts` first) when usage exceeds the cap

Default cap is 150 GB. Override via `OPTIONSMINER_DISK_CAP_GB`.

## Methodology reference

For the DT15 daily-range estimator (R1 / TSPL kernel / dynamic M multipliers,
parameter inventory, σ_R1 stability investigation, and the rationale for the
rolling-σ implementation), see [`dt15_methodology.md`](dt15_methodology.md).

## Licence

MIT
