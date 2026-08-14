# CLAUDE.md — Harmonica Price Tracker

## What this is

Weekly price scraper for **Harmonica-brand products** (130 tracked, 87 currently active) across 14+ Bulgarian online stores. Runs every Monday 07:00 EET via GitHub Actions. Outputs to Google Sheets → email to Galya and the sales team.

We track only Harmonica brand products, not everything in the Kashon catalog (191 total, 119 are Harmonica).

## Architecture

```
scraper.py          → Main orchestration (entry point, ~770 lines)
config.py           → Store configs, API keys, feature flags (228 lines)
validation.py       → Claude Sonnet outlier detection (215 lines)
matching.py         → Levenshtein-based product matching with weighted normalization (114 lines)
utils.py            → Price extraction (regex), BGN/EUR conversion, retry logic (360 lines)
fetchers/           → Firecrawl, Crawl4AI, Glovo, curl_cffi (4 modules, ~1500 lines)
extractors/         → One parser per store: Kashon, eBag, Balev, T-Market, Metro, Randi, Lilly, DM, Generic (9+1 modules)
output/sheets.py    → Google Sheets write via gspread (637 lines)
output/email_report.py → Email notifications (172 lines)
products.py         → Product list management (164 lines)
price_history.py    → Price history tracking (107 lines)
run_history.py      → Run history & health checks (183 lines)
data/               → products.json (119 products), price_history.json, run_history.json
scripts/            → monthly_product_sync.py (Kashon sync)
tests/              → 211 tests across 11 files + 8 fixture files
```

## Critical rules

### Currency — the #1 source of bugs

- **Fixed rate: 1 EUR = 1.95583 BGN.** Hardcoded in `config.py` as `EUR_BGN_RATE`. Never fetch dynamically.
- Bulgaria adopted EUR on 1 January 2026. Many stores still show BGN prices with EUR symbols.
- **All Glovo prices are BGN.** Always convert. No exceptions.
- The BGN-as-EUR detection has 4 layers — do not bypass or simplify them:
  1. Kashon-based: price >1.7× Kashon reference → likely BGN
  2. ref_eur fallback from data/products.json when no Kashon price
  3. Cross-store median: flag prices >70% above median (uses true median for even-length lists)
  4. EUR/BGN regex cross-validation via `validate_eur_bgn()`
- In price regex: use `[ \t]*` not `\s*` — `\s` matches newlines and breaks multi-line extraction.
- **Consequence of the rule above:** `[ \t]` also misses non-breaking spaces. Stores serve `1,49\xa0€`, so `extract_eur_price()` silently returns `None`. Normalize whitespace in the extractor *before* calling it (`re.sub(r"\s+", " ", text)` — Python's `\s` does match `\xa0`). This broke the eBag run of 10.08.2026 and is invisible in a browser, where JS `\s` matches `\xa0`.
- Every extraction path must call `validate_eur_bgn()` — including JSON-LD and structured data paths.

### Fetcher cascade

Firecrawl → Crawl4AI → curl_cffi. Do not change the fallback order without testing all stores.

- **Firecrawl** (paid, credits expiring April 2026): Randi, T-Market, DM, Zelen, BeFit, Glovo
- **Crawl4AI** (free, headless Chromium): primary fallback for all
- **curl_cffi**: TLS impersonation for Cloudflare (T-Market fallback)
- **Glovo API is reverse-engineered / unofficial.** It can break without warning. Handle failures gracefully.
- DM has no Crawl4AI fallback — only Firecrawl. Consider adding one.

### Data quality gate

- Dry-run pre-check: test scrape 3 stores (Kashon + eBag + Balev) before production
- If <40% of stores return data → do NOT write to Sheets
- Monthly product sync from Kashon on first Sunday of month

### Store extractors

Each store has its own parser in `extractors/`. When a store changes its HTML:
1. Fix the specific extractor — don't change the matching or orchestration logic
2. Run `pytest` — all 211 tests must pass
3. Test with `workflow_dispatch` before waiting for Monday cron

**Tested extractors:** Kashon, eBag, Balev, Metro, Randi, Generic
**Untested extractors (need tests):** Lilly, DM, T-Market

### AI validation

- Model: `claude-sonnet-4-5-20250929` via Anthropic API (`CLAUDE_MODEL` in `config.py`)
- Flags outliers >50% deviation from median as ГРЕШНА / ВЯРНА / СЪМНИТЕЛНА
- Provides EUR/100g context for accuracy
- Cost: ~$0.06/run — do not switch to Opus, Sonnet is sufficient here

## Secrets (GitHub Actions)

```
ANTHROPIC_API_KEY   — Claude Sonnet for validation
FIRECRAWL_API_KEY   — JS-heavy stores (expiring April 2026)
GOOGLE_CREDENTIALS  — gspread service account JSON
SPREADSHEET_ID      — target Google Sheet
GLOVO_AUTH_TOKEN    — optional Glovo bearer token
GMAIL_USER          — report sender
GMAIL_APP_PASSWORD  — report sender auth
ALERT_EMAIL         — error alerts
```

## Known issues & tech debt

- **History sheet overflow**: `sheets.py` creates history tab with 5000 rows — will fill up after ~57 weeks. Needs auto-expansion or rotation.
- **Firecrawl migration needed**: `firecrawl-py==1.17.0` expires April 2026; 2.x has breaking changes.
- **`asyncio.get_event_loop()`** in `scraper.py` — deprecated since Python 3.10+, should migrate to `asyncio.run()`.
- **GitHub Actions Node.js 20 deprecation**: `actions/checkout@v4`, `actions/setup-python@v5`, `actions/upload-artifact@v4` will need updates by June 2026.
- **Silent exception** in `curl_api.py:140` — JS bundle fetch errors swallowed without logging.
- **Unused imports**: 6 extractors import `logger` without using it.

## Common mistakes — do not repeat

- Do not assume a price with € symbol is actually EUR. Always run through BGN detection.
- Do not add `\s` to price regex patterns — it matches newlines. But do normalize whitespace on the text you pass in, or non-breaking spaces will silently kill the match.
- Do not assume a displayed price belongs to the pack size in the reference list. eBag prices only the *selected* variant of a size switcher and defaults to the multipack — see `_multipack_is_priced()` in `extractors/ebag.py`.
- Do not skip the data quality gate for "just this one run."
- Do not modify `matching.py` thresholds without re-running the full test suite.
- Do not hardcode store URLs in scraper.py — they belong in config.py.
- Do not skip `validate_eur_bgn()` in any extraction path — including JSON-LD, API responses, and structured data.
- When calculating median for price comparison, use true median (average of two middle values for even-length lists), not just `values[len//2]`.
- When adding a new store: create extractor in `extractors/`, add config in `config.py`, add tests, test via dry-run.
- When using temp files for credentials, always clean up in a `finally` block.

## Tech stack

Python 3.11+, Crawl4AI 0.8.0, Firecrawl 1.17.0, curl_cffi 0.14.0, BeautifulSoup 4.12.3, gspread 6.1.0, anthropic 0.79.0, pytest, GitHub Actions (cron weekly + workflow_dispatch manual).
