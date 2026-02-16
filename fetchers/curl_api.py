"""
Harmonica Price Tracker — curl_cffi API Fetchers
==================================================
Direct API fetchers using curl_cffi for TLS impersonation.
Includes DM Algolia API, Lilly Magento GraphQL/REST, T-Market CloudCart.
"""

import re
import time

from config import CURL_CFFI_AVAILABLE, EUR_BGN_RATE, FIRECRAWL_API_KEY, STORES, logger

if CURL_CFFI_AVAILABLE:
    from curl_cffi.requests import AsyncSession as CurlAsyncSession

from utils import detect_cloudflare_challenge, is_food_product
from extractors import extract_dm_from_curl_html


# =============================================================================
# DM ALGOLIA API — direct query bypass (без Cloudflare)
# =============================================================================

async def extract_algolia_config(html_text):
    """
    Извлича Algolia конфигурация от HTML/JS на DM.bg.

    Търси appId, apiKey и indexName в:
    - window.__INITIAL_STATE__ / window.__NEXT_DATA__
    - Inline <script> tags с algolia config
    - data-* атрибути
    """
    if not html_text:
        return None

    config = {}

    # Pattern 1: applicationId / appId
    app_id_patterns = [
        r'(?:applicationId|appId|algoliaAppId|ALGOLIA_APP_ID)["\s:=]+["\']([A-Z0-9]{10,})["\']',
        r'X-Algolia-Application-Id["\s:=]+["\']([A-Z0-9]{10,})["\']',
        r'"appId"\s*:\s*"([A-Z0-9]{10,})"',
    ]
    for pattern in app_id_patterns:
        match = re.search(pattern, html_text, re.IGNORECASE)
        if match:
            config['app_id'] = match.group(1)
            break

    # Pattern 2: searchOnlyApiKey / apiKey
    api_key_patterns = [
        r'(?:searchOnlyApiKey|apiKey|algoliaApiKey|ALGOLIA_API_KEY|searchKey)["\s:=]+["\']([a-f0-9]{20,})["\']',
        r'X-Algolia-API-Key["\s:=]+["\']([a-f0-9]{20,})["\']',
        r'"apiKey"\s*:\s*"([a-f0-9]{20,})"',
    ]
    for pattern in api_key_patterns:
        match = re.search(pattern, html_text, re.IGNORECASE)
        if match:
            config['api_key'] = match.group(1)
            break

    # Pattern 3: indexName
    index_patterns = [
        r'(?:indexName|algoliaIndex|ALGOLIA_INDEX)["\s:=]+["\']([a-zA-Z0-9_\-]+(?:product|search|bg)[a-zA-Z0-9_\-]*)["\']',
        r'"indexName"\s*:\s*"([^"]+)"',
    ]
    for pattern in index_patterns:
        match = re.search(pattern, html_text, re.IGNORECASE)
        if match:
            config['index_name'] = match.group(1)
            break

    if config.get('app_id') and config.get('api_key'):
        logger.info(f"Algolia config extracted: appId={config['app_id']}, "
                     f"index={config.get('index_name', 'N/A')}")
        return config

    return None


async def fetch_dm_via_algolia(query="harmonica"):
    """
    Опит за директна Algolia API заявка за DM Bulgaria.

    Стратегия:
    1. curl_cffi fetch на dm.bg → извличане на Algolia ключове от JS
    2. Директна Algolia API заявка с намерените ключове
    3. Парсване на JSON отговора в продуктов формат

    Връща dict с "success", "products", "method".
    """
    if not CURL_CFFI_AVAILABLE:
        logger.warning("DM Algolia: curl_cffi не е наличен")
        return {"success": False, "error": "curl_cffi not available"}

    logger.info("DM Algolia: опит за директна API заявка...")
    start = time.time()

    try:
        async with CurlAsyncSession(impersonate="chrome") as session:


            # Стъпка 1: Fetch dm.bg за Algolia config
            logger.info("DM Algolia: извличане на конфигурация от dm.bg...")
            resp = await session.get(
                "https://www.dm-drogeriemarkt.bg/search?query=harmonica&searchType=product",

                timeout=30,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "bg-BG,bg;q=0.9,en;q=0.8",
                },
            )

            if resp.status_code != 200:
                logger.warning(f"DM Algolia: HTTP {resp.status_code} при fetch на dm.bg")
                return {"success": False, "error": f"HTTP {resp.status_code}"}

            html = resp.text

            # Стъпка 2: Извличане на Algolia config
            config = await extract_algolia_config(html)

            if not config:
                # Пробваме да намерим JS bundle URLs
                js_urls = re.findall(
                    r'(?:src|href)=["\']([^"\']*(?:chunk|main|app|search|algolia)[^"\']*\.js)["\']',
                    html
                )
                for js_url in js_urls[:5]:
                    if not js_url.startswith('http'):
                        js_url = f"https://www.dm-drogeriemarkt.bg{js_url}"
                    try:
                        js_resp = await session.get(js_url, timeout=15)
                        if js_resp.status_code == 200:
                            config = await extract_algolia_config(js_resp.text)
                            if config:
                                logger.info(f"DM Algolia: config намерен в {js_url}")
                                break
                    except Exception:
                        continue

            if not config:
                elapsed = time.time() - start
                logger.warning(f"DM Algolia: не може да се извлече конфигурация ({elapsed:.1f}s)")
                # Връщаме HTML за BS4 парсване като fallback
                return {
                    "success": True,
                    "method": "curl_cffi_html",
                    "html": html,
                    "markdown": "",
                    "products": [],
                    "elapsed": elapsed,
                }

            # Стъпка 3: Algolia API заявка
            app_id = config['app_id']
            api_key = config['api_key']
            index_name = config.get('index_name', 'prod_search_bg')

            algolia_url = f"https://{app_id}-dsn.algolia.net/1/indexes/{index_name}/query"
            algolia_resp = await session.post(
                algolia_url,

                timeout=15,
                headers={
                    "X-Algolia-Application-Id": app_id,
                    "X-Algolia-API-Key": api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "query": query,
                    "hitsPerPage": 50,
                    "attributesToRetrieve": [
                        "name", "title", "price", "brand", "url",
                        "gtin", "image", "slug", "description",
                    ],
                },
            )

            if algolia_resp.status_code != 200:
                logger.warning(f"DM Algolia API: HTTP {algolia_resp.status_code}")
                # Fallback: парсваме HTML от стъпка 1
                return {
                    "success": True,
                    "method": "curl_cffi_html",
                    "html": html,
                    "markdown": "",
                    "products": [],
                    "elapsed": time.time() - start,
                }

            algolia_data = algolia_resp.json()
            hits = algolia_data.get("hits", [])
            elapsed = time.time() - start

            # Стъпка 4: Парсване на Algolia резултати
            products = []
            for hit in hits:
                product_name = hit.get("name") or hit.get("title") or ""
                if not product_name:
                    continue

                price = hit.get("price")
                price_bgn = None
                price_eur = None

                if isinstance(price, (int, float)):
                    price_bgn = round(float(price), 2)
                elif isinstance(price, dict):
                    price_bgn = price.get("BGN") or price.get("bgn") or price.get("value")
                    if price_bgn:
                        price_bgn = round(float(price_bgn), 2)

                if price_bgn and not price_eur:
                    price_eur = round(price_bgn / EUR_BGN_RATE, 2)

                if product_name and price_bgn:
                    products.append({
                        "name": product_name,
                        "eur": price_eur,
                        "bgn": price_bgn,
                    })

            logger.info(f"DM Algolia: {len(products)} продукта от {len(hits)} hits ({elapsed:.1f}s)")
            return {
                "success": True,
                "method": "algolia_api",
                "products": products,
                "elapsed": elapsed,
                "html": html,
            }

    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"DM Algolia грешка: {e} ({elapsed:.1f}s)")
        return {"success": False, "error": str(e)}


# =============================================================================
# LILLY curl_cffi + Magento GraphQL API
# =============================================================================

async def fetch_lilly_via_curl():
    """
    Директен fetch на Lilly продукти чрез Magento 2 GraphQL API.
    Lilly използва Hyvä Theme — продуктите се зареждат с JavaScript.
    GraphQL API-то връща JSON без нужда от browser rendering.
    """
    if not CURL_CFFI_AVAILABLE:
        return {"success": False, "error": "curl_cffi not available"}

    logger.info("Lilly: curl_cffi GraphQL API fetch...")
    start = time.time()

    graphql_query = """
    {
      products(
        search: "harmonica"
        pageSize: 50
      ) {
        total_count
        items {
          name
          sku
          url_key
          price_range {
            minimum_price {
              regular_price { value currency }
              final_price { value currency }
            }
          }
          stock_status
        }
      }
    }
    """

    try:
        async with CurlAsyncSession(impersonate="chrome") as session:


            # Опит 1: GraphQL API
            try:
                resp = await session.post(
                    "https://lillydrogerie.bg/graphql",

                    timeout=30,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "Store": "default",
                    },
                    json={"query": graphql_query},
                )

                if resp.status_code == 200:
                    data = resp.json()
                    items = (data.get("data", {}).get("products", {})
                             .get("items", []))

                    if items:
                        products = []
                        for item in items:
                            name = item.get("name", "")
                            if not name:
                                continue

                            price_range = item.get("price_range", {})
                            min_price = price_range.get("minimum_price", {})
                            final = min_price.get("final_price", {})
                            regular = min_price.get("regular_price", {})

                            price_val = final.get("value") or regular.get("value")
                            currency = final.get("currency") or regular.get("currency", "BGN")

                            if price_val:
                                price_bgn = round(float(price_val), 2)
                                price_eur = round(price_bgn / EUR_BGN_RATE, 2)
                                in_stock = item.get("stock_status") != "OUT_OF_STOCK"

                                products.append({
                                    "name": name,
                                    "eur": price_eur,
                                    "bgn": price_bgn,
                                    "in_stock": in_stock,
                                })

                        elapsed = time.time() - start
                        total = data.get("data", {}).get("products", {}).get("total_count", 0)
                        logger.info(f"Lilly GraphQL: {len(products)} продукта от "
                                    f"{total} total ({elapsed:.1f}s)")
                        return {
                            "success": True,
                            "method": "graphql",
                            "products": products,
                            "elapsed": elapsed,
                        }
                    else:
                        logger.info(f"Lilly GraphQL: 0 items, response keys: "
                                    f"{list(data.get('data', {}).get('products', {}).keys())}")
                else:
                    logger.info(f"Lilly GraphQL: HTTP {resp.status_code}")
            except Exception as e:
                logger.info(f"Lilly GraphQL: {e}")

            # Опит 2: REST API search
            try:
                rest_url = ("https://lillydrogerie.bg/rest/V1/products?"
                            "searchCriteria[filter_groups][0][filters][0][field]=name"
                            "&searchCriteria[filter_groups][0][filters][0][value]=%25harmonica%25"
                            "&searchCriteria[filter_groups][0][filters][0][condition_type]=like"
                            "&searchCriteria[pageSize]=50")
                resp = await session.get(
                    rest_url,

                    timeout=30,
                    headers={"Accept": "application/json"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("items", [])
                    if items:
                        products = []
                        for item in items:
                            name = item.get("name", "")
                            price = item.get("price")
                            if name and price:
                                price_bgn = round(float(price), 2)
                                price_eur = round(price_bgn / EUR_BGN_RATE, 2)
                                products.append({
                                    "name": name,
                                    "eur": price_eur,
                                    "bgn": price_bgn,
                                    "in_stock": True,
                                })
                        if products:
                            elapsed = time.time() - start
                            logger.info(f"Lilly REST: {len(products)} продукта ({elapsed:.1f}s)")
                            return {
                                "success": True,
                                "method": "rest_api",
                                "products": products,
                                "elapsed": elapsed,
                            }
                else:
                    logger.info(f"Lilly REST: HTTP {resp.status_code}")
            except Exception as e:
                logger.info(f"Lilly REST: {e}")

            elapsed = time.time() - start
            logger.warning(f"Lilly curl_cffi: нито GraphQL, нито REST API работят ({elapsed:.1f}s)")
            return {"success": False, "error": "GraphQL and REST API both failed"}

    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"Lilly curl_cffi грешка: {e} ({elapsed:.1f}s)")
        return {"success": False, "error": str(e)}


# =============================================================================
# T-MARKET curl_cffi — CloudCart + Cloudflare bypass
# =============================================================================

async def fetch_tmarket_via_curl(url="https://tmarketonline.bg/vendor/harmonica-1881705916"):
    """
    Директен fetch на T-Market чрез curl_cffi (TLS impersonation).
    T-Market е CloudCart сайт с Cloudflare — curl_cffi може да bypass-не.
    """
    if not CURL_CFFI_AVAILABLE:
        return {"success": False, "error": "curl_cffi not available"}

    logger.info("T-Market: curl_cffi директен fetch...")
    start = time.time()

    try:
        async with CurlAsyncSession(impersonate="chrome") as session:

            resp = await session.get(
                url,

                timeout=30,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "bg-BG,bg;q=0.9,en;q=0.8",
                },
            )

            elapsed = time.time() - start

            if resp.status_code != 200:
                logger.warning(f"T-Market curl_cffi: HTTP {resp.status_code}")
                return {"success": False, "error": f"HTTP {resp.status_code}"}

            html = resp.text

            # Проверка за Cloudflare challenge
            is_challenge, sitekey = detect_cloudflare_challenge(html)
            if is_challenge:
                logger.warning(f"T-Market curl_cffi: Cloudflare challenge ({elapsed:.1f}s)")
                return {
                    "success": False,
                    "error": "Cloudflare challenge via curl_cffi",
                    "html": html,
                    "sitekey": sitekey,
                }

            logger.info(f"T-Market curl_cffi: OK {elapsed:.1f}s, {len(html)} chars")
            return {
                "success": True,
                "method": "curl_cffi",
                "html": html,
                "markdown": "",
                "elapsed": elapsed,
                "store_key": "tmarket",
            }

    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"T-Market curl_cffi грешка: {e} ({elapsed:.1f}s)")
        return {"success": False, "error": str(e)}
