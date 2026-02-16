"""
Harmonica Price Tracker v10.6
==============================
Modular scraper — Firecrawl-first + Crawl4AI fallback архитектура.
Магазини, за които Firecrawl timeout-ва, автоматично преминават на Crawl4AI.
Claude Sonnet валидация на outlier цени (EUR).
Продуктов списък от harmonica_products.json (месечен sync с Кашон).

Магазини: Кашон, eBag, Balev, Lilly, DM, T-Market, Metro, Randi,
          Zelen, BioMarket, BeFit, Laika + Glovo (Fantastico, Billa, CBA, Kaufland).
"""

import asyncio
import json
import os
import re
import time
from datetime import datetime

# Project modules
from config import (
    STORES, GLOVO_STORES, EUR_BGN_RATE, logger,
    FIRECRAWL_AVAILABLE, FIRECRAWL_API_KEY,
    CRAWL4AI_AVAILABLE, CURL_CFFI_AVAILABLE,
    ANTHROPIC_AVAILABLE, ANTHROPIC_API_KEY, CLAUDE_MODEL,
    BS4_AVAILABLE, PROJECT_ROOT,
)
from products import load_product_list, update_product_list_with_new, save_product_list
from matching import match_products
from validation import validate_prices_with_claude
from extractors import (
    extract_kashon_products, extract_ebag_products, extract_balev_products,
    _extract_generic_products, extract_metro_products, extract_tmarket_products,
    extract_lilly_products, extract_dm_products, extract_dm_from_curl_html,
    extract_randi_products,
)

# Fetcher modules
from fetchers import (
    _fetch_dm_via_firecrawl,
    _fetch_randi_via_firecrawl,
    _fetch_store_via_firecrawl,
    _fetch_lilly_via_firecrawl,
    _fetch_tmarket_via_firecrawl,
    crawl_with_captcha_solver,
    crawl_store,
    fetch_dm_via_algolia,
    fetch_lilly_via_curl,
    fetch_tmarket_via_curl,
    fetch_all_glovo_products,
)

# Output modules
from output import write_to_sheets, send_email_report


# =============================================================================
# CRAWLING — с retry и паралелно изпълнение
# =============================================================================

async def crawl_all():
    """
    Сканира всички магазини: Firecrawl-first + Crawl4AI fallback.

    Стратегия:
    1. Стартираме Firecrawl за всички магазини паралелно
    2. Магазини, за които Firecrawl timeout-ва или връща грешка,
       автоматично преминават на Crawl4AI (локален headless Chromium)
    3. Crawl4AI работи без прокси — достатъчен е за повечето BG магазини
    """
    has_firecrawl = FIRECRAWL_AVAILABLE and FIRECRAWL_API_KEY
    has_crawl4ai = CRAWL4AI_AVAILABLE

    if not has_firecrawl and not has_crawl4ai:
        logger.error("Нито Firecrawl, нито Crawl4AI е наличен! Не може да се сканира.")
        return {}

    results = {}
    loop = asyncio.get_event_loop()

    # ==========================================================================
    # Стъпка 1: Стартираме Firecrawl задачи паралелно (ако е наличен)
    # ==========================================================================
    firecrawl_futures = {}

    if has_firecrawl:
        # Randi — специализиран Firecrawl (JS-heavy)
        if "randi" in STORES:
            firecrawl_futures["randi"] = loop.run_in_executor(
                None, _fetch_randi_via_firecrawl)

        # Lilly — специализиран Firecrawl (Magento 2 + Hyvä)
        if "lilly" in STORES:
            firecrawl_futures["lilly"] = loop.run_in_executor(
                None, _fetch_lilly_via_firecrawl)

        # T-Market — специализиран Firecrawl (CloudCart + Cloudflare)
        if "tmarket" in STORES:
            firecrawl_futures["tmarket"] = loop.run_in_executor(
                None, _fetch_tmarket_via_firecrawl)

        # Останалите магазини — универсален Firecrawl fetch
        generic_firecrawl_stores = [
            "kashon", "ebag", "balev", "metro", "zelen", "biomarket", "befit", "laika",
        ]
        for store_key in generic_firecrawl_stores:
            if store_key in STORES:
                cfg = STORES[store_key]
                firecrawl_futures[store_key] = loop.run_in_executor(
                    None, _fetch_store_via_firecrawl, store_key, cfg)

    # ==========================================================================
    # Стъпка 2: Събираме Firecrawl резултати, маркираме неуспешните за fallback
    # ==========================================================================
    failed_stores = []  # Магазини, които ще опитаме с Crawl4AI

    for store_key, future in firecrawl_futures.items():
        store_name = STORES.get(store_key, {}).get("name", store_key)
        try:
            fc_result = await future
            if fc_result and fc_result.get("success"):
                results[store_key] = fc_result
                products = fc_result.get("products", [])
                if products:
                    logger.info(f"{store_name}: Firecrawl успех — "
                                f"{len(products)} продукта")
                else:
                    logger.info(f"{store_name}: Firecrawl успех — "
                                f"markdown/html получен")
            else:
                error_msg = ""
                if fc_result:
                    error_msg = fc_result.get("error", "unknown")
                logger.warning(f"{store_name}: Firecrawl неуспешен ({error_msg})")
                failed_stores.append(store_key)
        except Exception as e:
            logger.error(f"{store_name}: Firecrawl грешка — {e}")
            failed_stores.append(store_key)

    # Магазини, за които Firecrawl изобщо не беше стартиран (липсва API key)
    if not has_firecrawl:
        failed_stores = list(STORES.keys())

    # Магазини, за които Firecrawl успя но с ограничени scrolls —
    # Crawl4AI ще скролира пълния обхват и ще заместим ако е по-добър
    partial_stores = [
        sk for sk, res in results.items()
        if res.get("success") and res.get("scrolls_capped")
    ]
    if partial_stores:
        logger.info(f"Магазини с ограничен Firecrawl scroll (ще пробваме Crawl4AI): "
                    f"{', '.join(STORES[s]['name'] for s in partial_stores)}")

    # ==========================================================================
    # Стъпка 3: Crawl4AI fallback за неуспешни + partial магазини
    # ==========================================================================
    # Crawl4AI fallback за всички магазини — опитваме headless Chromium
    CRAWL4AI_CAPABLE = {
        "kashon", "ebag", "balev", "metro", "zelen", "biomarket",
        "befit", "laika", "randi", "lilly", "tmarket",
    }
    crawl4ai_needed = [s for s in failed_stores if s in CRAWL4AI_CAPABLE]
    # Добавяме partial stores (Firecrawl успя, но scrolls бяха лимитирани)
    for s in partial_stores:
        if s in CRAWL4AI_CAPABLE and s not in crawl4ai_needed:
            crawl4ai_needed.append(s)

    if crawl4ai_needed and has_crawl4ai:
        logger.info(f"Crawl4AI fallback за {len(crawl4ai_needed)} магазина: "
                    f"{', '.join(STORES[s]['name'] for s in crawl4ai_needed)}")

        partial_set = set(partial_stores)
        stores_to_crawl = [s for s in crawl4ai_needed
                           if s in partial_set  # partial Firecrawl → Crawl4AI upgrade
                           or s not in results
                           or not results.get(s, {}).get("success")]

        if stores_to_crawl:
            browser_config = BrowserConfig(
                headless=True,
                viewport_width=1920,
                viewport_height=1080,
            )

            async with AsyncWebCrawler(config=browser_config) as crawler:
                tasks = {}
                for store_key in stores_to_crawl:
                    cfg = STORES[store_key]
                    if cfg.get("needs_captcha_solver"):
                        tasks[store_key] = crawl_with_captcha_solver(
                            crawler, store_key, cfg)
                    else:
                        tasks[store_key] = crawl_store(crawler, store_key, cfg)

                task_results = await asyncio.gather(
                    *tasks.values(), return_exceptions=True)

                for store_key, result in zip(tasks.keys(), task_results):
                    store_name = STORES[store_key]["name"]
                    if isinstance(result, Exception):
                        error_str = str(result)
                        logger.error(f"{store_name}: Crawl4AI грешка — {result}")
                        results[store_key] = {"success": False, "error": error_str}
                    elif result and result.get("success"):
                        result["method"] = "crawl4ai"
                        crawl4ai_md_len = len(result.get('markdown', ''))
                        existing_md_len = len(results.get(store_key, {}).get('markdown', ''))
                        if store_key in partial_set and existing_md_len > 0:
                            # Partial Firecrawl: сравняваме markdown размер
                            if crawl4ai_md_len > existing_md_len:
                                results[store_key] = result
                                logger.info(f"{store_name}: Crawl4AI upgrade — "
                                            f"{crawl4ai_md_len} chars (Firecrawl: {existing_md_len})")
                                partial_set.discard(store_key)
                            else:
                                logger.info(f"{store_name}: Crawl4AI {crawl4ai_md_len} chars "
                                            f"≤ Firecrawl {existing_md_len} — запазваме Firecrawl")
                                partial_set.discard(store_key)
                        else:
                            results[store_key] = result
                            logger.info(f"{store_name}: Crawl4AI fallback успех — "
                                        f"{crawl4ai_md_len} chars")
                    else:
                        error = result.get("error", "unknown") if result else "None"
                        logger.warning(f"{store_name}: Crawl4AI fallback неуспешен ({error})")
                        results[store_key] = result or {
                            "success": False, "error": "Crawl4AI returned None"}

    elif crawl4ai_needed and not has_crawl4ai:
        logger.warning(f"Crawl4AI не е наличен — {len(crawl4ai_needed)} магазина без fallback: "
                       f"{', '.join(STORES[s]['name'] for s in crawl4ai_needed)}")
        for store_key in crawl4ai_needed:
            if store_key not in results:
                results[store_key] = {
                    "success": False,
                    "error": "Firecrawl failed, Crawl4AI not available",
                }

    # ==========================================================================
    # Стъпка 4: curl_cffi fallback за T-Market и Lilly (ако Firecrawl + Crawl4AI неуспешни)
    # ==========================================================================
    if CURL_CFFI_AVAILABLE:
        # T-Market: curl_cffi TLS impersonation (bypass Cloudflare)
        tm_result = results.get("tmarket", {})
        tm_has_products = tm_result.get("success") and (
            tm_result.get("products") or len(tm_result.get("markdown", "")) > 500)
        if not tm_has_products:
            logger.info("T-Market: curl_cffi fallback...")
            try:
                tm_curl = await fetch_tmarket_via_curl()
                if tm_curl and tm_curl.get("success"):
                    results["tmarket"] = tm_curl
                    logger.info(f"T-Market: curl_cffi успех — {len(tm_curl.get('html', ''))} chars")
            except Exception as e:
                logger.warning(f"T-Market curl_cffi fallback грешка: {e}")

        # Lilly: Magento GraphQL/REST API (Hyvä Theme не дава продукти чрез Firecrawl)
        lilly_result = results.get("lilly", {})
        lilly_products = lilly_result.get("products", [])
        lilly_has_enough = lilly_result.get("success") and len(lilly_products) >= 3
        if not lilly_has_enough:
            logger.info("Lilly: curl_cffi GraphQL/REST API fallback...")
            try:
                lilly_curl = await fetch_lilly_via_curl()
                if lilly_curl and lilly_curl.get("success"):
                    results["lilly"] = lilly_curl
                    logger.info(f"Lilly: curl_cffi успех — "
                                f"{len(lilly_curl.get('products', []))} продукта")
            except Exception as e:
                logger.warning(f"Lilly curl_cffi fallback грешка: {e}")

    # Маркираме останалите неуспешни
    for store_key in failed_stores:
        if store_key not in results:
            results[store_key] = {
                "success": False,
                "error": "All methods failed (Firecrawl + Crawl4AI + curl_cffi)",
            }

    # ==========================================================================
    # Glovo магазини (паралелно, отделен Firecrawl pipeline)
    # ==========================================================================
    if GLOVO_STORES and has_firecrawl:
        glovo_results = await fetch_all_glovo_products("harmonica")
        results.update(glovo_results)

    return results


# =============================================================================
# MAIN
# =============================================================================

async def main():
    logger.info("=" * 60)
    total_stores = len(STORES) + len(GLOVO_STORES)
    logger.info(f"HARMONICA PRICE TRACKER v10.5 — {total_stores} магазина (Firecrawl + Crawl4AI)")
    logger.info("=" * 60)
    logger.info(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Магазини: {len(STORES)} + {len(GLOVO_STORES)} Glovo, BS4: {BS4_AVAILABLE}")
    if FIRECRAWL_AVAILABLE and FIRECRAWL_API_KEY:
        logger.info(f"Firecrawl: YES (key: {FIRECRAWL_API_KEY[:8]}...)")
    else:
        logger.warning("Firecrawl: НЕ — ще се ползва само Crawl4AI")
    if CRAWL4AI_AVAILABLE:
        logger.info("Crawl4AI: YES (fallback за неуспешни Firecrawl магазини)")
    else:
        logger.warning("Crawl4AI: НЕ — няма fallback при Firecrawl timeout")
    if ANTHROPIC_AVAILABLE and ANTHROPIC_API_KEY:
        logger.info(f"Claude: YES ({CLAUDE_MODEL})")
    else:
        logger.info("Claude: НЕ — ценова валидация изключена")

    if not (FIRECRAWL_AVAILABLE and FIRECRAWL_API_KEY) and not CRAWL4AI_AVAILABLE:
        logger.error("Нито Firecrawl, нито Crawl4AI е наличен! Инсталирайте поне един.")
        return

    total_start = time.time()

    # 0. Зареждане на продуктовия списък от JSON (master list)
    reference_products = load_product_list()

    # 1. Crawl — паралелно
    crawl_results = await crawl_all()

    # 2. Extract products
    logger.info("=" * 40 + " EXTRACTING " + "=" * 40)

    # Кашон — извличаме за цени + откриване на нови продукти
    kashon_products = []
    if crawl_results.get("kashon", {}).get("success"):
        kashon_products = extract_kashon_products(crawl_results["kashon"]["markdown"])
        logger.info(f"Кашон: {len(kashon_products)} Harmonica products")

    # Обновяваме reference list с нови продукти от Кашон
    if kashon_products and reference_products:
        reference_products = update_product_list_with_new(reference_products, kashon_products)
    elif kashon_products and not reference_products:
        # Fallback: ако JSON липсва, използваме Кашон като master list
        logger.warning("JSON продуктов файл липсва — използваме Кашон като master list")
        reference_products = [
            {"name": kp["name"], "ref_eur": kp.get("eur"), "ref_bgn": kp.get("bgn"),
             "status": "active", "active": True}
            for kp in kashon_products
        ]

    # eBag
    ebag_products = []
    if crawl_results.get("ebag", {}).get("success"):
        ebag_products = extract_ebag_products(crawl_results["ebag"]["markdown"])
        logger.info(f"eBag: {len(ebag_products)} Harmonica products")

    # Balev
    balev_products = []
    if crawl_results.get("balev", {}).get("success"):
        balev_products = extract_balev_products(crawl_results["balev"]["markdown"])
        logger.info(f"Balev: {len(balev_products)} Harmonica products")

    # Lilly Drogerie
    lilly_products = []
    lilly_data = crawl_results.get("lilly", {})
    if lilly_data.get("success"):
        method = lilly_data.get("method", "unknown")
        # GraphQL/REST API — продуктите са вече извлечени
        if lilly_data.get("products"):
            lilly_products = lilly_data["products"]
        elif lilly_data.get("html") or lilly_data.get("markdown"):
            lilly_products = extract_lilly_products(
                lilly_data.get("markdown", ""),
                html_text=lilly_data.get("html"),
            )
        logger.info(f"Lilly: {len(lilly_products)} Harmonica products (method: {method})")
        in_stock = sum(1 for p in lilly_products if p.get('in_stock', True))
        if in_stock < len(lilly_products):
            logger.info(f"  Налични: {in_stock}, Изчерпани: {len(lilly_products) - in_stock}")
    elif lilly_data.get("error"):
        logger.warning(f"Lilly: {lilly_data['error']}")

    # T-Market
    tmarket_products = []
    tmarket_data = crawl_results.get("tmarket", {})
    if tmarket_data.get("success"):
        method = tmarket_data.get("method", "unknown")
        if tmarket_data.get("html"):
            tmarket_products = extract_tmarket_products(
                tmarket_data.get("markdown", ""),
                html_text=tmarket_data.get("html"),
                brand_page=STORES["tmarket"].get("brand_page", True),
            )
        elif tmarket_data.get("markdown"):
            tmarket_products = extract_tmarket_products(
                tmarket_data["markdown"],
                brand_page=STORES["tmarket"].get("brand_page", True),
            )
        logger.info(f"T-Market: {len(tmarket_products)} Harmonica products (method: {method})")
    elif tmarket_data.get("error"):
        logger.warning(f"T-Market: {tmarket_data['error']}")

    # Metro — специализиран extractor
    metro_products = []
    metro_data = crawl_results.get("metro", {})
    if metro_data.get("success") and metro_data.get("markdown"):
        metro_products = extract_metro_products(metro_data["markdown"])
        if not metro_products:
            # Fallback към generic
            metro_products = _extract_generic_products(metro_data["markdown"], brand_page=False)
        logger.info(f"Metro: {len(metro_products)} Harmonica products")
    elif metro_data.get("error"):
        logger.warning(f"Metro: {metro_data['error']}")

    # Randi — специализиран extractor (с Firecrawl или Crawl4AI markdown)
    randi_products = []
    randi_data = crawl_results.get("randi", {})
    if randi_data.get("success"):
        if randi_data.get("products"):
            # Firecrawl — продуктите са вече извлечени
            randi_products = randi_data["products"]
        elif randi_data.get("markdown"):
            randi_products = extract_randi_products(randi_data["markdown"])
            if not randi_products:
                randi_products = _extract_generic_products(randi_data["markdown"], brand_page=False)
        method = randi_data.get("method", "crawl4ai")
        logger.info(f"Randi: {len(randi_products)} Harmonica products (method: {method})")
    elif randi_data.get("error"):
        logger.warning(f"Randi: {randi_data['error']}")

    # Останали нови магазини (Zelen, BioMarket, BeFit, Laika) — generic extraction
    generic_stores = {
        "zelen": {"products": [], "brand_page": True},
        "biomarket": {"products": [], "brand_page": True},
        "befit": {"products": [], "brand_page": True},
        "laika": {"products": [], "brand_page": True},
    }
    for store_key, store_info in generic_stores.items():
        store_data = crawl_results.get(store_key, {})
        if store_data.get("success") and store_data.get("markdown"):
            md = store_data["markdown"]
            # BeFit: премахваме accessibility overlay (UserWay/EqualWeb widget)
            if store_key == "befit":
                md = re.sub(
                    r'(?si)(?:Моля, обърнете внимание|Accessibility|'
                    r'система за достъпност|екранен четец|'
                    r'Control-F1[01]|acsb|EqualWeb|UserWay).*?(?=\n\n|\Z)',
                    '', md
                )
                md = re.sub(r'(?si)Close\s+Popup heading\s+Достъпност.*?(?=\n\n|\Z)', '', md)
            store_info["products"] = _extract_generic_products(
                md,
                brand_page=store_info["brand_page"],
            )
            # BeFit: ако generic extractor не намери нищо, пробваме без brand_page filter
            if store_key == "befit" and not store_info["products"]:
                store_info["products"] = _extract_generic_products(
                    md,
                    brand_page=False,
                )
            prods = store_info["products"]
            logger.info(f"{STORES[store_key]['name']}: {len(prods)} Harmonica products")
            if not prods:
                # Debug: показваме начало на markdown за диагностика
                md_preview = store_data["markdown"][:300].replace('\n', ' ')
                logger.info(f"  [DEBUG] markdown preview: {md_preview}")
            # Debug: показваме извлечените имена за магазини с малко продукти
            if len(prods) <= 10:
                for p in prods:
                    logger.info(f"  → {p['name'][:60]} = {p.get('eur', '?')}€")
        elif store_data.get("error"):
            logger.warning(f"{STORES[store_key]['name']}: {store_data['error']}")

    # Glovo магазини — продуктите са вече извлечени от fetch_all_glovo_products()
    glovo_all_products = {}
    for gkey, gconfig in GLOVO_STORES.items():
        gdata = crawl_results.get(gkey, {})
        if gdata.get("success") and gdata.get("products"):
            glovo_all_products[gkey] = gdata["products"]
            logger.info(f"Glovo {gconfig['name']}: {len(gdata['products'])} Harmonica products "
                        f"(method: {gdata.get('method')})")
        elif gdata.get("error"):
            glovo_all_products[gkey] = []
            logger.warning(f"Glovo {gconfig['name']}: {gdata['error']}")
        else:
            glovo_all_products[gkey] = []

    # 3. Match products
    logger.info("=" * 40 + " MATCHING " + "=" * 40)

    # Store keys: основни магазини (без Кашон) + Glovo магазини
    store_keys = [key for key, cfg in STORES.items() if not cfg.get("is_master")]
    glovo_keys = list(GLOVO_STORES.keys())
    all_keys = store_keys + glovo_keys

    # Изграждаме final_products от reference list (JSON), не от Кашон crawl
    final_products = []
    for ref in reference_products:
        product = {
            "name": ref["name"],
            "kashon": None,
            "status": ref.get("status", "active"),
        }
        for sk in all_keys:
            product[sk] = None
        final_products.append(product)

    # Кашон — match-ваме цените от crawl към reference list (EUR + BGN)
    if kashon_products:
        kashon_matches = match_products(reference_products, kashon_products)
        for product in final_products:
            if product["name"] in kashon_matches:
                m = kashon_matches[product["name"]]
                product["kashon"] = {"eur": m["eur"], "bgn": m["bgn"]}
        kashon_matched = sum(1 for p in final_products if p.get("kashon"))
        logger.info(f"Кашон цени: {kashon_matched}/{len(reference_products)} matched")

    # Всички магазини и техните продукти
    all_store_products = {
        "ebag": ebag_products,
        "balev": balev_products,
        "lilly": lilly_products,
        "tmarket": tmarket_products,
        "metro": metro_products,
        "randi": randi_products,
    }
    # Добавяме останалите generic магазини
    for store_key, store_info in generic_stores.items():
        all_store_products[store_key] = store_info["products"]
    # Добавяме Glovo магазините
    all_store_products.update(glovo_all_products)

    # External stores — само EUR цени
    for store_key, store_prods in all_store_products.items():
        if not store_prods:
            continue
        matches = match_products(reference_products, store_prods)
        for product in final_products:
            if product["name"] in matches:
                m = matches[product["name"]]
                eur = m.get("eur")
                bgn = m.get("bgn")
                if not eur and bgn:
                    eur = round(bgn / EUR_BGN_RATE, 2)
                entry = {"eur": eur}
                if "in_stock" in m:
                    entry["in_stock"] = m["in_stock"]
                product[store_key] = entry

    # 3.5. Claude Sonnet ценова валидация
    logger.info("=" * 40 + " CLAUDE VALIDATION " + "=" * 40)
    final_products, validation_log = validate_prices_with_claude(final_products, all_keys)

    # 4. Statistics
    logger.info("=" * 40 + " STATISTICS " + "=" * 40)
    total_ref = len(reference_products)
    kashon_count = len([p for p in final_products if p.get("kashon")])
    new_count = len([p for p in final_products if p.get("status") == "new"])
    logger.info(f"Референтен списък: {total_ref} продукта ({new_count} нови)")
    logger.info(f"Кашон цени: {kashon_count}/{total_ref} matched")

    # Всички имена на магазини (обикновени + Glovo)
    all_display = {}
    all_display.update({k: cfg["name"] for k, cfg in STORES.items()})
    all_display.update({k: f"Glovo {cfg['name']}" for k, cfg in GLOVO_STORES.items()})

    store_counts = {}
    for sk in all_keys:
        count = len([p for p in final_products if p.get(sk)])
        store_counts[sk] = count
        if total_ref:
            pct = count / total_ref * 100
            extra = ""
            if sk == "lilly":
                oos = len([p for p in final_products
                           if p.get("lilly") and not p["lilly"].get("in_stock", True)])
                extra = f" — {oos} изчерпани"
                store_counts["lilly_oos"] = oos
            logger.info(f"{all_display.get(sk, sk)}: {count}/{total_ref} ({pct:.0f}%){extra}")

    # Примерни продукти — показваме EUR
    matched = [p for p in final_products
               if any(p.get(sk) for sk in all_keys)][:5]
    for p in matched:
        parts = [f"{p['name'][:50]}:"]
        for store in ["kashon"] + all_keys:
            if p.get(store):
                eur = p[store].get('eur')
                parts.append(f"  {store}={'%.2f' % eur if eur else 'N/A'}€")
        logger.info(" ".join(parts))

    total_time = time.time() - total_start

    # 5. Write to Google Sheets
    stats = {"total_products": total_ref, "kashon_products": kashon_count}
    for sk in all_keys:
        stats[f"{sk}_matches"] = store_counts.get(sk, 0)
    stats["lilly_out_of_stock"] = store_counts.get("lilly_oos", 0)
    write_to_sheets(final_products, stats)

    # 6. Email report
    send_email_report(final_products, stats)

    # 7. Save product list (with any new products discovered)
    if kashon_products:
        # Обновяваме Кашон цените в reference list
        kashon_matches = match_products(reference_products, kashon_products)
        for ref in reference_products:
            if ref["name"] in kashon_matches:
                m = kashon_matches[ref["name"]]
                ref["ref_eur"] = m.get("eur")
                ref["ref_bgn"] = m.get("bgn")
        save_product_list(reference_products)

    # 8. Save JSON results
    json_stats = {"total_products": total_ref, "kashon_products": kashon_count}
    for sk, prods in all_store_products.items():
        json_stats[f"{sk}_products"] = len(prods)
        json_stats[f"{sk}_matches"] = store_counts.get(sk, 0)
    json_stats["lilly_out_of_stock"] = store_counts.get("lilly_oos", 0)

    # Почистваме _flags от final_products за JSON (вътрешни полета)
    products_for_json = []
    for p in final_products:
        clean = {k: v for k, v in p.items() if not k.startswith("_")}
        products_for_json.append(clean)

    output = {
        "version": "v10.3",
        "date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "total_time": round(total_time, 2),
        "stores": len(STORES) + len(GLOVO_STORES),
        "stats": json_stats,
        "claude_validation": validation_log if validation_log else None,
        "products": products_for_json,
    }

    try:
        os.makedirs("data", exist_ok=True)
        with open("data/results.json", "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        logger.info("Резултати записани в data/results.json")
    except Exception as e:
        logger.error(f"Грешка при запис на JSON: {e}")

    logger.info(f"ГОТОВО за {total_time:.1f}s — {len(STORES) + len(GLOVO_STORES)} магазина, "
                f"{total_ref} продукта ({new_count} нови)")


if __name__ == "__main__":
    asyncio.run(main())
