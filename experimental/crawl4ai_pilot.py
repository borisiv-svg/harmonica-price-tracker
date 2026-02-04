"""
EXP-001: Crawl4AI Pilot Test v2
===============================
Подобрена версия, използваща JsonCssExtractionStrategy
за структурирано извличане без LLM разходи.
"""

import asyncio
import time
import json
import os
import re

try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    from crawl4ai.extraction_strategy import JsonCssExtractionStrategy
    CRAWL4AI_AVAILABLE = True
except ImportError:
    CRAWL4AI_AVAILABLE = False
    print("Crawl4AI not installed. Run: pip install crawl4ai")


# =============================================================================
# CONFIGURATION
# =============================================================================

BALEV_URL = "https://balevbiomarket.com/productBrands/harmonica"

# Референтни продукти за валидация
REFERENCE_PRODUCTS = [
    {"name": "Био Локум роза", "weight": "140г", "ref_price": 3.81},
    {"name": "Био тънки претцели", "weight": "80г", "ref_price": 2.50},
    {"name": "Био лимонада", "weight": "330мл", "ref_price": 3.48},
    {"name": "Айран harmonica", "weight": "500мл", "ref_price": 2.90},
    {"name": "Био сироп от липа", "weight": "750мл", "ref_price": 14.29},
]

# =============================================================================
# SCHEMA FOR BALEV BIO MARKET
# =============================================================================

# Тази схема дефинира как да извлечем продукти от HTML структурата на Balev
# Ще я настроим след като видим реалната структура

BALEV_SCHEMA = {
    "name": "harmonica_products",
    "baseSelector": ".product-item, .product-card, .product, [class*='product']",
    "fields": [
        {
            "name": "title",
            "selector": "h2, h3, .product-name, .product-title, [class*='name'], [class*='title']",
            "type": "text"
        },
        {
            "name": "price",
            "selector": ".price, .product-price, [class*='price'], span[class*='price']",
            "type": "text"
        },
        {
            "name": "weight",
            "selector": ".weight, .volume, [class*='weight'], [class*='volume']",
            "type": "text"
        },
        {
            "name": "link",
            "selector": "a",
            "type": "attribute",
            "attribute": "href"
        }
    ]
}


# =============================================================================
# MAIN FUNCTIONS
# =============================================================================

async def crawl_with_schema_extraction():
    """
    Използва JsonCssExtractionStrategy за структурирано извличане.
    Това е препоръчаният подход от Crawl4AI документацията.
    """
    print("\n" + "=" * 60)
    print("METHOD 1: JsonCssExtractionStrategy")
    print("=" * 60)
    
    if not CRAWL4AI_AVAILABLE:
        print("ERROR: Crawl4AI not available")
        return None
    
    browser_config = BrowserConfig(
        headless=True,
        viewport_width=1920,
        viewport_height=1080,
    )
    
    # Създаваме extraction strategy от схемата
    extraction_strategy = JsonCssExtractionStrategy(schema=BALEV_SCHEMA)
    
    crawler_config = CrawlerRunConfig(
        page_timeout=60000,
        wait_for="css:.product, css:[class*='product']",  # Чакаме продуктите да се заредят
        extraction_strategy=extraction_strategy,
        remove_overlay_elements=True,
    )
    
    start_time = time.time()
    
    try:
        async with AsyncWebCrawler(config=browser_config) as crawler:
            print(f"\nLoading {BALEV_URL}")
            
            result = await crawler.arun(
                url=BALEV_URL,
                config=crawler_config,
            )
            
            elapsed_time = time.time() - start_time
            
            if result.success:
                print(f"SUCCESS: Page loaded in {elapsed_time:.2f} seconds")
                print(f"HTML length: {len(result.html)} characters")
                
                # Извличаме структурираните данни
                extracted_data = []
                if result.extracted_content:
                    try:
                        extracted_data = json.loads(result.extracted_content)
                        print(f"Extracted {len(extracted_data)} products with schema")
                    except json.JSONDecodeError:
                        print(f"Could not parse extracted content as JSON")
                        print(f"Raw content: {result.extracted_content[:500]}")
                
                return {
                    "success": True,
                    "method": "JsonCssExtractionStrategy",
                    "products": extracted_data,
                    "html_length": len(result.html),
                    "elapsed_time": elapsed_time,
                }
            else:
                print(f"ERROR: {result.error_message}")
                return {
                    "success": False,
                    "error": result.error_message,
                    "elapsed_time": elapsed_time,
                }
                
    except Exception as e:
        elapsed_time = time.time() - start_time
        print(f"EXCEPTION: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "elapsed_time": elapsed_time,
        }


async def crawl_with_markdown_analysis():
    """
    Алтернативен подход: извличаме markdown и анализираме.
    Полезно за разбиране на структурата на сайта.
    """
    print("\n" + "=" * 60)
    print("METHOD 2: Markdown Analysis")
    print("=" * 60)
    
    if not CRAWL4AI_AVAILABLE:
        return None
    
    browser_config = BrowserConfig(
        headless=True,
        viewport_width=1920,
        viewport_height=1080,
    )
    
    crawler_config = CrawlerRunConfig(
        page_timeout=60000,
        wait_for="css:body",
        remove_overlay_elements=True,
    )
    
    start_time = time.time()
    
    try:
        async with AsyncWebCrawler(config=browser_config) as crawler:
            print(f"\nLoading {BALEV_URL}")
            
            result = await crawler.arun(
                url=BALEV_URL,
                config=crawler_config,
            )
            
            elapsed_time = time.time() - start_time
            
            if result.success:
                print(f"SUCCESS: Page loaded in {elapsed_time:.2f} seconds")
                print(f"Markdown length: {len(result.markdown)} characters")
                
                # Анализираме markdown за продукти
                products = analyze_markdown_for_products(result.markdown)
                
                # Показваме извадка от markdown за debug
                print(f"\n--- Markdown Sample (first 2000 chars) ---")
                print(result.markdown[:2000])
                
                return {
                    "success": True,
                    "method": "Markdown Analysis",
                    "products": products,
                    "markdown_length": len(result.markdown),
                    "elapsed_time": elapsed_time,
                }
            else:
                return {"success": False, "error": result.error_message}
                
    except Exception as e:
        return {"success": False, "error": str(e)}


def analyze_markdown_for_products(markdown):
    """
    Анализира markdown текст за продукти и цени.
    """
    products = []
    
    # Търсим цени в markdown (различни формати)
    price_patterns = [
        r'(\d+[.,]\d{2})\s*(?:лв|BGN|EUR|€)',
        r'(\d+[.,]\d{2})\s*лв\.',
        r'€\s*(\d+[.,]\d{2})',
    ]
    
    all_prices = []
    for pattern in price_patterns:
        found = re.findall(pattern, markdown, re.IGNORECASE)
        all_prices.extend(found)
    
    # Филтрираме валидни цени
    valid_prices = []
    for p in all_prices:
        try:
            price = float(str(p).replace(",", "."))
            if 0.50 <= price <= 100:
                valid_prices.append(price)
        except:
            pass
    
    unique_prices = list(set(valid_prices))
    print(f"Found {len(unique_prices)} unique prices in markdown")
    if unique_prices[:10]:
        print(f"Sample prices: {sorted(unique_prices)[:10]}")
    
    return {
        "prices_found": len(valid_prices),
        "unique_prices": unique_prices,
    }


async def discover_html_structure():
    """
    Помощна функция за откриване на HTML структурата.
    Помага да разберем какви CSS селектори да използваме.
    """
    print("\n" + "=" * 60)
    print("METHOD 3: HTML Structure Discovery")
    print("=" * 60)
    
    if not CRAWL4AI_AVAILABLE:
        return None
    
    browser_config = BrowserConfig(headless=True)
    
    crawler_config = CrawlerRunConfig(
        page_timeout=60000,
        wait_for="css:body",
    )
    
    try:
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=BALEV_URL, config=crawler_config)
            
            if result.success:
                html = result.html
                
                # Търсим често срещани CSS класове за продукти
                product_patterns = [
                    r'class="([^"]*product[^"]*)"',
                    r'class="([^"]*item[^"]*)"',
                    r'class="([^"]*card[^"]*)"',
                    r'class="([^"]*price[^"]*)"',
                ]
                
                print("\n--- Found CSS classes ---")
                for pattern in product_patterns:
                    matches = re.findall(pattern, html, re.IGNORECASE)
                    unique_matches = list(set(matches))[:5]
                    if unique_matches:
                        print(f"Pattern '{pattern[:30]}': {unique_matches}")
                
                # Търсим data атрибути
                data_attrs = re.findall(r'data-([a-z-]+)="([^"]*)"', html, re.IGNORECASE)
                unique_attrs = list(set([d[0] for d in data_attrs]))[:10]
                print(f"\nData attributes found: {unique_attrs}")
                
                # Показваме извадка около "Harmonica"
                harmonica_context = re.findall(r'.{0,200}[Hh]armonica.{0,200}', html)
                if harmonica_context:
                    print(f"\n--- HTML around 'Harmonica' ---")
                    print(harmonica_context[0][:400])
                
                return {"success": True, "html_length": len(html)}
            else:
                return {"success": False}
                
    except Exception as e:
        print(f"Error: {e}")
        return {"success": False, "error": str(e)}


def compare_with_reference(results):
    """
    Сравнява намерените продукти с референтните.
    """
    print("\n" + "=" * 60)
    print("COMPARISON WITH REFERENCE")
    print("=" * 60)
    
    if not results:
        print("No results to compare")
        return {"matches": 0, "total": len(REFERENCE_PRODUCTS)}
    
    # Събираме всички намерени цени
    all_prices = []
    
    for result in results:
        if result and result.get("success"):
            products = result.get("products", {})
            
            if isinstance(products, list):
                # От JsonCssExtractionStrategy
                for p in products:
                    if isinstance(p, dict) and "price" in p:
                        try:
                            price_str = re.sub(r'[^\d.,]', '', str(p["price"]))
                            price = float(price_str.replace(",", "."))
                            if 0.50 <= price <= 100:
                                all_prices.append(price)
                        except:
                            pass
            elif isinstance(products, dict):
                # От markdown analysis
                all_prices.extend(products.get("unique_prices", []))
    
    unique_prices = list(set(all_prices))
    print(f"\nTotal unique prices found: {len(unique_prices)}")
    print(f"Prices: {sorted(unique_prices)[:15]}")
    
    # Сравняваме с референтни (10% толеранс)
    matches = 0
    for ref in REFERENCE_PRODUCTS:
        ref_price = ref["ref_price"]
        found = any(abs(p - ref_price) / ref_price < 0.10 for p in unique_prices)
        status = "FOUND" if found else "NOT FOUND"
        print(f"  [{status}] {ref['name']} - {ref_price} lv")
        if found:
            matches += 1
    
    match_rate = (matches / len(REFERENCE_PRODUCTS)) * 100
    print(f"\nMatch rate: {matches}/{len(REFERENCE_PRODUCTS)} ({match_rate:.0f}%)")
    
    return {"matches": matches, "total": len(REFERENCE_PRODUCTS), "match_rate": match_rate}


async def main():
    """
    Изпълнява всички методи и сравнява резултатите.
    """
    print("\n" + "=" * 60)
    print("EXP-001: CRAWL4AI PILOT TEST v2")
    print("=" * 60)
    print(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Store: Balev Bio Market")
    print(f"URL: {BALEV_URL}")
    
    results = []
    
    # Метод 1: Schema-based extraction
    result1 = await crawl_with_schema_extraction()
    results.append(result1)
    
    # Метод 2: Markdown analysis
    result2 = await crawl_with_markdown_analysis()
    results.append(result2)
    
    # Метод 3: HTML structure discovery (за debug)
    result3 = await discover_html_structure()
    results.append(result3)
    
    # Сравнение с референтни продукти
    comparison = compare_with_reference(results)
    
    # Обобщение
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    for i, result in enumerate(results, 1):
        if result and result.get("success"):
            method = result.get("method", f"Method {i}")
            elapsed = result.get("elapsed_time", 0)
            print(f"Method {i} ({method}): SUCCESS in {elapsed:.2f}s")
        else:
            print(f"Method {i}: FAILED")
    
    print(f"\nOverall price match rate: {comparison.get('match_rate', 0):.0f}%")
    
    # Записваме резултатите
    output = {
        "experiment": "EXP-001-v2",
        "date": time.strftime('%Y-%m-%d %H:%M:%S'),
        "store": "Balev Bio Market",
        "results": results,
        "comparison": comparison,
    }
    
    try:
        os.makedirs("experimental", exist_ok=True)
        with open("experimental/pilot_results.json", "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2, default=str)
        print(f"\nResults saved to: experimental/pilot_results.json")
    except Exception as e:
        print(f"\nCould not save results: {e}")
    
    print("\n" + "=" * 60)
    print("END OF PILOT TEST v2")
    print("=" * 60)
    
    return output


if __name__ == "__main__":
    asyncio.run(main())
