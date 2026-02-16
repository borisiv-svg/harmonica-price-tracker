"""
Harmonica Price Tracker — Firecrawl Fetchers
==============================================
Firecrawl-based fetchers for DM, Randi, Lilly, T-Market, and generic stores.
Synchronous functions — designed to run in thread pools via asyncio.run_in_executor().
"""

import re
import time

from config import FIRECRAWL_AVAILABLE, FIRECRAWL_API_KEY, STORES, logger

if FIRECRAWL_AVAILABLE:
    from firecrawl import FirecrawlApp

from extractors import (
    extract_dm_from_curl_html, extract_dm_products,
    extract_randi_products, extract_lilly_products, extract_tmarket_products,
)
from utils import is_food_product, is_harmonica_product


def _fetch_dm_via_firecrawl(query="harmonica"):
    """
    Firecrawl: рендерира DM.bg search page с headless browser.
    DM.bg има силна Cloudflare защита, която блокира proxy + curl_cffi.
    Firecrawl използва собствена инфраструктура и може да bypass-не.
    Синхронна функция — ще се изпълнява в thread pool.
    """
    if not FIRECRAWL_AVAILABLE or not FIRECRAWL_API_KEY:
        return None

    start = time.time()
    url = f"https://www.dm-drogeriemarkt.bg/search?query={query}&searchType=product"

    try:
        app = FirecrawlApp(api_key=FIRECRAWL_API_KEY)

        # Firecrawl scrape с wait за JS rendering
        # DM е тежък JS сайт (Cloudflare + SPA) — 90s timeout
        result = app.scrape_url(
            url,
            params={
                "formats": ["markdown", "html"],
                "actions": [
                    {"type": "wait", "milliseconds": 5000},
                    {"type": "scroll", "direction": "down"},
                    {"type": "wait", "milliseconds": 3000},
                    {"type": "scroll", "direction": "down"},
                    {"type": "wait", "milliseconds": 2000},
                    {"type": "scrape"},
                ],
                "timeout": 90000,
            },
        )
        elapsed = time.time() - start

        markdown = ""
        html = ""
        if isinstance(result, dict):
            markdown = result.get("markdown", "")
            html = result.get("html", "")
        elif hasattr(result, "markdown"):
            markdown = result.markdown or ""
            html = getattr(result, "html", "") or ""

        if not markdown and not html:
            logger.info(f"DM Firecrawl: празен резултат ({elapsed:.1f}s)")
            return None

        # Парсване на продукти от HTML/markdown
        products = []
        if html:
            products = extract_dm_from_curl_html(html)
        if not products and markdown:
            products = extract_dm_products(markdown, html_text=html)

        logger.info(f"DM Firecrawl: {len(products)} продукта ({elapsed:.1f}s)")

        if products:
            return {
                "success": True,
                "method": "firecrawl",
                "products": products,
                "elapsed": elapsed,
                "html": html,
            }

        # Firecrawl успя, но не можахме да парснем продукти
        harmonica_refs = len(re.findall(r'(?i)harmonica|хармоника', markdown))
        logger.info(f"DM Firecrawl: 0 парсирани, {harmonica_refs} refs в markdown ({elapsed:.1f}s)")
        return {
            "success": True,
            "method": "firecrawl",
            "products": [],
            "html": html,
            "markdown": markdown,
            "elapsed": elapsed,
        }

    except Exception as e:
        elapsed = time.time() - start
        logger.warning(f"DM Firecrawl грешка: {e} ({elapsed:.1f}s)")
        return None


# =============================================================================
# RANDI FIRECRAWL FETCH
# =============================================================================

def _fetch_randi_via_firecrawl():
    """
    Firecrawl: рендерира Randi.bg search page с headless browser.
    Randi.bg зарежда продуктите с JS — Crawl4AI не улавя всичко.
    Синхронна функция — ще се изпълнява в thread pool.
    """
    if not FIRECRAWL_AVAILABLE or not FIRECRAWL_API_KEY:
        return None

    start = time.time()
    url = "https://randi.bg/search?search=harmonica"

    try:
        app = FirecrawlApp(api_key=FIRECRAWL_API_KEY)

        result = app.scrape_url(
            url,
            params={
                "formats": ["markdown"],
                "actions": [
                    {"type": "wait", "milliseconds": 4000},
                    {"type": "scroll", "direction": "down", "amount": 8},
                    {"type": "wait", "milliseconds": 3000},
                    {"type": "scrape"},
                ],
                "timeout": 90000,
            },
        )
        elapsed = time.time() - start

        markdown = ""
        if isinstance(result, dict):
            markdown = result.get("markdown", "")
        elif hasattr(result, "markdown"):
            markdown = result.markdown or ""

        if not markdown:
            logger.info(f"Randi Firecrawl: празен резултат ({elapsed:.1f}s)")
            return None

        products = extract_randi_products(markdown)
        logger.info(f"Randi Firecrawl: {len(products)} продукта ({elapsed:.1f}s)")

        if products:
            return {
                "success": True,
                "method": "firecrawl",
                "products": products,
                "elapsed": elapsed,
                "markdown": markdown,
            }

        harmonica_refs = len(re.findall(r'(?i)harmonica|хармоника', markdown))
        logger.info(f"Randi Firecrawl: 0 парсирани, {harmonica_refs} refs в markdown ({elapsed:.1f}s)")
        return {
            "success": True,
            "method": "firecrawl",
            "products": [],
            "markdown": markdown,
            "elapsed": elapsed,
        }

    except Exception as e:
        elapsed = time.time() - start
        logger.warning(f"Randi Firecrawl грешка: {e} ({elapsed:.1f}s)")
        return None


# =============================================================================
# UNIVERSAL FIRECRAWL FETCH — за всички магазини
# =============================================================================

def _fetch_store_via_firecrawl(store_key, store_config):
    """
    Универсален Firecrawl fetch за произволен магазин.
    Използва Firecrawl headless browser за рендериране на JS-heavy страници.
    Синхронна функция — ще се изпълнява в thread pool.

    Връща dict с success, method, markdown, html, elapsed или None при грешка.
    """
    if not FIRECRAWL_AVAILABLE or not FIRECRAWL_API_KEY:
        return None

    store_name = store_config["name"]
    url = store_config["url"]
    scroll_times = store_config.get("scroll_times", 5)
    start = time.time()

    try:
        app = FirecrawlApp(api_key=FIRECRAWL_API_KEY)

        # Изграждаме actions: wait → scroll → wait → scrape
        # Firecrawl лимити: max 50 actions, max 60s общо wait
        scroll_wait = store_config.get("scroll_delay", 1500)
        initial_wait = 4000
        # Бюджет: 50 actions = 1 (init wait) + 2N (scroll+wait) + 1 (final scroll) + 1 (final wait) + 1 (scrape) = 2N+4
        max_scrolls_by_actions = (50 - 4) // 2  # = 23
        # Бюджет: 60s wait = initial_wait + N * scroll_wait + scroll_wait (final)
        max_scrolls_by_wait = max(1, int((60000 - initial_wait - scroll_wait) / scroll_wait))
        firecrawl_scrolls = min(scroll_times, max_scrolls_by_actions, max_scrolls_by_wait)

        actions = [
            {"type": "wait", "milliseconds": initial_wait},
        ]
        # Pre-actions (напр. затваряне на overlay/popup) — ако са зададени
        pre_actions = store_config.get("firecrawl_pre_actions", [])
        actions.extend(pre_actions)
        for _ in range(firecrawl_scrolls):
            actions.append({"type": "scroll", "direction": "down"})
            actions.append({"type": "wait", "milliseconds": scroll_wait})
        # Финален scroll до дъното
        actions.append({"type": "scroll", "direction": "down"})
        actions.append({"type": "wait", "milliseconds": scroll_wait})
        actions.append({"type": "scrape"})

        if firecrawl_scrolls < scroll_times:
            logger.info(f"{store_name} Firecrawl: {firecrawl_scrolls}/{scroll_times} scrolls "
                        f"(лимит actions/wait), Crawl4AI ще обхване пълния обхват")

        # Timeout: базов 60s + scroll_times × scroll_wait
        timeout = max(90000, 60000 + firecrawl_scrolls * scroll_wait * 2)
        result = app.scrape_url(
            url,
            params={
                "formats": ["markdown", "html"],
                "actions": actions,
                "timeout": timeout,
            },
        )
        elapsed = time.time() - start

        markdown = ""
        html = ""
        if isinstance(result, dict):
            markdown = result.get("markdown", "")
            html = result.get("html", "")
        elif hasattr(result, "markdown"):
            markdown = result.markdown or ""
            html = getattr(result, "html", "") or ""

        if not markdown and not html:
            logger.info(f"{store_name} Firecrawl: празен резултат ({elapsed:.1f}s)")
            return None

        logger.info(f"{store_name} Firecrawl: OK {elapsed:.1f}s, "
                     f"{len(markdown)} md chars, {len(html)} html chars")

        return {
            "success": True,
            "store_key": store_key,
            "method": "firecrawl",
            "markdown": markdown,
            "html": html,
            "elapsed": elapsed,
            "scrolls_capped": firecrawl_scrolls < scroll_times,
        }

    except Exception as e:
        elapsed = time.time() - start
        logger.warning(f"{store_name} Firecrawl грешка: {e} ({elapsed:.1f}s)")
        return None


def _fetch_lilly_via_firecrawl():
    """
    Firecrawl fetch за Lilly — специализиран, защото Lilly е Magento 2 с Hyvä Theme.
    Опитва да извлече продукти от HTML (JSON-LD, BS4) преди да върне markdown.
    """
    if not FIRECRAWL_AVAILABLE or not FIRECRAWL_API_KEY:
        return None

    store_config = STORES.get("lilly", {})
    result = _fetch_store_via_firecrawl("lilly", store_config)
    if not result or not result.get("success"):
        return result

    # Опитваме да извлечем продукти директно от HTML
    html = result.get("html", "")
    markdown = result.get("markdown", "")
    products = []
    if html:
        products = extract_lilly_products(markdown, html_text=html)
    elif markdown:
        products = extract_lilly_products(markdown)

    if products:
        result["products"] = products
        logger.info(f"Lilly Firecrawl: {len(products)} продукта извлечени")

    return result


def _fetch_tmarket_via_firecrawl():
    """Firecrawl fetch за T-Market — CloudCart + Cloudflare."""
    if not FIRECRAWL_AVAILABLE or not FIRECRAWL_API_KEY:
        return None

    store_config = STORES.get("tmarket", {})
    result = _fetch_store_via_firecrawl("tmarket", store_config)
    if not result or not result.get("success"):
        return result

    html = result.get("html", "")
    markdown = result.get("markdown", "")
    products = extract_tmarket_products(
        markdown, html_text=html if html else None,
        brand_page=store_config.get("brand_page", True),
    )
    if products:
        result["products"] = products
        logger.info(f"T-Market Firecrawl: {len(products)} продукта извлечени")

    return result
