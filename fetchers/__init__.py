"""
Harmonica Price Tracker — Fetchers Package
============================================
Re-exports key fetcher functions used by scraper.py's crawl_all() and main().
"""

from fetchers.firecrawl_fetcher import (
    _fetch_dm_via_firecrawl,
    _fetch_randi_via_firecrawl,
    _fetch_store_via_firecrawl,
    _fetch_lilly_via_firecrawl,
    _fetch_tmarket_via_firecrawl,
)

from fetchers.crawl4ai_fetcher import (
    solve_turnstile,
    crawl_with_captcha_solver,
    crawl_store,
)

from fetchers.curl_api import (
    extract_algolia_config,
    fetch_dm_via_algolia,
    fetch_lilly_via_curl,
    fetch_tmarket_via_curl,
)

from fetchers.glovo import (
    _fetch_glovo_via_firecrawl,
    _parse_glovo_markdown,
    fetch_glovo_store_products,
    _parse_glovo_products,
    _parse_glovo_catalog,
    fetch_all_glovo_products,
)
