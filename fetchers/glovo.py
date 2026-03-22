"""
Harmonica Price Tracker — Glovo Fetchers
==========================================
Fetchers for Glovo stores (Fantastico, Billa, CBA, Kaufland) via Firecrawl and API.
"""

import asyncio
import re
import time

from config import (
    FIRECRAWL_AVAILABLE, FIRECRAWL_API_KEY,
    CURL_CFFI_AVAILABLE, GLOVO_AUTH_TOKEN, GLOVO_API_BASE,
    GLOVO_STORES, EUR_BGN_RATE, logger,
)

if FIRECRAWL_AVAILABLE:
    from firecrawl import FirecrawlApp

if CURL_CFFI_AVAILABLE:
    from curl_cffi.requests import AsyncSession as CurlAsyncSession

from utils import is_food_product, is_harmonica_product, extract_bgn_price, extract_eur_price, extract_price_fallback


def _fetch_glovo_via_firecrawl(slug, store_name, query="harmonica"):
    """
    Firecrawl: рендерира Glovo SPA с headless browser, използва actions за
    да взаимодейства с търсачката в магазина и извлича продукти.
    Синхронна функция — ще се изпълнява в thread pool.
    """
    if not FIRECRAWL_AVAILABLE or not FIRECRAWL_API_KEY:
        return None

    start = time.time()
    store_url = f"https://glovoapp.com/bg/bg/sofia/stores/{slug}"

    # JS: намира и фокусира search input в Glovo SPA
    find_search_js = """
    (function() {
        var selectors = [
            'input[type="search"]',
            'input[placeholder*="Търси"]',
            'input[placeholder*="Search"]',
            'input[placeholder*="търси"]',
            '[data-testid*="search"] input',
            '[role="search"] input',
            'input[aria-label*="Search"]',
            'input[aria-label*="Търси"]',
        ];
        for (var i = 0; i < selectors.length; i++) {
            var el = document.querySelector(selectors[i]);
            if (el) { el.click(); el.focus(); return 'found:' + selectors[i]; }
        }
        var btns = document.querySelectorAll('button, [role="button"], a');
        for (var j = 0; j < btns.length; j++) {
            var t = (btns[j].textContent || '').toLowerCase();
            var a = (btns[j].getAttribute('aria-label') || '').toLowerCase();
            if (t.indexOf('search') >= 0 || t.indexOf('търси') >= 0 ||
                a.indexOf('search') >= 0 || a.indexOf('търси') >= 0) {
                btns[j].click();
                return 'clicked-button';
            }
        }
        return 'not-found';
    })()
    """.strip()

    try:
        app = FirecrawlApp(api_key=FIRECRAWL_API_KEY)

        # Подход 1: Actions — взаимодействие с search box на store page
        search_actions = [
            {"type": "wait", "milliseconds": 4000},
            {"type": "executeJavascript", "script": find_search_js},
            {"type": "wait", "milliseconds": 1500},
            {"type": "write", "text": query},
            {"type": "wait", "milliseconds": 1000},
            {"type": "press", "key": "Enter"},
            {"type": "wait", "milliseconds": 5000},
            {"type": "scroll", "direction": "down"},
            {"type": "wait", "milliseconds": 2000},
            {"type": "scrape"},
        ]

        try:
            result = app.scrape_url(
                store_url,
                params={
                    "formats": ["markdown"],
                    "actions": search_actions,
                    "timeout": 60000,
                },
            )
            elapsed = time.time() - start

            if isinstance(result, dict):
                markdown = result.get("markdown", "")
            elif hasattr(result, "markdown"):
                markdown = result.markdown or ""
            else:
                markdown = str(result) if result else ""

            if markdown:
                harmonica_refs = len(re.findall(r'(?i)harmonica|хармоника', markdown))
                logger.info(f"Glovo {store_name}: Firecrawl [search-actions] — "
                            f"{len(markdown)} chars, {harmonica_refs} harmonica refs ({elapsed:.1f}s)")

                if harmonica_refs > 0:
                    products = _parse_glovo_markdown(markdown, store_name, query)
                    if products:
                        return {
                            "success": True,
                            "method": "firecrawl_search_actions",
                            "products": products,
                            "elapsed": elapsed,
                        }
                else:
                    logger.info(f"  preview: {markdown[:300].replace(chr(10), ' ')}")
            else:
                logger.info(f"Glovo {store_name}: Firecrawl [search-actions] — празен markdown ({elapsed:.1f}s)")

        except Exception as e:
            elapsed = time.time() - start
            logger.info(f"Glovo {store_name}: Firecrawl actions грешка: {e} ({elapsed:.1f}s)")

        elapsed = time.time() - start
        logger.info(f"Glovo {store_name}: Firecrawl — 0 продукта ({elapsed:.1f}s)")
        return None

    except Exception as e:
        elapsed = time.time() - start
        logger.warning(f"Glovo {store_name}: Firecrawl грешка: {e} ({elapsed:.1f}s)")
        return None


def _parse_glovo_markdown(markdown, store_name, query):
    """Парсва Firecrawl markdown от Glovo store page за Harmonica продукти."""
    products = []
    seen = set()
    query_lower = query.lower()

    # Pattern 1: Продукт с цена на следващ ред (markdown формат)
    # Примери: "Harmonica Био кисело мляко 2% 400г\n3.29 лв" или "3,29 лв"
    lines = markdown.split('\n')
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if not line_stripped:
            continue

        # Търсим ред с harmonica/хармоника
        if query_lower not in line_stripped.lower() and 'хармоника' not in line_stripped.lower():
            continue

        if not is_food_product(line_stripped):
            continue

        name_key = line_stripped.lower()[:30]
        if name_key in seen:
            continue

        # Търсим цена в текущия ред или следващите 3 реда
        # ВАЖНО: Glovo работи в България — ВСИЧКИ цени са в BGN,
        # дори ако markdown-ът показва € символ (грешен маркер от сайта).
        context = '\n'.join(lines[i:i+4])
        bgn = extract_bgn_price(context)
        if not bgn:
            # Glovo понякога показва BGN цени с € маркер —
            # третираме ги като BGN, НЕ като EUR
            eur_val = extract_eur_price(context)
            if eur_val:
                bgn = eur_val  # стойността е BGN въпреки € символа
        if not bgn:
            # Fallback: число без валутен маркер
            bgn = extract_price_fallback(context)

        if bgn and bgn > 0:
            eur = round(bgn / EUR_BGN_RATE, 2)
            # Чистим името
            name = re.sub(r'\s*\d+[.,]\d{2}\s*(?:лв|bgn|eur|€)?\s*$', '', line_stripped,
                          flags=re.IGNORECASE).strip()
            if len(name) > 5:
                seen.add(name_key)
                products.append({"name": name, "eur": eur, "bgn": bgn})

    # Pattern 2: Link формат [Име](url) с цена наблизо
    link_pattern = r'\[([^\]]*(?:harmonica|хармоника)[^\]]*)\]\([^\)]+\)'
    for match in re.finditer(link_pattern, markdown, re.IGNORECASE):
        name = match.group(1).strip()
        if not name or not is_food_product(name):
            continue

        name_key = name.lower()[:30]
        if name_key in seen:
            continue

        idx = match.end()
        context = markdown[idx:idx + 200]
        bgn = extract_bgn_price(context)
        if not bgn:
            eur_val = extract_eur_price(context)
            if eur_val:
                bgn = eur_val  # Glovo: € маркер е BGN
        if not bgn:
            bgn = extract_price_fallback(context)
        if bgn and bgn > 0:
            eur = round(bgn / EUR_BGN_RATE, 2)
            seen.add(name_key)
            products.append({"name": name, "eur": eur, "bgn": bgn})

    return products


async def fetch_glovo_store_products(store_key, store_config, query="harmonica"):
    """
    Търси Harmonica продукти в Glovo магазин.

    Подходи по приоритет:
    1. Firecrawl (JS rendering, headless browser)
    2. Glovo API v3 (с auth token)
    3. curl_cffi HTML (fallback)
    """
    slug = store_config["slug"]
    city_code = store_config.get("city_code", "SOF")
    store_name = store_config["name"]

    logger.info(f"Glovo {store_name}: търсене на '{query}'...")
    start = time.time()

    # === Подход 1: Firecrawl (JS rendering) ===
    if FIRECRAWL_AVAILABLE and FIRECRAWL_API_KEY:
        # Firecrawl е синхронен — run в thread pool
        loop = asyncio.get_event_loop()
        fc_result = await loop.run_in_executor(
            None, _fetch_glovo_via_firecrawl, slug, store_name, query
        )
        if fc_result and fc_result.get("success"):
            return fc_result

    # === Подход 2: Glovo API (с auth token) ===
    if GLOVO_AUTH_TOKEN and CURL_CFFI_AVAILABLE:

        glovo_headers = {
            "Accept": "application/json",
            "Accept-Language": "bg-BG,bg;q=0.9,en;q=0.8",
            "Glovo-Location-City-Code": city_code,
            "Glovo-Api-Version": "14",
            "Glovo-App-Platform": "web",
            "Glovo-App-Type": "customer",
            "Authorization": f"Bearer {GLOVO_AUTH_TOKEN}",
        }

        try:
            async with CurlAsyncSession(impersonate="chrome") as session:
                # API search
                search_url = f"{GLOVO_API_BASE}/stores/{slug}/search"
                resp = await session.get(
                    search_url, params={"query": query},
                    headers=glovo_headers, timeout=20,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    products = _parse_glovo_products(data, store_name)
                    if products:
                        elapsed = time.time() - start
                        logger.info(f"Glovo {store_name}: API search → "
                                    f"{len(products)} продукта ({elapsed:.1f}s)")
                        return {"success": True, "method": "glovo_api_search",
                                "products": products, "elapsed": elapsed}
                else:
                    logger.info(f"Glovo {store_name}: API search HTTP {resp.status_code}")

                # API catalog
                catalog_url = f"{GLOVO_API_BASE}/stores/{slug}"
                resp = await session.get(
                    catalog_url, headers=glovo_headers, timeout=20,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    products = _parse_glovo_catalog(data, store_name, query)
                    if products:
                        elapsed = time.time() - start
                        logger.info(f"Glovo {store_name}: API catalog → "
                                    f"{len(products)} продукта ({elapsed:.1f}s)")
                        return {"success": True, "method": "glovo_api_catalog",
                                "products": products, "elapsed": elapsed}
                else:
                    logger.info(f"Glovo {store_name}: API catalog HTTP {resp.status_code}")
        except Exception as e:
            logger.info(f"Glovo {store_name}: API грешка: {e}")

    elapsed = time.time() - start
    logger.warning(f"Glovo {store_name}: не намерени Harmonica продукти ({elapsed:.1f}s)")
    return {"success": False, "error": "No products found"}


def _parse_glovo_products(data, store_name):
    """Парсва продукти от Glovo API search response."""
    products = []
    seen = set()

    # Glovo search response може да е dict с "products" или list
    items = []
    if isinstance(data, dict):
        items = data.get("products", data.get("items", data.get("results", [])))
        # Опит: sections → products
        for section in data.get("sections", []):
            items.extend(section.get("products", section.get("items", [])))
    elif isinstance(data, list):
        items = data

    for item in items:
        name = item.get("name", item.get("productName", ""))
        if not name:
            continue
        if not is_harmonica_product(name):
            continue
        if not is_food_product(name):
            continue

        name_key = name.lower()[:30]
        if name_key in seen:
            continue

        # Price — Glovo обикновено връща в стотинки или пряко в BGN
        price_bgn = None
        price_obj = item.get("price", item.get("priceInfo", {}))
        if isinstance(price_obj, (int, float)):
            price_bgn = round(float(price_obj) / 100, 2) if price_obj > 100 else float(price_obj)
        elif isinstance(price_obj, dict):
            amount = price_obj.get("amount", price_obj.get("value", 0))
            if amount:
                price_bgn = round(float(amount) / 100, 2) if amount > 100 else float(amount)

        if price_bgn and price_bgn > 0:
            price_eur = round(price_bgn / EUR_BGN_RATE, 2)
            seen.add(name_key)
            products.append({
                "name": name,
                "eur": price_eur,
                "bgn": price_bgn,
            })

    return products


def _parse_glovo_catalog(data, store_name, query):
    """Парсва целия каталог и филтрира по query."""
    all_products = []

    # Каталогът може да е в categories → sections → products
    categories = data.get("categories", data.get("menu", {}).get("categories", []))
    for cat in categories:
        sections = cat.get("sections", cat.get("groups", []))
        for section in sections:
            items = section.get("products", section.get("items", []))
            all_products.extend(items)
        # Директни продукти в категорията
        all_products.extend(cat.get("products", []))

    # Филтрираме за Harmonica
    products = []
    seen = set()
    query_lower = query.lower()

    for item in all_products:
        name = item.get("name", "")
        if not name:
            continue
        if query_lower not in name.lower() and "хармоника" not in name.lower():
            continue
        if not is_food_product(name):
            continue

        name_key = name.lower()[:30]
        if name_key in seen:
            continue

        price_bgn = None
        price_obj = item.get("price", item.get("priceInfo", {}))
        if isinstance(price_obj, (int, float)):
            price_bgn = round(float(price_obj) / 100, 2) if price_obj > 100 else float(price_obj)
        elif isinstance(price_obj, dict):
            amount = price_obj.get("amount", price_obj.get("value", 0))
            if amount:
                price_bgn = round(float(amount) / 100, 2) if amount > 100 else float(amount)

        if price_bgn and price_bgn > 0:
            price_eur = round(price_bgn / EUR_BGN_RATE, 2)
            seen.add(name_key)
            products.append({
                "name": name,
                "eur": price_eur,
                "bgn": price_bgn,
            })

    return products


async def fetch_all_glovo_products(query="harmonica"):
    """Търси Harmonica продукти във всички Glovo магазини паралелно."""
    if not GLOVO_STORES:
        return {}

    if not FIRECRAWL_AVAILABLE or not FIRECRAWL_API_KEY:
        logger.warning("Glovo: FIRECRAWL_API_KEY не е зададен — пропускане")
        return {}

    logger.info("Glovo: ще използваме Firecrawl (JS rendering)")

    tasks = {}
    for store_key, config in GLOVO_STORES.items():
        tasks[store_key] = asyncio.create_task(
            fetch_glovo_store_products(store_key, config, query)
        )

    results = {}
    for store_key, task in tasks.items():
        try:
            result = await task
            results[store_key] = result
            if result.get("success"):
                products = result.get("products", [])
                logger.info(f"Glovo {GLOVO_STORES[store_key]['name']}: "
                            f"{len(products)} Harmonica продукта")
            else:
                logger.info(f"Glovo {GLOVO_STORES[store_key]['name']}: "
                            f"{result.get('error', 'неизвестна грешка')}")
        except Exception as e:
            logger.error(f"Glovo {GLOVO_STORES[store_key]['name']}: {e}")
            results[store_key] = {"success": False, "error": str(e)}

    return results
