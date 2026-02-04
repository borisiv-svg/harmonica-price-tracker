"""
EXP-001: Crawl4AI Multi-Store Test v4
=====================================
Подобрена версия с:
- eBag добавен като магазин
- Двойни цени EUR/BGN (EUR е водещо)
- Филтриране само на хранителни продукти
- Паралелно сканиране с arun_many()
- Подобрено извличане за Balev
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
        "name": "Kashon Harmonica (Official)",
        "url": "https://kashonharmonica.bg/bg/products",
        "is_reference": True,
        "needs_scroll": True,
    },
    "balev": {
        "name": "Balev Bio Market",
        "url": "https://balevbiomarket.com/productBrands/harmonica",
        "is_reference": False,
        "needs_scroll": True,
    },
    "ebag": {
        "name": "eBag.bg",
        "url": "https://www.ebag.bg/brands/harmonica?page=1&limit=100",
        "is_reference": False,
        "needs_scroll": False,
    },
}

# =============================================================================
# FOOD PRODUCT CATEGORIES (за филтриране)
# =============================================================================

# Ключови думи за ХРАНИТЕЛНИ продукти
FOOD_KEYWORDS = [
    # Млечни продукти
    "мляко", "кисело", "айран", "сирене", "кашкавал", "масло", "сметана",
    "йогурт", "извара", "крема",
    # Напитки
    "сок", "лимонада", "нектар", "напитка", "вода",
    # Сладки и снаксове
    "локум", "бисквити", "вафла", "шоколад", "бонбони", "десерт",
    "сладко", "мармалад", "халва", "тахан",
    # Зърнени и снаксове
    "претцел", "солет", "крекер", "чипс", "пуканки", "ядки",
    "лешник", "бадем", "орех", "фъстък", "соленки",
    "мюсли", "овесен", "зърнена", "гранола",
    # Консерви и сосове
    "доматено", "домат", "кетчуп", "лютеница", "пюре", "паста",
    "сироп", "мед", "конфитюр",
    # Други храни
    "хляб", "питка", "кори", "тесто", "брашно",
    "олио", "оцет", "зехтин",
    "подправка", "билка", "чай", "кафе",
    "яйца", "яйце",
    "пюре", "каша", "бебешк",
    # Месо и риба (ако има)
    "салам", "шунка", "кренвирш", "риба", "пастет",
    # Плодове и зеленчуци
    "плод", "зеленчук", "морков", "ябълка", "круша", "слива",
]

# Ключови думи за НЕ-ХРАНИТЕЛНИ продукти (да се изключат)
NON_FOOD_KEYWORDS = [
    "потник", "тениска", "блуза", "панталон", "дреха", "шапка",
    "чанта", "раница", "торба", "сак",
    "козметика", "крем", "шампоан", "сапун", "гел", "лосион",
    "бебешк" "памперс", "пелена",
    "почиств", "препарат", "домакинск",
    "играчка", "книга", "списание",
]


# =============================================================================
# DUAL CURRENCY PRICE EXTRACTION
# =============================================================================

def extract_dual_prices(text):
    """
    Извлича цени в EUR и BGN от текст.
    Връща списък от dict с eur и bgn цени.
    """
    prices = []
    
    # Pattern за EUR цени
    eur_patterns = [
        r'(\d+[.,]\d{2})\s*(?:€|EUR|eur|евро)',
        r'(?:€|EUR)\s*(\d+[.,]\d{2})',
        r'(\d+[.,]\d{2})\s*€',
    ]
    
    # Pattern за BGN цени
    bgn_patterns = [
        r'(\d+[.,]\d{2})\s*(?:лв|лева|BGN|bgn)',
        r'(\d+[.,]\d{2})\s*лв\.',
        r'(?:BGN|лв)\s*(\d+[.,]\d{2})',
    ]
    
    # Извличаме EUR цени
    eur_prices = []
    for pattern in eur_patterns:
        found = re.findall(pattern, text, re.IGNORECASE)
        for p in found:
            try:
                price = float(str(p).replace(",", "."))
                if 0.20 <= price <= 50:  # EUR range
                    eur_prices.append(price)
            except:
                pass
    
    # Извличаме BGN цени
    bgn_prices = []
    for pattern in bgn_patterns:
        found = re.findall(pattern, text, re.IGNORECASE)
        for p in found:
            try:
                price = float(str(p).replace(",", "."))
                if 0.50 <= price <= 100:  # BGN range
                    bgn_prices.append(price)
            except:
                pass
    
    # Извличаме и числа между тагове (за сайтове без валутен символ)
    bare_prices = re.findall(r'>(\d+[.,]\d{2})<', text)
    for p in bare_prices:
        try:
            price = float(str(p).replace(",", "."))
            if 0.50 <= price <= 100:
                bgn_prices.append(price)
        except:
            pass
    
    return {
        "eur": sorted(list(set(eur_prices))),
        "bgn": sorted(list(set(bgn_prices))),
    }


def is_food_product(name):
    """
    Проверява дали продукт е хранителен.
    """
    name_lower = name.lower()
    
    # Първо проверяваме за не-хранителни ключови думи
    for keyword in NON_FOOD_KEYWORDS:
        if keyword in name_lower:
            return False
    
    # После проверяваме за хранителни ключови думи
    for keyword in FOOD_KEYWORDS:
        if keyword in name_lower:
            return True
    
    # Ако няма ясни индикатори, приемаме за храна
    # (по-добре да включим повече, отколкото да пропуснем)
    return True


# =============================================================================
# PRODUCT EXTRACTION
# =============================================================================

def extract_products_advanced(markdown, html, store_key):
    """
    Подобрено извличане на продукти с двойни цени и филтриране.
    """
    products = []
    
    # Извличаме двойни цени
    dual_prices = extract_dual_prices(html + markdown)
    
    print(f"  EUR prices found: {len(dual_prices['eur'])}")
    print(f"  BGN prices found: {len(dual_prices['bgn'])}")
    
    if dual_prices['eur'][:10]:
        print(f"  EUR sample: {dual_prices['eur'][:10]}")
    if dual_prices['bgn'][:10]:
        print(f"  BGN sample: {dual_prices['bgn'][:10]}")
    
    # Извличаме имена на продукти
    product_names = extract_product_names(markdown, store_key)
    
    # Филтрираме само хранителни продукти
    food_products = [name for name in product_names if is_food_product(name)]
    non_food = [name for name in product_names if not is_food_product(name)]
    
    print(f"  Total product names: {len(product_names)}")
    print(f"  Food products: {len(food_products)}")
    print(f"  Non-food filtered out: {len(non_food)}")
    
    if non_food[:3]:
        print(f"  Filtered examples: {non_food[:3]}")
    
    # Извличаме продукти с цени (Harmonica специфични)
    harmonica_products = extract_harmonica_products(markdown, html)
    
    # Филтрираме само хранителни Harmonica продукти
    food_harmonica = [p for p in harmonica_products if is_food_product(p.get("name", ""))]
    
    print(f"  Harmonica products with prices: {len(harmonica_products)}")
    print(f"  Harmonica FOOD products: {len(food_harmonica)}")
    
    return {
        "prices": dual_prices,
        "product_names": food_products,
        "harmonica_products": food_harmonica,
        "stats": {
            "eur_count": len(dual_prices["eur"]),
            "bgn_count": len(dual_prices["bgn"]),
            "food_count": len(food_products),
            "harmonica_count": len(food_harmonica),
        }
    }


def extract_product_names(markdown, store_key):
    """
    Извлича имена на продукти от markdown.
    """
    names = []
    
    # Pattern за markdown линкове
    link_pattern = r'\[([^\]]+)\]\([^\)]+\)'
    links = re.findall(link_pattern, markdown)
    
    # Pattern за продукти с грамаж
    weight_pattern = r'([^\n\[\]]{5,80}?\d+\s*(?:г|ml|мл|g|kg|кг|л|l)[^\n\[\]]{0,20})'
    weighted = re.findall(weight_pattern, markdown, re.IGNORECASE)
    
    # Комбинираме и филтрираме
    all_names = links + weighted
    
    seen = set()
    for name in all_names:
        # Почистваме името
        clean = name.strip()
        clean = re.sub(r'\s+', ' ', clean)  # Премахваме излишни интервали
        clean = clean[:100]  # Ограничаваме дължината
        
        # Филтрираме невалидни
        if len(clean) < 5:
            continue
        if clean.lower() in seen:
            continue
        if clean.startswith('http'):
            continue
        if clean.count('/') > 2:
            continue
            
        # Проверяваме дали е продукт (има грамаж или ключова дума)
        has_weight = bool(re.search(r'\d+\s*(?:г|ml|мл|g|kg|л)', clean, re.IGNORECASE))
        has_keyword = any(kw in clean.lower() for kw in FOOD_KEYWORDS[:20])
        
        if has_weight or has_keyword:
            seen.add(clean.lower())
            names.append(clean)
    
    return names[:100]  # Limit


def extract_harmonica_products(markdown, html):
    """
    Извлича специфични Harmonica продукти с цени.
    """
    products = []
    combined = markdown + "\n" + html
    
    # Pattern 1: Име с Harmonica, последвано от цена
    patterns = [
        # "Продукт harmonica 500ml ... 2.90 лв"
        r'([^\n]{5,60}[Hh]armonica[^\n]{5,40}?)\s+(\d+[.,]\d{2})\s*(?:лв|€|EUR|BGN)',
        # "2.90 лв ... Продукт harmonica"
        r'(\d+[.,]\d{2})\s*(?:лв|€)[^\n]{0,20}([^\n]{5,60}[Hh]armonica[^\n]{0,30})',
        # Био продукт с цена
        r'([Бб]ио\s+[^\n]{5,50}?)\s+(\d+[.,]\d{2})\s*(?:лв|€|EUR|BGN)',
    ]
    
    seen = set()
    for pattern in patterns:
        matches = re.findall(pattern, combined, re.IGNORECASE)
        for match in matches:
            if len(match) >= 2:
                # Определяме кое е името и кое е цената
                if re.match(r'\d+[.,]\d{2}', str(match[0])):
                    price_str, name = match[0], match[1]
                else:
                    name, price_str = match[0], match[1]
                
                name = name.strip()[:80]
                
                # Пропускаме ако вече сме видели
                if name.lower() in seen:
                    continue
                seen.add(name.lower())
                
                try:
                    price = float(str(price_str).replace(",", "."))
                    if 0.20 <= price <= 100:
                        products.append({
                            "name": name,
                            "price_bgn": price if price > 1 else None,
                            "price_eur": price if price <= 50 else None,
                        })
                except:
                    pass
    
    return products[:100]


# =============================================================================
# CRAWLING FUNCTIONS
# =============================================================================

async def crawl_store(crawler, store_key, store_config):
    """
    Сканира един магазин.
    """
    store_name = store_config["name"]
    url = store_config["url"]
    needs_scroll = store_config.get("needs_scroll", False)
    
    print(f"\n{'=' * 60}")
    print(f"CRAWLING: {store_name}")
    print(f"URL: {url}")
    print("=" * 60)
    
    # JavaScript за скролиране (ако е нужно)
    js_scroll = """
    async function scrollPage() {
        for (let i = 0; i < 5; i++) {
            window.scrollTo(0, document.body.scrollHeight);
            await new Promise(r => setTimeout(r, 1000));
        }
        window.scrollTo(0, 0);
    }
    await scrollPage();
    """ if needs_scroll else None
    
    crawler_config = CrawlerRunConfig(
        page_timeout=60000,
        remove_overlay_elements=True,
        excluded_tags=["nav", "footer", "aside", "header"],
        js_code=js_scroll,
    )
    
    start_time = time.time()
    
    try:
        result = await crawler.arun(
            url=url,
            config=crawler_config,
        )
        
        elapsed_time = time.time() - start_time
        
        if result.success:
            print(f"SUCCESS: Loaded in {elapsed_time:.2f}s")
            print(f"HTML: {len(result.html)} chars, Markdown: {len(result.markdown)} chars")
            
            # Извличаме продукти
            products = extract_products_advanced(result.markdown, result.html, store_key)
            
            return {
                "success": True,
                "store": store_name,
                "store_key": store_key,
                "url": url,
                "products": products,
                "elapsed_time": elapsed_time,
            }
        else:
            print(f"ERROR: {result.error_message}")
            return {"success": False, "store": store_name, "error": result.error_message}
            
    except Exception as e:
        print(f"EXCEPTION: {str(e)}")
        return {"success": False, "store": store_name, "error": str(e)}


async def crawl_all_stores():
    """
    Сканира всички магазини.
    """
    results = {}
    
    browser_config = BrowserConfig(
        headless=True,
        viewport_width=1920,
        viewport_height=1080,
    )
    
    async with AsyncWebCrawler(config=browser_config) as crawler:
        for store_key, store_config in STORES.items():
            result = await crawl_store(crawler, store_key, store_config)
            results[store_key] = result
            await asyncio.sleep(2)  # Пауза между магазините
    
    return results


# =============================================================================
# COMPARISON
# =============================================================================

def compare_stores(results):
    """
    Сравнява цените между магазините.
    """
    print(f"\n{'=' * 60}")
    print("STORE COMPARISON")
    print("=" * 60)
    
    store_data = {}
    
    for store_key, result in results.items():
        if result and result.get("success"):
            products = result.get("products", {})
            prices = products.get("prices", {})
            stats = products.get("stats", {})
            
            store_data[store_key] = {
                "name": result["store"],
                "eur_prices": prices.get("eur", []),
                "bgn_prices": prices.get("bgn", []),
                "food_products": stats.get("food_count", 0),
                "harmonica_products": products.get("harmonica_products", []),
            }
    
    # Статистика
    print("\n--- Store Statistics ---")
    for store_key, data in store_data.items():
        print(f"\n{data['name']}:")
        print(f"  EUR prices: {len(data['eur_prices'])}")
        print(f"  BGN prices: {len(data['bgn_prices'])}")
        print(f"  Food products: {data['food_products']}")
        print(f"  Harmonica products: {len(data['harmonica_products'])}")
        
        if data['eur_prices']:
            print(f"  EUR range: {min(data['eur_prices']):.2f} - {max(data['eur_prices']):.2f}")
        if data['bgn_prices']:
            print(f"  BGN range: {min(data['bgn_prices']):.2f} - {max(data['bgn_prices']):.2f}")
    
    # Сравнение на EUR цени между магазините
    comparison = {}
    if "kashon" in store_data:
        kashon_eur = set(store_data["kashon"]["eur_prices"])
        kashon_bgn = set(store_data["kashon"]["bgn_prices"])
        
        print(f"\n--- Price Comparison (vs Kashon) ---")
        for store_key in ["balev", "ebag"]:
            if store_key in store_data:
                other_eur = set(store_data[store_key]["eur_prices"])
                other_bgn = set(store_data[store_key]["bgn_prices"])
                
                # EUR matches
                eur_matches = sum(1 for kp in kashon_eur 
                                  for op in other_eur 
                                  if abs(kp - op) / kp < 0.05)
                
                # BGN matches
                bgn_matches = sum(1 for kp in kashon_bgn 
                                  for op in other_bgn 
                                  if abs(kp - op) / kp < 0.05)
                
                print(f"\n{store_data[store_key]['name']}:")
                print(f"  EUR price matches: {eur_matches}")
                print(f"  BGN price matches: {bgn_matches}")
                
                comparison[store_key] = {
                    "eur_matches": eur_matches,
                    "bgn_matches": bgn_matches,
                }
    
    return comparison


async def main():
    """
    Main function.
    """
    print("\n" + "=" * 60)
    print("EXP-001: CRAWL4AI MULTI-STORE TEST v4")
    print("=" * 60)
    print(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Stores: {len(STORES)}")
    print("Features: Dual EUR/BGN prices, Food-only filter, eBag added")
    
    total_start = time.time()
    
    # Crawl
    results = await crawl_all_stores()
    
    # Compare
    comparison = compare_stores(results)
    
    total_elapsed = time.time() - total_start
    
    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print("=" * 60)
    print(f"Total time: {total_elapsed:.2f} seconds")
    
    successful = sum(1 for r in results.values() if r and r.get("success"))
    print(f"Successful: {successful}/{len(STORES)}")
    
    for store_key, result in results.items():
        if result and result.get("success"):
            stats = result.get("products", {}).get("stats", {})
            print(f"  {result['store']}:")
            print(f"    Time: {result['elapsed_time']:.2f}s")
            print(f"    EUR: {stats.get('eur_count', 0)}, BGN: {stats.get('bgn_count', 0)}")
            print(f"    Food products: {stats.get('food_count', 0)}")
        else:
            print(f"  {STORES[store_key]['name']}: FAILED")
    
    # Save
    output = {
        "experiment": "EXP-001-v4",
        "date": time.strftime('%Y-%m-%d %H:%M:%S'),
        "version": "4.0",
        "features": ["dual_currency", "food_filter", "ebag_added"],
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
        print(f"\nCould not save: {e}")
    
    print(f"\n{'=' * 60}")
    print("END OF TEST v4")
    print("=" * 60)
    
    return output


if __name__ == "__main__":
    asyncio.run(main())
