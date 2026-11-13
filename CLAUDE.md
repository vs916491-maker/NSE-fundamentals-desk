# NSE Fundamentals Desk — project notes

Owner: Vivek (GitHub `vs916491-maker`). Personal analysis only, not investment advice.
Repo: `vs916491-maker/NSE-fundamentals-desk` (public). Site: https://vs916491-maker.github.io/NSE-fundamentals-desk/
Kept as a **separate site** on purpose (not a tab inside F&O Desk).

## What it is
Daily digest of NSE corporate filings for all listed stocks, plus a nightly email. NSE data only (yfinance dropped). Free tools only.

## Tabs
- **Ideas** – 1-year investment ideas and industry themes (`collector/ideas.py`, data `ideas.json` + `ideas_log.json`): stocks ≥ ₹500 cr scored on earnings 40, orders 15, ownership 20, institutional buying 10, valuation 15; idea = 65+ with 3 of 5 groups at half marks; theme cards (groupings in `collector/themes.csv`); price-timing label and theme stage read live from Sector Strength (`docs` table, needs sign-in); track record vs Nifty 500 at 3/6/12 months
- **Today** – tagged announcement feed (orders won, penalties, buybacks, rating changes, red flags), FII/DII daily summary at top; "partial day" note after the 2 PM refresh
- **Results** – quarterly results with YoY / QoQ and verdicts, sortable
- **Holdings** – quarterly shareholding changes (promoter / FII / DII / MF)
- **Deals** – bulk/block deals
- **FII/DII Adding** – stocks institutions are buying via bulk/block deals, ranked over 7/30/90 days
- **FII/DII Activity** – cash + index F&O trend charts with short-term and swing bullish/bearish verdicts
- **Stock Screener** (tab renamed 13 Nov 2026; hash still `#stock`) – per-symbol timeline + fundamentals (P/E, run-rate P/E, margins, growth, quality flags); header search box (symbol or company name) opens it from any tab; **About** box (theme, NSE industry, 2-line AI-written description) and **Policy & Budget watch** (sector-level government/regulator headlines with a rough tailwind/headwind guess)
- **News** – market headlines from RSS feeds, hourly 8 AM–11 PM
- **Watchlist** – private, Supabase table `fd_watchlist`, shared with Sector Strength (the F&O Desk has its own separate watchlist)
- **Refresh** button – runs an on-demand refresh (needs sign-in)

## Main files
- `collector/run.py` – main job; `nse.py` (NSE session with cookie warm-up), `tagger.py` (tags announcements), `xbrl.py` (results + shareholding XBRL), `flows.py` (FII/DII), `fundamentals.py` (per-stock records), `news.py`, `mailer.py`
- `collector/ideas.py` – Ideas tab (scoring rules at the top of the file); `industry.py` – stock → NSE industry (`cache/industry.json`); `themes.csv` – industry → theme and theme → Sector Strength index (edit freely)
- `collector/profiles.py` – Stock page About box: industry + theme from `cache/industry.json`, description written once per stock (≥ ₹500 cr, biggest first) by Gemini free tier, kept in `cache/profiles.json`, published to `site/data/profiles/<letter>.json`; runs after Ideas at end of day, `--profiles-only` on demand; picks the newest Flash-Lite/Flash model itself (override with repo variable `GEMINI_MODEL`); stops when the free daily limit is hit and continues next evening
- `collector/policy.py` – Policy & Budget watch (`site/data/policy.json`): Google News search per topic (TOPICS list: theme-wide or narrower by NSE basic industry, e.g. Water & sanitation), headline must name the topic and a policy action; kept 75 days; runs inside `news.yml` about twice a day
- `cache/` – year-ago and previous-quarter filings, fetched once and kept; `ideas_events.json` keeps orders / red flags / penalties / ratings beyond the 120 days of day files
- `control/request.json` – edit + push for a manual run (e.g. `--date 2026-10-23 --force-email`, `--backfill <from> <to> --budget 120`)
- `site/` – plain HTML/CSS/JS; `site/data/` JSON is committed and published
- `supabase/001_watchlist.sql`, `002_refresh_button.sql`, `003_news_schedule.sql`

## Schedule (IST)
- `collect.yml`: 14:00 (2 PM refresh), 18:45 (end-of-day + email), 20:00 (fallback, skips if done). Supabase pg_cron also starts the evening run with `--email` and a late run at ~23:30 for late filers.
- Email sent **only after the end-of-day refresh**; by 10 PM is fine. Includes "Investment ideas: new / dropped".
- Ideas are rebuilt with the end-of-day refresh only (not the 2 PM one); `--ideas-only` rebuilds them on demand.
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
Optional `GEMINI_API_KEY` (free key from Google AI Studio): company descriptions; without it only theme and industry show.
Optional `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (same as the other two repos): lets the Ideas build log Sector Strength's price-timing label for the track record and email.

## Rules / decisions to keep
- Automated tagging and amounts can be wrong; always open the filing.
- Stock names link to TradingView.
- Ideas (decided 5 Nov 2026): 1-year horizon, market cap ≥ ₹500 cr. Price timing (Sector Strength) is shown but kept out of the score so the track record can test it.
- Ideas valuation (5 Nov 2026): run-rate P/E (last 2 quarters' profit × 2) replaces trailing P/E when lower, only for proven growers (profit +25% YoY in both quarters, sales +15%, no one-off/other-income flag). Vivek chose not to make the P/E ÷ growth scale stricter.
- Theme score (7 Nov 2026): orders ignored as a probable misread only if above 3x revenue AND above 1.5x market cap (GRSE's ₹32,000 cr NGC order was being dropped); bulk/block buying ranked as % of the theme's market cap, not ₹ cr, so big themes get no head start. Theme score is still percentile ranks, so a 33% order book scores the same as a 3% one if both rank first.
- Price timing label (7 Nov 2026): "Not tracked" = stock is outside Sector Strength's ~765 stocks (Nifty 500 + Microcap 250, tracked indices, F&O) so no price history exists (24 of 60 ideas on 7 Nov); "No price data" = tracked but no RS rating yet. Vivek chose to label it, not widen Sector Strength's universe (that would shift every RS rating).
- Stock page profile (13 Nov 2026): description = free AI API, cached; tailwinds = theme-level keyword match on news (noisy, labelled as a guess, sector-level not company-level); coverage = market cap ≥ ₹500 cr.

## How to ask for changes
Give: tab name, what's wrong or wanted, and a screenshot or symbol + date. Keep changes small.
