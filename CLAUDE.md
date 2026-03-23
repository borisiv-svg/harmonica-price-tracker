# CLAUDE.md — Harmonica Price Tracker
 
## What this is
 
Weekly price scraper for **119 Harmonica-brand products** across 14+ Bulgarian online stores. Runs every Monday 07:00 EET via GitHub Actions. Outputs to Google Sheets → email to Galya and the sales team.
 
We track only Harmonica brand products, not everything in the Kashon catalog (191 total, 119 are Harmonica).
 
## Architecture
 
```
scraper.py        → Main orchestration (entry point)
config.py         → Store configs, API keys, feature flags
validation.py     → Claude Sonnet 4.5 outlier detection
matching.py       → Levenshtein-based product matching with weighted normalization
utils.py          → Price extraction (regex), BGN/EUR conversion, retry logic
fetchers/         → Firecrawl, Crawl4AI, Glovo, curl_cffi
extractors/       → One parser per store (Kashon, eBag, Balev, T-Market, Metro, etc.)
output/sheets.py  → Google Sheets write via gspread
data/             → products.json, price history, run history
```
 
## Critical rules
 
### Currency — the #1 source of bugs
 
- **Fixed rate: 1 EUR = 1.95583 BGN.** Hardcoded. Never fetch dynamically.
- Bulgaria adopted EUR on 1 January 2026. Many stores still show BGN prices with EUR symbols.
- **All Glovo prices are BGN.** Always convert. No exceptions.
- The BGN-as-EUR detection has 4 layers — do not bypass or simplify them:
  1. Kashon-based: price >1.7× Kashon reference → likely BGN
  2. ref_eur fallback from data/products.json when no Kashon price
  3. Cross-store median: flag prices >70% above median
  4. EUR/BGN regex cross-validation
- In price regex: use `[ \t]*` not `\s*` — `\s` matches newlines and breaks multi-line extraction.
 
### Fetcher cascade
 
Firecrawl → Crawl4AI → curl_cffi. Do not change the fallback order without testing all stores.
 
- **Firecrawl** (paid, credits expiring April 2026): Randi, T-Market, DM, Zelen, BeFit, Glovo
- **Crawl4AI** (free, headless Chromium): primary fallback for all
- **curl_cffi**: TLS impersonation for Cloudflare (T-Market fallback)
- **Glovo API is reverse-engineered / unofficial.** It can break without warning. Handle failures gracefully.
 
### Data quality gate
 
- Dry-run pre-check: test scrape 3 stores before production
- If <40% of stores return data → do NOT write to Sheets
- Monthly product sync from Kashon on first Sunday of month
 
### Store extractors
 
Each store has its own parser in `extractors/`. When a store changes its HTML:
1. Fix the specific extractor — don't change the matching or orchestration logic
2. Run `pytest` — all 199 tests must pass
3. Test with `workflow_dispatch` before waiting for Monday cron
 
### AI validation
 
- Model: `claude-sonnet-4-5-20250514` via Anthropic API
- Flags outliers >50% deviation from median as ГРЕШНА / ВЯРНА / СЪМНИТЕЛНА
- Provides EUR/100g context for accuracy
- Cost: ~$0.06/run — do not switch to Opus, Sonnet is sufficient here
 
## Secrets (GitHub Actions)
 
```
ANTHROPIC_API_KEY          — Claude Sonnet 4.5 for validation
FIRECRAWL_API_KEY          — JS-heavy stores (expiring April 2026)
GOOGLE_SERVICE_ACCOUNT_JSON — gspread auth
NOTIFICATION_EMAIL         — error alerts
```
 
## Common mistakes — do not repeat
 
- Do not assume a price with € symbol is actually EUR. Always run through BGN detection.
- Do not add `\s` to price regex patterns — it matches newlines.
- Do not skip the data quality gate for "just this one run."
- Do not modify `matching.py` thresholds without re-running the full test suite.
- Do not hardcode store URLs in scraper.py — they belong in config.py.
- When adding a new store: create extractor in `extractors/`, add config in `config.py`, add tests, test via dry-run.
 
## Tech stack
 
Python 3.11+, Crawl4AI 0.8.0, Firecrawl 1.17.0, curl_cffi 0.14.0, BeautifulSoup 4.12.3, gspread 6.1.0, pytest, GitHub Actions (cron weekly + workflow_dispatch manual).
