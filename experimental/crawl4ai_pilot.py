"""
EXP-001: Crawl4AI Dynamic Tracker v6.2 DEBUG
=============================================
DEBUG версия - записва markdown samples за анализ.
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
    print("ERROR: Crawl4AI not installed")


# =============================================================================
# STORE CONFIGURATION
# =============================================================================

STORES = {
    "kashon": {
        "name": "Кашон Harmonica (Official)",
        "url": "https://kashonharmonica.bg/bg/products",
        "scroll_times": 10,
        "is_reference": True,
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
# FOOD FILTERING
# =============================================================================

FOOD_KEYWORDS = [
    "мляко", "айран", "кефир", "сирене", "кашкавал", "масло", "сметана",
    "извара", "йогурт", "крема", "сок", "лимонада", "нектар", "сироп",
    "локум", "бисквит", "вафла", "шоколад", "бонбон", "сладко", "халва",
    "претцел", "солет", "крекер", "соленки", "лешник", "бадем", "орех",
    "домат", "кетчуп", "лютеница", "пюре", "паста", "хляб", "кори",
    "олио", "оцет", "зехтин", "мед", "чай", "smiles", "топчета",
]

NON_FOOD_KEYWORDS = [
    "потник", "тениска", "блуза", "дреха", "шапка", "чанта", "раница",
    "козметика", "крем", "шампоан", "сапун", "гел", "лосион",
]


def is_food_product(name):
    """Проверява дали е хранителен продукт."""
    name_lower = name.lower()
    
    for kw in NON_FOOD_KEYWORDS:
        if kw in name_lower:
            return False
    
    for kw in FOOD_KEYWORDS:
        if kw in name_lower:
            return True
    
    if re.search(r'\d+\s*(?:г|мл|ml|g|kg|л)\b', name_lower):
        return True
    
    return True


# =============================================================================
# PRICE EXTRACTION
# =============================================================================

def extract_eur_price(text):
    """Извлича EUR цена."""
    patterns = [
        r'(\d+[.,]\d{2})\s*(?:€|EUR|eur|евро)',
        r'(?:€|EUR)\s*(\d+[.,]\d{2})',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                price = float(match.group(1).replace(",", "."))
                if 0.20 <= price <= 100:
                    return round(price, 2)
            except:
                pass
    return None


def extract_bgn_price(text):
    """Извлича BGN цена."""
    patterns = [
        r'(\d+[.,]\d{2})\s*(?:лв\.?|лева|BGN)',
        r'(?:BGN|лв\.?)\s*(\d+[.,]\d{2})',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                price = float(match.group(1).replace(",", "."))
                if 0.50 <= price <= 200:
                    return round(price, 2)
            except:
                pass
    return None


# =============================================================================
# DEBUG: ANALYZE MARKDOWN STRUCTURE
# =============================================================================

def analyze_markdown_structure(markdown, store_name):
    """
    DEBUG: Анализира структурата на markdown-а.
    Показва примерни редове и patterns.
    """
    print(f"\n{'='*60}")
    print(f"DEBUG: Analyzing {store_name} markdown structure")
    print(f"{'='*60}")
    print(f"Total length: {len(markdown)} chars")
    
    lines = markdown.split('\n')
    print(f"Total lines: {len(lines)}")
    
    # Показваме първите 50 непразни реда
    print(f"\n--- First 50 non-empty lines ---")
    count = 0
    for line in lines:
        line = line.strip()
        if line and len(line) > 3:
            print(f"  {count+1}: {line[:100]}")
            count += 1
            if count >= 50:
                break
    
    # Търсим линкове
    links = re.findall(r'\[([^\]]+)\]\(([^\)]+)\)', markdown)
    print(f"\n--- Found {len(links)} markdown links ---")
    for text, url in links[:20]:
        print(f"  [{text[:50]}]({url[:50]})")
    
    # Търсим цени
    prices_bgn = re.findall(r'(\d+[.,]\d{2})\s*лв', markdown)
    prices_eur = re.findall(r'(\d+[.,]\d{2})\s*€', markdown)
    print(f"\n--- Found {len(prices_bgn)} BGN prices, {len(prices_eur)} EUR prices ---")
    print(f"BGN sample: {prices_bgn[:10]}")
    print(f"EUR sample: {prices_eur[:10]}")
    
    # Търсим продуктови имена (с грамаж)
    products_with_weight = re.findall(r'([^\n\[\]]{5,60}?\d+\s*(?:г|мл|ml|g)\b[^\n\[\]]{0,20})', markdown)
    print(f"\n--- Found {len(products_with_weight)} potential product names (with weight) ---")
    for p in products_with_weight[:15]:
        print(f"  {p.strip()[:70]}")
    
    # Търсим Harmonica/Хармоника mentions
    harmonica_context = []
    for match in re.finditer(r'.{0,50}(?:harmonica|хармоника).{0,50}', markdown, re.IGNORECASE):
        harmonica_context.append(match.group().strip())
    print(f"\n--- Found {len(harmonica_context)} Harmonica mentions ---")
    for ctx in harmonica_context[:10]:
        print(f"  {ctx[:80]}")
    
    return {
        "lines": len(lines),
        "links": len(links),
        "prices_bgn": len(prices_bgn),
        "prices_eur": len(prices_eur),
        "products_with_weight": len(products_with_weight),
    }


# =============================================================================
# PRODUCT EXTRACTION (IMPROVED)
# =============================================================================

def extract_products_from_kashon(markdown, html):
    """
    Извлича продукти от Кашон.
    Използва множество стратегии.
    """
    products = []
    seen = set()
    
    # Стратегия 1: Markdown линкове с текст
    print("\n  Strategy 1: Markdown links...")
    link_pattern = r'\[([^\]]{5,80})\]\(https://kashonharmonica\.bg[^\)]+\)'
    for match in re.finditer(link_pattern, markdown):
        name = match.group(1).strip()
        
        # Пропускаме ако е URL или изображение
        if name.startswith('http') or name.startswith('!') or 'logo' in name.lower():
            continue
        
        # Пропускаме ако няма букви
        if len(re.findall(r'[а-яА-Яa-zA-Z]', name)) < 3:
            continue
        
        name_key = name.lower()[:25]
        if name_key in seen:
            continue
        
        if not is_food_product(name):
            continue
        
        # Търсим цена около линка
        idx = markdown.find(match.group(0))
        context = markdown[max(0,idx-100):idx+200]
        eur = extract_eur_price(context)
        bgn = extract_bgn_price(context)
        
        if eur or bgn:
            seen.add(name_key)
            products.append({"name": name, "eur": eur, "bgn": bgn, "method": "link"})
    
    print(f"    Found {len(products)} from links")
    
    # Стратегия 2: Редове с грамаж
    print("\n  Strategy 2: Lines with weight...")
    lines = markdown.split('\n')
    
    for i, line in enumerate(lines):
        line = line.strip()
        
        # Търсим ред с грамаж
        weight_match = re.search(r'\d+\s*(?:г|мл|ml|g|kg|л)\b', line, re.IGNORECASE)
        if not weight_match:
            continue
        
        # Почистваме реда
        name = line
        name = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', name)  # [text](url) -> text
        name = re.sub(r'https?://[^\s]+', '', name)  # Remove URLs
        name = re.sub(r'\d+[.,]\d{2}\s*(?:лв|€|EUR|BGN)\.?', '', name)  # Remove prices
        name = re.sub(r'^[\-\*\•\>\|\s/]+', '', name)  # Leading chars
        name = re.sub(r'[\-\*\•\>\|\s/]+$', '', name)  # Trailing chars
        name = re.sub(r'\s+', ' ', name).strip()
        
        if len(name) < 5 or len(name) > 80:
            continue
        
        if len(re.findall(r'[а-яА-Яa-zA-Z]', name)) < 3:
            continue
        
        name_key = name.lower()[:25]
        if name_key in seen:
            continue
        
        if not is_food_product(name):
            continue
        
        # Търсим цена в контекста
        context = '\n'.join(lines[max(0,i-2):i+5])
        eur = extract_eur_price(context)
        bgn = extract_bgn_price(context)
        
        if eur or bgn:
            seen.add(name_key)
            products.append({"name": name, "eur": eur, "bgn": bgn, "method": "weight_line"})
    
    print(f"    Found {len([p for p in products if p['method']=='weight_line'])} from weight lines")
    
    # Стратегия 3: HTML product titles
    print("\n  Strategy 3: HTML titles...")
    html_patterns = [
        r'title="([^"]{10,80})"',
        r'alt="([^"]{10,80})"',
        r'>([^<]{10,60}(?:г|мл|ml|g)\b[^<]{0,20})<',
    ]
    
    for pattern in html_patterns:
        for match in re.finditer(pattern, html):
            name = match.group(1).strip()
            
            if 'http' in name.lower() or 'logo' in name.lower():
                continue
            
            if len(re.findall(r'[а-яА-Яa-zA-Z]', name)) < 3:
                continue
            
            name_key = name.lower()[:25]
            if name_key in seen:
                continue
            
            if not is_food_product(name):
                continue
            
            idx = html.find(name)
            context = html[max(0,idx-200):idx+300]
            eur = extract_eur_price(context)
            bgn = extract_bgn_price(context)
            
            if eur or bgn:
                seen.add(name_key)
                products.append({"name": name, "eur": eur, "bgn": bgn, "method": "html"})
    
    print(f"    Found {len([p for p in products if p['method']=='html'])} from HTML")
    
    return products


def extract_products_from_store(markdown, html, store_name):
    """Извлича продукти от eBag или Balev."""
    products = []
    seen = set()
    
    combined = markdown + "\n" + html[:100000]
    
    # Търсим продукти с грамаж и цена
    # Pattern: име с грамаж ... цена
    patterns = [
        r'([^\n<>]{5,60}?\d+\s*(?:г|мл|ml|g)\b[^\n<>]{0,20})[^\d]{0,50}?(\d+[.,]\d{2})\s*(?:лв|€)',
        r'(\d+[.,]\d{2})\s*(?:лв|€)[^\n<>]{0,30}?([^\n<>]{5,60}?\d+\s*(?:г|мл|ml|g)\b)',
    ]
    
    for pattern in patterns:
        for match in re.finditer(pattern, combined, re.IGNORECASE):
            groups = match.groups()
            
            # Определяме кое е името
            if re.match(r'^\d+[.,]\d{2}$', groups[0].strip()):
                price_str, name = groups
            else:
                name, price_str = groups
            
            # Почистваме
            name = re.sub(r'\s+', ' ', name).strip()
            name = re.sub(r'^[\-\*\•\>\|]+', '', name).strip()
            
            if len(name) < 5 or len(name) > 80:
                continue
            
            name_key = name.lower()[:25]
            if name_key in seen:
                continue
            
            try:
                price = float(price_str.replace(",", "."))
                if not (0.5 <= price <= 100):
                    continue
            except:
                continue
            
            seen.add(name_key)
            
            # Определяме валутата
            context = match.group(0)
            eur = price if '€' in context or 'EUR' in context else None
            bgn = price if 'лв' in context or 'BGN' in context else None
            
            products.append({"name": name, "eur": eur, "bgn": bgn})
    
    return products


# =============================================================================
# MATCHING
# =============================================================================

def match_product_in_store(ref_product, store_products):
    """
    Намира съответствие между референтен продукт и продукти от магазин.
    """
    ref_name = ref_product["name"].lower()
    ref_keywords = set(re.findall(r'[а-я]{3,}|\d+(?:г|мл|ml|g)', ref_name))
    
    best_match = None
    best_score = 0
    
    for prod in store_products:
        prod_name = prod["name"].lower()
        prod_keywords = set(re.findall(r'[а-я]{3,}|\d+(?:г|мл|ml|g)', prod_name))
        
        # Изчисляваме overlap
        common = ref_keywords & prod_keywords
        score = len(common)
        
        if score >= 2 and score > best_score:
            best_score = score
            best_match = prod
    
    return best_match


# =============================================================================
# CRAWLING
# =============================================================================

async def crawl_store(crawler, store_key, store_config):
    """Сканира един магазин."""
    
    store_name = store_config["name"]
    url = store_config["url"]
    scroll_times = store_config.get("scroll_times", 5)
    
    print(f"\n{'='*60}")
    print(f"CRAWLING: {store_name}")
    print(f"URL: {url[:60]}...")
    print("="*60)
    
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
            return {"success": False, "store": store_name, "error": result.error_message}
        
        print(f"SUCCESS: {elapsed:.2f}s, {len(result.markdown)} chars markdown")
        
        return {
            "success": True,
            "store": store_name,
            "store_key": store_key,
            "elapsed_time": elapsed,
            "markdown": result.markdown,
            "html": result.html,
        }
        
    except Exception as e:
        print(f"EXCEPTION: {str(e)}")
        return {"success": False, "store": store_name, "error": str(e)}


async def crawl_all_stores():
    """Сканира всички магазини."""
    
    browser_config = BrowserConfig(headless=True, viewport_width=1920, viewport_height=1080)
    results = {}
    
    async with AsyncWebCrawler(config=browser_config) as crawler:
        for store_key, store_config in STORES.items():
            results[store_key] = await crawl_store(crawler, store_key, store_config)
            await asyncio.sleep(3)
    
    return results


# =============================================================================
# MAIN
# =============================================================================

async def main():
    print("\n" + "="*60)
    print("EXP-001: CRAWL4AI v6.2 DEBUG")
    print("="*60)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if not CRAWL4AI_AVAILABLE:
        print("ERROR: Crawl4AI not available!")
        return
    
    total_start = time.time()
    
    # Crawl всички магазини
    crawl_results = await crawl_all_stores()
    
    # DEBUG: Анализираме структурата
    print("\n" + "="*60)
    print("DEBUG ANALYSIS")
    print("="*60)
    
    debug_info = {}
    for store_key, data in crawl_results.items():
        if data.get("success"):
            debug_info[store_key] = analyze_markdown_structure(
                data["markdown"], 
                STORES[store_key]["name"]
            )
    
    # Извличаме продукти
    print("\n" + "="*60)
    print("PRODUCT EXTRACTION")
    print("="*60)
    
    # От Кашон
    kashon_data = crawl_results.get("kashon", {})
    if kashon_data.get("success"):
        print("\n--- Extracting from Kashon ---")
        kashon_products = extract_products_from_kashon(
            kashon_data["markdown"],
            kashon_data["html"]
        )
        print(f"\nTotal Kashon products: {len(kashon_products)}")
        
        if kashon_products:
            print("\nSample products:")
            for p in kashon_products[:15]:
                eur = f"{p['eur']:.2f}€" if p['eur'] else "N/A"
                bgn = f"{p['bgn']:.2f}лв" if p['bgn'] else "N/A"
                print(f"  [{p['method']}] {p['name'][:45]}: {eur} / {bgn}")
    else:
        kashon_products = []
    
    # От другите магазини
    store_products = {}
    for store_key in ["ebag", "balev"]:
        data = crawl_results.get(store_key, {})
        if data.get("success"):
            print(f"\n--- Extracting from {STORES[store_key]['name']} ---")
            products = extract_products_from_store(
                data["markdown"],
                data["html"],
                store_key
            )
            store_products[store_key] = products
            print(f"Found {len(products)} products")
            
            for p in products[:10]:
                eur = f"{p['eur']:.2f}€" if p['eur'] else "N/A"
                bgn = f"{p['bgn']:.2f}лв" if p['bgn'] else "N/A"
                print(f"  {p['name'][:45]}: {eur} / {bgn}")
    
    # Matching
    print("\n" + "="*60)
    print("MATCHING")
    print("="*60)
    
    for product in kashon_products:
        product["stores"] = {"kashon": {"eur": product["eur"], "bgn": product["bgn"]}}
        
        for store_key, products in store_products.items():
            match = match_product_in_store(product, products)
            if match:
                product["stores"][store_key] = {"eur": match["eur"], "bgn": match["bgn"]}
    
    # Statistics
    print("\nStore coverage:")
    for store_key in STORES.keys():
        count = sum(1 for p in kashon_products if store_key in p.get("stores", {}))
        pct = (count / len(kashon_products) * 100) if kashon_products else 0
        print(f"  {STORES[store_key]['name']}: {count}/{len(kashon_products)} ({pct:.0f}%)")
    
    total_time = time.time() - total_start
    
    # Save results
    output = {
        "experiment": "EXP-001-v6.2-debug",
        "date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "total_time": total_time,
        "debug_info": debug_info,
        "kashon_products": kashon_products,
        "store_products": {k: v[:20] for k, v in store_products.items()},
        "markdown_samples": {
            store_key: data.get("markdown", "")[:3000]
            for store_key, data in crawl_results.items()
            if data.get("success")
        },
    }
    
    try:
        os.makedirs("experimental", exist_ok=True)
        with open("experimental/pilot_results.json", "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2, default=str)
        print(f"\nResults saved to: experimental/pilot_results.json")
    except Exception as e:
        print(f"Save error: {e}")
    
    print(f"\n{'='*60}")
    print(f"DONE in {total_time:.2f}s")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
