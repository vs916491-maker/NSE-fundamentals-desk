# NSE Fundamentals Desk — project notes

Owner: Vivek (GitHub `vs916491-maker`). Personal analysis only, not investment advice.
Repo: `vs916491-maker/NSE-fundamentals-desk` (public). Site: https://vs916491-maker.github.io/NSE-fundamentals-desk/
Kept as a **separate site** on purpose (not a tab inside F&O Desk).

## What it is
Daily digest of NSE corporate filings for all listed stocks, plus a nightly email. NSE data only (yfinance dropped). Free tools only.

## Tabs
- **Today** – tagged announcement feed (orders won, penalties, buybacks, rating changes, red flags), FII/DII daily summary at top; "partial day" note after the 2 PM refresh
- **Results** – quarterly results with YoY / QoQ and verdicts, sortable
- **Holdings** – quarterly shareholding changes (promoter / FII / DII / MF)
- **Deals** – bulk/block deals
- **FII/DII Adding** – stocks institutions are buying via bulk/block deals, ranked over 7/30/90 days
- **FII/DII Activity** – cash + index F&O trend charts with short-term and swing bullish/bearish verdicts
- **Stock** – per-symbol timeline + fundamentals (P/E, margins, growth, quality flags)
- **News** – market headlines from RSS feeds, hourly 8 AM–11 PM
- **Watchlist** – private, Supabase table `fd_watchlist`, shared with Sector Strength (the F&O Desk has its own separate watchlist)
- **Refresh** button – runs an on-demand refresh (needs sign-in)

## Main files
- `collector/run.py` – main job; `nse.py` (NSE session with cookie warm-up), `tagger.py` (tags announcements), `xbrl.py` (results + shareholding XBRL), `flows.py` (FII/DII), `fundamentals.py` (per-stock records), `news.py`, `mailer.py`
- `cache/` – year-ago and previous-quarter filings, fetched once and kept
- `control/request.json` – edit + push for a manual run (e.g. `--date 2026-10-23 --force-email`, `--backfill <from> <to> --budget 120`)
- `site/` – plain HTML/CSS/JS; `site/data/` JSON is committed and published
- `supabase/001_watchlist.sql`, `002_refresh_button.sql`, `003_news_schedule.sql`

## Schedule (IST)
- `collect.yml`: 14:00 (2 PM refresh), 18:45 (end-of-day + email), 20:00 (fallback, skips if done). Supabase pg_cron also starts the evening run with `--email` and a late run at ~23:30 for late filers.
- Email sent **only after the end-of-day refresh**; by 10 PM is fine.
- `news.yml`: hourly, 8 AM–11 PM (Supabase starts it; GitHub cron is backup).
- Shared Supabase project, token and scheduling pattern: see F&O Desk notes.

## Key NSE endpoints (all work from GitHub runners)
- `/api/corporate-announcements` – daily filings
- `/api/integrated-filing-results` – results XBRL (old `corporates-financial-results` stopped updating in 2025)
- `/api/corporate-share-holdings-master` – shareholding XBRL
- `/api/historicalOR/bulk-block-short-deals?csv=true` – bulk/block deals (full day)
- `/api/fiidiiTradeReact` – FII/DII cash; `fii_stats_DD-Mon-YYYY.xls` – FII derivatives
- Needs cookie warm-up (homepage first); `curl_cffi` with Chrome impersonation, `requests` as fallback

## Secrets
`GMAIL_USER`, `GMAIL_APP_PASSWORD` (optional `EMAIL_TO`); email goes to his own Gmail.

## Rules / decisions to keep
- Automated tagging and amounts can be wrong; always open the filing.
- Stock names link to TradingView.

## How to ask for changes
Give: tab name, what's wrong or wanted, and a screenshot or symbol + date. Keep changes small.
