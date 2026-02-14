"""
Firecrawl Scraper Module for Harmonica Price Tracker v10.0

Замества Playwright + Claude двуфазния анализ с:
1. Firecrawl scrape с actions (за JS-heavy сайтове)
2. Firecrawl structured extraction с JSON schema (за директно извличане на продукти)
3. Fallback към markdown + Claude matching (ако structured extraction не сработи)

Предимства:
- Без нужда от локален browser (Playwright)
- По-малко токени към Claude (markdown вместо HTML)
- Structured extraction елиминира Claude Haiku фазата
- Batch scrape за паралелно обработване на магазини
"""

import os
import re
import json
import time
import logging
from typing import Optional

logger = logging.getLogger('harmonica')

# Firecrawl SDK
try:
    from firecrawl import FirecrawlApp
    FIRECRAWL_AVAILABLE = True
except ImportError:
    FIRECRAWL_AVAILABLE = False
    logger.warning("  [FIRECRAWL] firecrawl-py не е инсталиран")

FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY")

# JSON schema за структурирано извличане на Harmonica продукти
# Firecrawl използва тази schema за AI-базирано извличане директно от HTML
PRODUCT_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "products": {
            "type": "array",
            "description": "Списък с всички хранителни продукти на марката Harmonica (Хармоника) намерени на страницата",
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Пълно име на продукта както е изписано на сайта, включително грамаж/обем"
                    },
                    "price": {
                        "type": "number",
                        "description": "Цена на продукта като число (напр. 2.79), без валутен символ"
                    },
                    "weight": {
                        "type": "string",
                        "description": "Грамаж или обем (напр. '400г', '500мл', '1л', '30г')"
                    },
                    "in_stock": {
                        "type": "boolean",
                        "description": "Дали продуктът е наличен (true ако няма индикация за липса)"
                    }
                },
                "required": ["name", "price"]
            }
        }
    },
    "required": ["products"]
}

# Prompt за structured extraction
EXTRACTION_PROMPT = """Извлечи ВСИЧКИ хранителни продукти на марката Harmonica (Хармоника) от тази страница.
Включи САМО храни: млечни продукти, вафли, сиропи, масла, лютеници, кори, солети, бисквити, локум, кефир, извара.
НЕ включвай козметика, дрехи или нехранителни продукти.
За всеки продукт извлечи: име (точно както е на сайта), цена (само числото), грамаж/обем."""


# ============================================================================
# STORE-SPECIFIC FIRECRAWL CONFIGURATIONS
# ============================================================================

# Действия за сайтове, които изискват JS интеракция
STORE_ACTIONS = {
    "eBag": [
        {"type": "wait", "milliseconds": 3000},
        {"type": "click", "selector": 'button:has-text("покажи повече"), button:has-text("Покажи повече"), .ais-InfiniteHits-loadMore'},
        {"type": "wait", "milliseconds": 2000},
        {"type": "click", "selector": 'button:has-text("покажи повече"), button:has-text("Покажи повече"), .ais-InfiniteHits-loadMore'},
        {"type": "wait", "milliseconds": 2000},
        {"type": "click", "selector": 'button:has-text("покажи повече"), button:has-text("Покажи повече"), .ais-InfiniteHits-loadMore'},
        {"type": "wait", "milliseconds": 2000},
        {"type": "scroll", "direction": "down", "amount": 5},
        {"type": "wait", "milliseconds": 2000},
        {"type": "scrape"},
    ],
    "Kashon": [
        {"type": "wait", "milliseconds": 3000},
        {"type": "scroll", "direction": "down", "amount": 10},
        {"type": "wait", "milliseconds": 2000},
        {"type": "scrape"},
    ],
    "Balev": [
        {"type": "wait", "milliseconds": 3000},
        {"type": "scroll", "direction": "down", "amount": 8},
        {"type": "wait", "milliseconds": 2000},
        {"type": "scrape"},
    ],
    "Metro": [
        {"type": "wait", "milliseconds": 3000},
        {"type": "scroll", "direction": "down", "amount": 10},
        {"type": "wait", "milliseconds": 2000},
        {"type": "scrape"},
    ],
    "Zelen": [
        {"type": "wait", "milliseconds": 3000},
        {"type": "scroll", "direction": "down", "amount": 8},
        {"type": "wait", "milliseconds": 2000},
        {"type": "scrape"},
    ],
    "Randi": [
        {"type": "wait", "milliseconds": 3000},
        {"type": "scroll", "direction": "down", "amount": 8},
        {"type": "wait", "milliseconds": 2000},
        {"type": "scrape"},
    ],
    "BioMarket": [
        {"type": "wait", "milliseconds": 3000},
        {"type": "scroll", "direction": "down", "amount": 8},
        {"type": "wait", "milliseconds": 2000},
        {"type": "scrape"},
    ],
    "BeFit": [
        {"type": "wait", "milliseconds": 3000},
        {"type": "scroll", "direction": "down", "amount": 8},
        {"type": "wait", "milliseconds": 2000},
        {"type": "scrape"},
    ],
    "Laika": [
        {"type": "wait", "milliseconds": 3000},
        {"type": "scroll", "direction": "down", "amount": 8},
        {"type": "wait", "milliseconds": 2000},
        {"type": "scrape"},
    ],
}


def get_firecrawl_client() -> Optional[FirecrawlApp]:
    """Създава Firecrawl клиент."""
    if not FIRECRAWL_AVAILABLE:
        logger.error("  [FIRECRAWL] SDK не е наличен")
        return None
    if not FIRECRAWL_API_KEY:
        logger.error("  [FIRECRAWL] API ключ не е зададен (FIRECRAWL_API_KEY)")
        return None
    try:
        return FirecrawlApp(api_key=FIRECRAWL_API_KEY)
    except Exception as e:
        logger.error(f"  [FIRECRAWL] Грешка при създаване на клиент: {str(e)[:80]}")
        return None


def scrape_store_firecrawl(client: FirecrawlApp, store_key: str, url: str) -> dict:
    """
    Скрейпва един магазин с Firecrawl.

    Стратегия:
    1. Опитва scrape с markdown формат + actions за JS rendering
    2. Връща markdown текст за по-нататъшна обработка с Claude

    Args:
        client: FirecrawlApp инстанция
        store_key: Ключ на магазина (напр. "eBag", "Balev")
        url: URL за скрейпване

    Returns:
        dict с ключове:
            - markdown: Чист markdown текст от страницата
            - success: bool
            - error: str при грешка
    """
    actions = STORE_ACTIONS.get(store_key, [
        {"type": "wait", "milliseconds": 3000},
        {"type": "scroll", "direction": "down", "amount": 5},
        {"type": "wait", "milliseconds": 2000},
        {"type": "scrape"},
    ])

    start_time = time.time()

    try:
        logger.info(f"  [FIRECRAWL] Скрейпване на {store_key}: {url[:60]}...")

        result = client.scrape_url(
            url,
            params={
                "formats": ["markdown"],
                "actions": actions,
                "timeout": 60000,
                "waitFor": 3000,
            }
        )

        elapsed = time.time() - start_time

        # Извличаме markdown от резултата
        markdown = None
        if isinstance(result, dict):
            markdown = result.get("markdown", "")
        elif hasattr(result, "markdown"):
            markdown = result.markdown

        if not markdown:
            logger.warning(f"  [FIRECRAWL] {store_key}: Празен markdown ({elapsed:.1f}s)")
            return {"markdown": "", "success": False, "error": "Празен отговор"}

        logger.info(f"  [FIRECRAWL] {store_key}: {len(markdown)} символа markdown ({elapsed:.1f}s)")
        return {"markdown": markdown, "success": True, "error": None}

    except Exception as e:
        elapsed = time.time() - start_time
        error_msg = str(e)[:120]
        logger.error(f"  [FIRECRAWL] {store_key}: Грешка ({elapsed:.1f}s): {error_msg}")
        return {"markdown": "", "success": False, "error": error_msg}


def scrape_store_with_extraction(client: FirecrawlApp, store_key: str, url: str) -> dict:
    """
    Скрейпва магазин с Firecrawl и опитва structured extraction.

    Опитва два подхода:
    1. scrape с JSON schema extraction (директно структурирани данни)
    2. Fallback към markdown (за обработка с Claude)

    Args:
        client: FirecrawlApp инстанция
        store_key: Ключ на магазина
        url: URL за скрейпване

    Returns:
        dict с ключове:
            - products: list[dict] с извлечени продукти (ако extraction успее)
            - markdown: str markdown текст (винаги)
            - method: "extraction" или "markdown"
            - success: bool
    """
    actions = STORE_ACTIONS.get(store_key, [
        {"type": "wait", "milliseconds": 3000},
        {"type": "scroll", "direction": "down", "amount": 5},
        {"type": "wait", "milliseconds": 2000},
        {"type": "scrape"},
    ])

    start_time = time.time()

    # Подход 1: Scrape с markdown (надежден, работи с кредитите)
    try:
        logger.info(f"  [FIRECRAWL] {store_key}: Скрейпване с markdown...")

        result = client.scrape_url(
            url,
            params={
                "formats": ["markdown"],
                "actions": actions,
                "timeout": 60000,
                "waitFor": 3000,
            }
        )

        elapsed = time.time() - start_time

        markdown = ""
        if isinstance(result, dict):
            markdown = result.get("markdown", "")
        elif hasattr(result, "markdown"):
            markdown = result.markdown or ""

        if not markdown:
            logger.warning(f"  [FIRECRAWL] {store_key}: Празен markdown ({elapsed:.1f}s)")
            return {
                "products": [],
                "markdown": "",
                "method": "failed",
                "success": False,
            }

        logger.info(f"  [FIRECRAWL] {store_key}: {len(markdown)} символа ({elapsed:.1f}s)")

        return {
            "products": [],
            "markdown": markdown,
            "method": "markdown",
            "success": True,
        }

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"  [FIRECRAWL] {store_key}: Грешка ({elapsed:.1f}s): {str(e)[:120]}")
        return {
            "products": [],
            "markdown": "",
            "method": "failed",
            "success": False,
        }


def scrape_all_stores_firecrawl(stores_config: dict) -> dict:
    """
    Скрейпва всички магазини с Firecrawl последователно.

    Args:
        stores_config: STORES dict от scraper.py

    Returns:
        dict: {store_key: {"markdown": str, "products": list, "method": str, "success": bool}}
    """
    client = get_firecrawl_client()
    if not client:
        logger.error("  [FIRECRAWL] Не може да се създаде клиент")
        return {}

    results = {}
    total_start = time.time()

    for store_key, config in stores_config.items():
        url = config["url"]
        store_name = config["name_in_sheet"]

        logger.info(f"\n{'='*60}")
        logger.info(f"{store_name}: Firecrawl скрейпване")
        logger.info(f"{'='*60}")

        result = scrape_store_with_extraction(client, store_key, url)
        results[store_key] = result

        # Кратка пауза между заявките за да не претоварим API-то
        time.sleep(1)

    total_elapsed = time.time() - total_start
    successful = sum(1 for r in results.values() if r.get("success"))
    logger.info(f"\n  [FIRECRAWL] Общо: {successful}/{len(stores_config)} магазина за {total_elapsed:.1f}s")

    return results


def extract_products_from_markdown(markdown_text: str, store_name: str) -> list:
    """
    Извлича продукти от markdown текст с regex (без Claude).

    Търси patterns като:
    - "Продукт Name | 2.99 лв"
    - "Продукт Name ... 2.99"
    - Markdown таблици и списъци с цени

    Args:
        markdown_text: Markdown текст от Firecrawl
        store_name: Име на магазина

    Returns:
        list[dict]: [{name: str, price: float}, ...]
    """
    products = []
    if not markdown_text:
        return products

    # Pattern 1: Цена в контекст на продуктов текст
    # Търсим "текст ... числоX.XX ... лв/BGN/EUR"
    lines = markdown_text.split('\n')

    for line in lines:
        line = line.strip()
        if not line or len(line) < 5:
            continue

        # Търсим Harmonica/Хармоника продукти
        line_lower = line.lower()
        is_harmonica = any(kw in line_lower for kw in [
            'harmonica', 'хармоника', 'био вафла', 'био кисело', 'био сирене',
            'био краве', 'био козе', 'био фъстъчено', 'био лютеница',
            'био кашкавал', 'био крема', 'био извара', 'био кефир',
            'био прясно', 'био слънчогледово', 'био тахан', 'bio ',
            'chocobiotic', 'био солети', 'био кори', 'био локум',
            'био бисквити', 'био сироп',
        ])

        if not is_harmonica:
            continue

        # Извличаме цена от реда
        price_matches = re.findall(r'(\d+)[,.](\d{2})', line)
        if price_matches:
            # Вземаме последната цена в реда (обикновено е актуалната)
            for match in price_matches:
                try:
                    price = float(f"{match[0]}.{match[1]}")
                    if 0.5 < price < 200:  # Разумен диапазон
                        # Извличаме име (текст преди цената)
                        name = re.split(r'\d+[,.]?\d{2}', line)[0].strip()
                        # Почистваме markdown символи
                        name = re.sub(r'[*_#\[\]|>-]', '', name).strip()
                        if len(name) > 3 and name:
                            products.append({"name": name, "price": price})
                            break  # Една цена на ред
                except (ValueError, IndexError):
                    continue

    return products


def is_firecrawl_available() -> bool:
    """Проверява дали Firecrawl е наличен и конфигуриран."""
    return FIRECRAWL_AVAILABLE and bool(FIRECRAWL_API_KEY)
