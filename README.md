# NSE Fundamentals Desk

Daily digest of NSE corporate filings for all listed stocks: quarterly results (with YoY / QoQ), orders won,
penalties and regulatory actions, buybacks, rating changes, red flags, shareholding changes (promoter / FII / DII / MF)
and bulk/block deals.

- **Site:** https://vs916491-maker.github.io/NSE-fundamentals-desk/
- **Schedule:** GitHub Actions at 18:50 IST (with email), 19:25 IST (backup) and 23:30 IST (late filers).
- **Email:** sent once a day through Gmail. Needs repo secrets `GMAIL_USER` and `GMAIL_APP_PASSWORD`
  (optional `EMAIL_TO`, otherwise it mails `GMAIL_USER`).

## How it works
`collector/run.py` pulls from NSE's public JSON feeds and archives, tags each announcement
(`collector/tagger.py`), reads quarterly figures and shareholding from the XBRL files (`collector/xbrl.py`), and writes
JSON into `site/data/`. The workflow commits that data and publishes `site/` to GitHub Pages.

Results filings only carry the current quarter, so the year-ago and previous-quarter filings are fetched once and kept
in `cache/`.

## Manual run
Edit `control/request.json` and push, or use *Actions → collect → Run workflow*. Examples:

    --date 2026-10-23 --force-email
    --backfill 2026-10-01 2026-10-11 --budget 120

Automated tagging and amount extraction can be wrong; always open the filing. Not investment advice.
