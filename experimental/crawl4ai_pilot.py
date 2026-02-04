"""
EXP-001: Crawl4AI Dynamic Product Tracker v6
=============================================
Динамично извличане на продукти от Кашон Harmonica.

Архитектура:
1. Сканираме Кашон и извличаме ВСИЧКИ хранителни продукти Harmonica
2. Това става референтният списък с официални цени
3. Сканираме eBag и Balev, търсейки същите продукти
4. Сравняваме цените между магазините

Предимства:
- Няма hardcoded списък с продукти
- Нови продукти се добавят автоматично
- Референтните цени винаги са актуални
- EUR е водещата валута (от юни 2026)
"""

import asyncio
import time
import json
import os
import re
from datetime import datetime

try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    CRAWL4AI_AVAILABLE = True
except ImportError:
    CRAWL4AI_AVAILABLE = False
    print("ERROR: Crawl4AI not installed. Run: pip install crawl4ai")


# =============================================================================
# КОНФИГУРАЦИЯ НА МАГАЗИНИТЕ
# =============================================================================

STORES = {
    "kashon": {
        "name": "Кашон Harmonica (Official)",
        "url": "https://kashonharmonica.bg/bg/products",
        "scroll_times": 10,
        "is_reference": True,  # Източник на истина
    },
    "ebag": {
        "name": "eBag",
        "url": "https://www.ebag.bg/search/?products%5BrefinementList%5D%5Bbrand_name_bg%5D%5B0%5D=%D0%A5%D0%B0%D1%80%D0%BC%D0%BE%D0%BD%D0%B8%D0%BA%D0%B0",
        "scroll_times": 12,
        "is_reference": False,
    },
    "balev": {
        "name": "Balev Bio Market",
        "url": "https://balevbiomarket.com/productBrands/harmonica",
        "scroll_times": 8,
        "is_reference": False,
    },
}


# =============================================================================
# КЛЮЧОВИ ДУМИ ЗА ХРАНИТЕЛНИ ПРОДУКТИ
# Използваме ги за филтриране - само храни, без потници и козметика
# =============================================================================

FOOD_INDICATORS = [
    # Млечни продукти
    "мляко", "айран", "кефир", "сирене", "кашкавал", "масло", "сметана",
    "извара", "йогурт", "крема",
    # Напитки
    "сок", "лимонада", "нектар", "напитка", "сироп",
    # Сладки и снаксове
    "локум", "бисквит", "вафла", "шоколад", "бонбон", "десерт",
    "сладко", "мармалад", "халва",
    # Солени снаксове
    "претцел", "солет", "крекер", "соленки", "чипс",
    "лешник", "бадем", "орех", "фъстък", "ядки",
    # Консерви и сосове
    "домат", "кетчуп", "лютеница", "пюре", "паста", "passata",
    # Други храни
    "хляб", "кори", "тесто", "брашно",
    "олио", "оцет", "зехтин", "мед",
    # Грамаж/обем индикатори (ако има грамаж, вероятно е храна)
    "г", "мл", "ml", "kg", "кг", "л", "l",
]

# Думи, които показват НЕ-храна
NON_FOOD_INDICATORS = [
    "потник", "тениска", "блуза", "панталон", "дреха", "шапка", "чорап",
    "чанта", "раница", "торба",
    "козметика", "крем", "шампоан", "сапун", "гел", "лосион",
    "почиств", "препарат",
    "играчка", "книга",
]


# =============================================================================
# ФУНКЦИИ ЗА ИЗВЛИЧАНЕ НА ЦЕНИ
# =============================================================================

def extract_eur_price(text):
    """Извлича EUR цена от текст."""
    patterns = [
        r'(\d+[.,]\d{2})\s*(?:€|EUR|eur|евро)',
        r'(?:€|EUR)\s*(\d+[.,]\d{2})',
        r'(\d+[.,]\d{2})\s*€',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                price = float(match.group(1).replace(",", "."))
                if 0.20 <= price <= 100:  # Разумен диапазон за EUR
                    return round(price, 2)
            except:
                pass
    return None


def extract_bgn_price(text):
    """Извлича BGN цена от текст."""
    patterns = [
        r'(\d+[.,]\d{2})\s*(?:лв\.?|лева|BGN|bgn)',
        r'(?:BGN|лв\.?)\s*(\d+[.,]\d{2})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                price = float(match.group(1).replace(",", "."))
                if 0.50 <= price <= 200:  # Разумен диапазон за BGN
                    return round(price, 2)
            except:
                pass
    return None


def is_food_product(name):
    """
    Проверява дали продукт е хранителен.
    Връща True ако е храна, False ако не е.
    """
    name_lower = name.lower()
    
    # Първо проверяваме за не-хранителни индикатори
    for indicator in NON_FOOD_INDICATORS:
        if indicator in name_lower:
            return False
    
    # После проверяваме за хранителни индикатори
    for indicator in FOOD_INDICATORS:
        if indicator in name_lower:
            return True
    
    # Ако има числа с г/мл/л, вероятно е храна
    if re.search(r'\d+\s*(?:г|мл|ml|g|kg|кг|л|l)\b', name_lower):
        return True
    
    # По подразбиране приемаме за храна (по-добре да включим повече)
    return True


def is_harmonica_product(name):
    """
    Проверява дали продукт е на марка Harmonica/Хармоника.
    """
    name_lower = name.lower()
    return "harmonica" in name_lower or "хармоника" in name_lower


# =============================================================================
# ИЗВЛИЧАНЕ НА ПРОДУКТИ ОТ КАШОН (РЕФЕРЕНТЕН ИЗТОЧНИК)
# =============================================================================

def extract_kashon_products(markdown, html):
    """
    Извлича всички хранителни продукти Harmonica от Кашон.
    Това е референтният списък.
    
    Търсим patterns като:
    - "Продукт Harmonica 500мл ... 2.90 лв"
    - Markdown линкове с имена на продукти
    """
    products = []
    seen_names = set()
    
    combined_text = markdown + "\n" + html
    
    # Pattern 1: Търсим продукти с цени в markdown
    # Типичен формат: "Име на продукт\n2.90 лв" или "Име ... 2.90 лв"
    product_patterns = [
        # Име с грамаж, последвано от цена
        r'([^\n\[\]]{5,80}?\d+\s*(?:г|мл|ml|g|kg|л|l)[^\n\[\]]{0,30}?)\s*(\d+[.,]\d{2})\s*(?:лв|€|EUR|BGN)',
        
        # Цена, последвана от име с грамаж  
        r'(\d+[.,]\d{2})\s*(?:лв|€)[^\n]{0,30}?([^\n]{5,60}?\d+\s*(?:г|мл|ml|g|kg|л|l)[^\n]{0,20})',
        
        # Markdown линк с цена наблизо
        r'\[([^\]]{5,80})\]\([^\)]+\)[^\n]{0,50}?(\d+[.,]\d{2})\s*(?:лв|€)',
    ]
    
    for pattern in product_patterns:
        matches = re.findall(pattern, combined_text, re.IGNORECASE)
        
        for match in matches:
            # Определяме кое е името и кое е цената
            if re.match(r'^\d+[.,]\d{2}$', str(match[0]).strip()):
                price_str, name = match[0], match[1]
            else:
                name, price_str = match[0], match[1]
            
            # Почистваме името
            name = clean_product_name(name)
            
            if not name or len(name) < 5:
                continue
            
            # Проверяваме дали е уникален
            name_key = name.lower()[:40]
            if name_key in seen_names:
                continue
            
            # Проверяваме дали е храна
            if not is_food_product(name):
                continue
            
            # Извличаме цените
            try:
                price = float(str(price_str).replace(",", "."))
            except:
                continue
            
            # Определяме дали е EUR или BGN
            context_start = combined_text.lower().find(name.lower()[:20])
            if context_start >= 0:
                context = combined_text[max(0, context_start-50):context_start+150]
            else:
                context = ""
            
            eur_price = extract_eur_price(context) or (price if price < 50 else None)
            bgn_price = extract_bgn_price(context) or (price if price >= 0.5 else None)
            
            # Ако цената е под 15 и няма валутен знак, проверяваме диапазона
            if eur_price is None and bgn_price is None:
                if price < 15:
                    eur_price = price  # Вероятно EUR
                else:
                    bgn_price = price  # Вероятно BGN
            
            seen_names.add(name_key)
            products.append({
                "name": name,
                "eur": eur_price,
                "bgn": bgn_price,
                "source": "kashon",
            })
    
    return products


def clean_product_name(name):
    """Почиства име на продукт."""
    if not name:
        return ""
    
    # Премахваме излишни символи
    name = re.sub(r'\s+', ' ', name)  # Множество интервали -> един
    name = name.strip()
    name = re.sub(r'^[\-\*\•\>\|\s]+', '', name)  # Водещи символи
    name = re.sub(r'[\-\*\•\>\|\s]+$', '', name)  # Крайни символи
    
    # Ограничаваме дължината
    if len(name) > 80:
        name = name[:80]
    
    return name


# =============================================================================
# ТЪРСЕНЕ НА ПРОДУКТИ В ДРУГИ МАГАЗИНИ
# =============================================================================

def find_product_in_store(product_name, store_markdown):
    """
    Търси продукт от референтния списък в текста на друг магазин.
    Връща намерените цени или None.
    """
    text_lower = store_markdown.lower()
    product_lower = product_name.lower()
    
    # Извличаме ключови думи от името на продукта
    keywords = extract_keywords(product_name)
    
    # Търсим по ключови думи
    best_match = None
    best_score = 0
    
    # Разделяме текста на "блокове" около цени
    price_blocks = re.split(r'(?=\d+[.,]\d{2}\s*(?:лв|€|EUR|BGN))', store_markdown)
    
    for block in price_blocks:
        if len(block) < 10:
            continue
        
        block_lower = block.lower()
        
        # Броим колко keywords съвпадат
        score = sum(1 for kw in keywords if kw in block_lower)
        
        # Бонус ако има "harmonica" или "хармоника"
        if "harmonica" in block_lower or "хармоника" in block_lower:
            score += 2
        
        if score > best_score and score >= 2:  # Минимум 2 съвпадения
            best_score = score
            best_match = block
    
    if best_match:
        eur = extract_eur_price(best_match)
        bgn = extract_bgn_price(best_match)
        
        if eur or bgn:
            return {"eur": eur, "bgn": bgn, "score": best_score}
    
    return None


def extract_keywords(product_name):
    """
    Извлича ключови думи от име на продукт.
    Пример: "Био кисело мляко 3.6% 400г" -> ["био", "кисело", "мляко", "3.6", "400"]
    """
    # Премахваме "harmonica" и "хармоника" - те са общи за всички
    name = product_name.lower()
    name = name.replace("harmonica", "").replace("хармоника", "")
    
    # Извличаме думи и числа
    words = re.findall(r'[а-яa-z]{3,}|\d+(?:[.,]\d+)?', name)
    
    # Филтрираме твърде общи думи
    stopwords = {"био", "organic", "the", "and", "with", "без", "от", "за"}
    keywords = [w for w in words if w not in stopwords and len(w) >= 2]
    
    return keywords


# =============================================================================
# CRAWLING ФУНКЦИИ
# =============================================================================

async def crawl_store(crawler, store_key, store_config):
    """Сканира един магазин."""
    
    store_name = store_config["name"]
    url = store_config["url"]
    scroll_times = store_config.get("scroll_times", 5)
    
    print(f"\n{'='*60}")
    print(f"CRAWLING: {store_name}")
    print(f"URL: {url[:70]}...")
    print(f"Scroll: {scroll_times}x")
    print("="*60)
    
    # JavaScript за скролиране (зарежда lazy-loaded съдържание)
    scroll_js = f"""
    async function scrollPage() {{
        for (let i = 0; i < {scroll_times}; i++) {{
            window.scrollTo(0, document.body.scrollHeight);
            await new Promise(r => setTimeout(r, 1500));
        }}
        window.scrollTo(0, 0);
    }}
    await scrollPage();
    """
    
    crawler_config = CrawlerRunConfig(
        page_timeout=90000,
        remove_overlay_elements=True,
        js_code=scroll_js,
    )
    
    start_time = time.time()
    
    try:
        result = await crawler.arun(url=url, config=crawler_config)
        elapsed = time.time() - start_time
        
        if not result.success:
            print(f"FAILED: {result.error_message}")
            return {
                "success": False,
                "store": store_name,
                "store_key": store_key,
                "error": result.error_message,
            }
        
        print(f"SUCCESS: {elapsed:.2f}s")
        print(f"  Markdown: {len(result.markdown)} chars")
        print(f"  HTML: {len(result.html)} chars")
        
        return {
            "success": True,
            "store": store_name,
            "store_key": store_key,
            "elapsed_time": elapsed,
            "markdown": result.markdown,
            "html": result.html,
            "is_reference": store_config.get("is_reference", False),
        }
        
    except Exception as e:
        print(f"EXCEPTION: {str(e)}")
        return {
            "success": False,
            "store": store_name,
            "store_key": store_key,
            "error": str(e),
        }


async def crawl_all_stores():
    """Сканира всички магазини."""
    
    browser_config = BrowserConfig(
        headless=True,
        viewport_width=1920,
        viewport_height=1080,
    )
    
    results = {}
    
    async with AsyncWebCrawler(config=browser_config) as crawler:
        # Първо сканираме Кашон (референтен)
        kashon_result = await crawl_store(crawler, "kashon", STORES["kashon"])
        results["kashon"] = kashon_result
        
        await asyncio.sleep(3)
        
        # После останалите магазини
        for store_key, store_config in STORES.items():
            if store_key == "kashon":
                continue
            
            result = await crawl_store(crawler, store_key, store_config)
            results[store_key] = result
            await asyncio.sleep(3)
    
    return results


# =============================================================================
# ОБРАБОТКА И СРАВНЕНИЕ
# =============================================================================

def process_results(crawl_results):
    """
    Обработва резултатите от сканирането.
    1. Извлича референтен списък от Кашон
    2. Търси продуктите в другите магазини
    3. Сравнява цените
    """
    
    print(f"\n{'='*60}")
    print("PROCESSING RESULTS")
    print("="*60)
    
    # Стъпка 1: Извличаме референтен списък от Кашон
    kashon_data = crawl_results.get("kashon", {})
    
    if not kashon_data.get("success"):
        print("ERROR: Кашон не е зареден успешно!")
        return {"error": "Kashon failed", "products": []}
    
    print("\n--- STEP 1: Extract reference products from Kashon ---")
    
    reference_products = extract_kashon_products(
        kashon_data.get("markdown", ""),
        kashon_data.get("html", "")
    )
    
    # Филтрираме само Harmonica продукти
    harmonica_products = [p for p in reference_products 
                          if is_harmonica_product(p["name"]) or is_food_product(p["name"])]
    
    print(f"Total products extracted: {len(reference_products)}")
    print(f"Harmonica food products: {len(harmonica_products)}")
    
    if harmonica_products:
        print("\nSample products from Kashon:")
        for p in harmonica_products[:10]:
            eur_str = f"{p['eur']:.2f}€" if p['eur'] else "N/A"
            bgn_str = f"{p['bgn']:.2f}лв" if p['bgn'] else "N/A"
            print(f"  - {p['name'][:50]}: {eur_str} / {bgn_str}")
    
    # Стъпка 2: Търсим продуктите в другите магазини
    print("\n--- STEP 2: Find products in other stores ---")
    
    for product in harmonica_products:
        product["stores"] = {"kashon": {"eur": product["eur"], "bgn": product["bgn"]}}
        
        for store_key, store_data in crawl_results.items():
            if store_key == "kashon":
                continue
            
            if not store_data.get("success"):
                continue
            
            match = find_product_in_store(
                product["name"],
                store_data.get("markdown", "")
            )
            
            if match:
                product["stores"][store_key] = {
                    "eur": match["eur"],
                    "bgn": match["bgn"],
                }
    
    # Стъпка 3: Статистика
    print("\n--- STEP 3: Statistics ---")
    
    for store_key in STORES.keys():
        count = sum(1 for p in harmonica_products if store_key in p.get("stores", {}))
        store_name = STORES[store_key]["name"]
        print(f"  {store_name}: {count}/{len(harmonica_products)} products")
    
    return {
        "reference_count": len(harmonica_products),
        "products": harmonica_products,
    }


# =============================================================================
# MAIN
# =============================================================================

async def main():
    """Main function."""
    
    print("\n" + "="*60)
    print("EXP-001: CRAWL4AI DYNAMIC TRACKER v6")
    print("="*60)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Stores: {len(STORES)}")
    print("Mode: Dynamic product list from Kashon Harmonica")
    print("Currency: EUR (primary) + BGN")
    
    if not CRAWL4AI_AVAILABLE:
        print("\nERROR: Crawl4AI not available!")
        return
    
    total_start = time.time()
    
    # Сканираме всички магазини
    print("\n" + "="*60)
    print("PHASE 1: CRAWLING STORES")
    print("="*60)
    
    crawl_results = await crawl_all_stores()
    
    # Обработваме резултатите
    print("\n" + "="*60)
    print("PHASE 2: PROCESSING")
    print("="*60)
    
    processed = process_results(crawl_results)
    
    total_time = time.time() - total_start
    
    # Финално обобщение
    print(f"\n{'='*60}")
    print("FINAL SUMMARY")
    print("="*60)
    print(f"Total execution time: {total_time:.2f}s")
    print(f"Reference products (Kashon): {processed.get('reference_count', 0)}")
    
    # Показваме покритие по магазини
    products = processed.get("products", [])
    
    if products:
        print("\nStore coverage:")
        for store_key, store_config in STORES.items():
            count = sum(1 for p in products if store_key in p.get("stores", {}))
            pct = (count / len(products) * 100) if products else 0
            print(f"  {store_config['name']}: {count}/{len(products)} ({pct:.0f}%)")
        
        # Показваме примерни продукти с цени от всички магазини
        print("\nSample products with prices across stores:")
        for p in products[:5]:
            print(f"\n  {p['name'][:50]}:")
            for store_key, prices in p.get("stores", {}).items():
                store_name = STORES[store_key]["name"]
                eur = f"{prices['eur']:.2f}€" if prices.get('eur') else "N/A"
                bgn = f"{prices['bgn']:.2f}лв" if prices.get('bgn') else "N/A"
                print(f"    {store_name}: {eur} / {bgn}")
    
    # Записваме резултатите
    output = {
        "experiment": "EXP-001-v6-dynamic",
        "date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "total_time": total_time,
        "reference_source": "kashon",
        "reference_count": processed.get("reference_count", 0),
        "products": products,
        "crawl_stats": {
            store_key: {
                "success": data.get("success"),
                "elapsed": data.get("elapsed_time"),
                "error": data.get("error"),
            }
            for store_key, data in crawl_results.items()
        },
    }
    
    try:
        os.makedirs("experimental", exist_ok=True)
        with open("experimental/pilot_results.json", "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2, default=str)
        print(f"\nResults saved to: experimental/pilot_results.json")
    except Exception as e:
        print(f"\nCould not save results: {e}")
    
    print(f"\n{'='*60}")
    print("END OF EXPERIMENT")
    print("="*60)
    
    return output


if __name__ == "__main__":
    asyncio.run(main())
