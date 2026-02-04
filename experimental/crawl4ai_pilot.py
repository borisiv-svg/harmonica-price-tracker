"""
EXP-001: Crawl4AI Multi-Store Test v3
=====================================
Извлича продукти от Кашон Harmonica (официален източник)
и ги сравнява с Balev Bio Market.
"""

import asyncio
import time
import json
import os
import re

try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    CRAWL4AI_AVAILABLE = True
except ImportError:
    CRAWL4AI_AVAILABLE = False
    print("Crawl4AI not installed. Run: pip install crawl4ai")


# =============================================================================
# STORE CONFIGURATION
# =============================================================================

STORES = {
    "kashon": {
        "name": "Кашон Harmonica (Official)",
        "url": "https://kashonharmonica.bg/bg/products",
        "is_reference": True,  # Това е референтният източник
    },
    "balev": {
        "name": "Balev Bio Market",
        "url": "https://balevbiomarket.com/productBrands/harmonica",
        "is_reference": False,
    },
}


# =============================================================================
# CRAWLING FUNCTIONS
# =============================================================================

async def crawl_store(store_key, store_config):
    """
    Сканира един магазин и извлича продукти с цени.
    """
    store_name = store_config["name"]
    url = store_config["url"]
    
    print(f"\n{'=' * 60}")
    print(f"CRAWLING: {store_name}")
    print(f"URL: {url}")
    print("=" * 60)
    
    if not CRAWL4AI_AVAILABLE:
        print("ERROR: Crawl4AI not available")
        return None
    
    browser_config = BrowserConfig(
        headless=True,
        viewport_width=1920,
        viewport_height=1080,
    )
    
    crawler_config = CrawlerRunConfig(
        page_timeout=60000,
        remove_overlay_elements=True,
    )
    
    start_time = time.time()
    
    try:
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(
                url=url,
                config=crawler_config,
            )
            
            elapsed_time = time.time() - start_time
            
            if result.success:
                print(f"SUCCESS: Page loaded in {elapsed_time:.2f} seconds")
                print(f"HTML length: {len(result.html)} characters")
                print(f"Markdown length: {len(result.markdown)} characters")
                
                # Извличаме продукти
                products = extract_products(result.markdown, result.html, store_key)
                
                return {
                    "success": True,
                    "store": store_name,
                    "store_key": store_key,
                    "url": url,
                    "products": products,
                    "elapsed_time": elapsed_time,
                    "html_length": len(result.html),
                    "markdown_length": len(result.markdown),
                }
            else:
                print(f"ERROR: {result.error_message}")
                return {
                    "success": False,
                    "store": store_name,
                    "error": result.error_message,
                }
                
    except Exception as e:
        print(f"EXCEPTION: {str(e)}")
        return {
            "success": False,
            "store": store_name,
            "error": str(e),
        }


def extract_products(markdown, html, store_key):
    """
    Извлича продукти и цени от markdown/html.
    Използва различни patterns за различните магазини.
    """
    products = []
    
    # =========================================================================
    # PRICE EXTRACTION - Multiple patterns
    # =========================================================================
    
    price_patterns = [
        # Standard formats
        r'(\d+[.,]\d{2})\s*(?:лв|BGN|EUR|€)',
        r'(\d+[.,]\d{2})\s*лв\.',
        r'€\s*(\d+[.,]\d{2})',
        # HTML/JSON formats
        r'>(\d+[.,]\d{2})<',
        r'price["\s:]+(\d+[.,]\d{2})',
        r'"price":\s*"?(\d+[.,]\d{2})"?',
        r'data-price="(\d+[.,]\d{2})"',
    ]
    
    all_prices = []
    for pattern in price_patterns:
        found = re.findall(pattern, html, re.IGNORECASE)
        for p in found:
            try:
                price_str = p if isinstance(p, str) else p[0]
                price = float(price_str.replace(",", "."))
                if 0.50 <= price <= 100:
                    all_prices.append(price)
            except:
                pass
    
    unique_prices = sorted(list(set(all_prices)))
    print(f"Found {len(unique_prices)} unique prices")
    if unique_prices[:15]:
        print(f"Prices: {unique_prices[:15]}")
    
    # =========================================================================
    # PRODUCT NAME EXTRACTION from Markdown
    # =========================================================================
    
    # Търсим имена на продукти - обикновено са линкове или заглавия
    product_names = []
    
    # Pattern 1: Markdown links with product names
    link_pattern = r'\[([^\]]*(?:harmonica|био|Био|BIO)[^\]]*)\]'
    names_from_links = re.findall(link_pattern, markdown, re.IGNORECASE)
    product_names.extend(names_from_links)
    
    # Pattern 2: Lines that look like product names (contain weight)
    weight_line_pattern = r'([^\n]*\d+\s*(?:г|ml|мл|g|kg|кг|л|l)[^\n]*)'
    names_with_weight = re.findall(weight_line_pattern, markdown, re.IGNORECASE)
    
    # Филтрираме само релевантни
    for name in names_with_weight:
        name_clean = name.strip()
        if len(name_clean) > 10 and len(name_clean) < 100:
            # Проверяваме дали съдържа ключови думи
            keywords = ['harmonica', 'био', 'кисело', 'мляко', 'айран', 
                       'сирене', 'кашкавал', 'масло', 'сметана', 'локум',
                       'бисквити', 'вафл', 'сироп', 'лимонада', 'домат']
            if any(kw in name_clean.lower() for kw in keywords):
                product_names.append(name_clean)
    
    unique_names = list(set(product_names))[:50]  # Limit to 50
    print(f"Found {len(unique_names)} potential product names")
    if unique_names[:5]:
        print(f"Sample names: {unique_names[:5]}")
    
    # =========================================================================
    # HARMONICA-SPECIFIC EXTRACTION
    # =========================================================================
    
    # Търсим специфични Harmonica продукти
    harmonica_products = []
    
    # Pattern за продукт с цена
    product_price_pattern = r'([^\n]*[Hh]armonica[^\n]*?)[\s\n]+(\d+[.,]\d{2})\s*(?:лв|BGN|€)'
    matches = re.findall(product_price_pattern, markdown + html)
    
    for match in matches:
        name = match[0].strip()[:80]  # Limit name length
        try:
            price = float(match[1].replace(",", "."))
            if 0.50 <= price <= 100:
                harmonica_products.append({
                    "name": name,
                    "price": price,
                })
        except:
            pass
    
    print(f"Found {len(harmonica_products)} Harmonica-specific products with prices")
    
    return {
        "unique_prices": unique_prices,
        "product_names": unique_names,
        "harmonica_products": harmonica_products,
        "price_count": len(unique_prices),
        "name_count": len(unique_names),
    }


async def crawl_all_stores():
    """
    Сканира всички магазини последователно.
    """
    results = {}
    
    for store_key, store_config in STORES.items():
        result = await crawl_store(store_key, store_config)
        results[store_key] = result
        
        # Малка пауза между магазините
        await asyncio.sleep(2)
    
    return results


def compare_stores(results):
    """
    Сравнява цените между магазините.
    """
    print(f"\n{'=' * 60}")
    print("STORE COMPARISON")
    print("=" * 60)
    
    # Извличаме данни от всеки магазин
    store_data = {}
    
    for store_key, result in results.items():
        if result and result.get("success"):
            products = result.get("products", {})
            store_data[store_key] = {
                "name": result["store"],
                "prices": products.get("unique_prices", []),
                "price_count": products.get("price_count", 0),
                "product_names": products.get("product_names", []),
                "harmonica_products": products.get("harmonica_products", []),
            }
    
    # Показваме статистика за всеки магазин
    print("\n--- Store Statistics ---")
    for store_key, data in store_data.items():
        print(f"\n{data['name']}:")
        print(f"  Unique prices: {data['price_count']}")
        print(f"  Product names: {len(data['product_names'])}")
        print(f"  Harmonica products: {len(data['harmonica_products'])}")
        if data['prices']:
            print(f"  Price range: {min(data['prices']):.2f} - {max(data['prices']):.2f} лв")
    
    # Сравняваме цени между магазините
    if "kashon" in store_data and "balev" in store_data:
        kashon_prices = set(store_data["kashon"]["prices"])
        balev_prices = set(store_data["balev"]["prices"])
        
        # Намираме съвпадащи цени (с толеранс 5%)
        matching_prices = []
        for kp in kashon_prices:
            for bp in balev_prices:
                if abs(kp - bp) / kp < 0.05:  # 5% tolerance
                    matching_prices.append((kp, bp))
                    break
        
        print(f"\n--- Price Matching (5% tolerance) ---")
        print(f"Kashon prices: {len(kashon_prices)}")
        print(f"Balev prices: {len(balev_prices)}")
        print(f"Matching prices: {len(matching_prices)}")
        
        if kashon_prices:
            match_rate = len(matching_prices) / len(kashon_prices) * 100
            print(f"Match rate: {match_rate:.1f}%")
        
        return {
            "kashon_prices": len(kashon_prices),
            "balev_prices": len(balev_prices),
            "matching_prices": len(matching_prices),
            "match_rate": match_rate if kashon_prices else 0,
        }
    
    return {}


async def main():
    """
    Main function - сканира всички магазини и сравнява.
    """
    print("\n" + "=" * 60)
    print("EXP-001: CRAWL4AI MULTI-STORE TEST v3")
    print("=" * 60)
    print(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Stores to crawl: {len(STORES)}")
    
    total_start = time.time()
    
    # Сканираме всички магазини
    results = await crawl_all_stores()
    
    # Сравняваме резултатите
    comparison = compare_stores(results)
    
    total_elapsed = time.time() - total_start
    
    # Обобщение
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print("=" * 60)
    print(f"Total execution time: {total_elapsed:.2f} seconds")
    
    successful = sum(1 for r in results.values() if r and r.get("success"))
    print(f"Successful crawls: {successful}/{len(STORES)}")
    
    for store_key, result in results.items():
        if result and result.get("success"):
            print(f"  {result['store']}: {result['elapsed_time']:.2f}s, "
                  f"{result['products']['price_count']} prices")
        else:
            error = result.get("error", "Unknown") if result else "No result"
            print(f"  {STORES[store_key]['name']}: FAILED - {error[:50]}")
    
    if comparison:
        print(f"\nPrice match rate: {comparison.get('match_rate', 0):.1f}%")
    
    # Записваме резултатите
    output = {
        "experiment": "EXP-001-v3",
        "date": time.strftime('%Y-%m-%d %H:%M:%S'),
        "total_time": total_elapsed,
        "stores": results,
        "comparison": comparison,
    }
    
    try:
        os.makedirs("experimental", exist_ok=True)
        with open("experimental/pilot_results.json", "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2, default=str)
        print(f"\nResults saved to: experimental/pilot_results.json")
    except Exception as e:
        print(f"\nCould not save results: {e}")
    
    print(f"\n{'=' * 60}")
    print("END OF MULTI-STORE TEST")
    print("=" * 60)
    
    return output


if __name__ == "__main__":
    asyncio.run(main())
