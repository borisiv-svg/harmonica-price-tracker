"""
EXP-001: Crawl4AI Dynamic Product Tracker v6.1
==============================================
ПОПРАВКА: Подобрено извличане на имена от Кашон.

Проблем в v6: Извличахме URL фрагменти вместо реални имена.
Решение: Парсваме markdown линкове правилно и почистваме имената.
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
    
    # Ако има грамаж, вероятно е храна
    if re.search(r'\d+\s*(?:г|мл|ml|g|kg|л)\b', name_lower):
        return True
    
    return True  # По подразбиране приемаме


def is_valid_product_name(name):
    """Проверява дали името е валидно (не е URL, не е само цена)."""
    if not name or len(name) < 5:
        return False
    
    # Не е URL
    if name.startswith("http") or name.startswith("://") or name.startswith("(http"):
        return False
    
    # Не е само цена
    if re.match(r'^[\d\s\.,/лвEUR€]+$', name):
        return False
    
    # Не е само символи
    if re.match(r'^[\-\*\•\>\|\s/]+$', name):
        return False
    
    # Има поне 2 букви
    if len(re.findall(r'[а-яА-Яa-zA-Z]', name)) < 2:
        return False
    
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
# KASHON PRODUCT EXTRACTION (ПОДОБРЕНО)
# =============================================================================

def extract_kashon_products(markdown, html):
    """
    Извлича продукти от Кашон с подобрено парсване.
    
    Стратегия:
    1. Търсим markdown линкове: [Име на продукт](URL)
    2. Търсим имена с грамаж близо до цени
    3. Почистваме и валидираме имената
    """
    products = []
    seen = set()
    
    print("\n  [DEBUG] Extracting from Kashon...")
    
    # ===========================================
    # МЕТОД 1: Markdown линкове
    # Формат: [Име на продукт](https://kashonharmonica.bg/...)
    # ===========================================
    
    link_pattern = r'\[([^\]]+)\]\(https://kashonharmonica\.bg/bg/products/([^\)]+)\)'
    links = re.findall(link_pattern, markdown)
    
    print(f"  [DEBUG] Found {len(links)} markdown links")
    
    for name, url_slug in links:
        name = clean_product_name(name)
        
        if not is_valid_product_name(name):
            continue
        
        if not is_food_product(name):
            continue
        
        name_key = name.lower()[:30]
        if name_key in seen:
            continue
        seen.add(name_key)
        
        # Търсим цена в контекста
        idx = markdown.find(name)
        if idx >= 0:
            context = markdown[idx:idx+200]
            eur = extract_eur_price(context)
            bgn = extract_bgn_price(context)
            
            if eur or bgn:
                products.append({
                    "name": name,
                    "eur": eur,
                    "bgn": bgn,
                    "source": "markdown_link",
                })
    
    # ===========================================
    # МЕТОД 2: Имена с грамаж от текста
    # Търсим: "Био кисело мляко 3.6% 400г" близо до цена
    # ===========================================
    
    # Разделяме на редове и търсим продуктови имена
    lines = markdown.split('\n')
    
    for i, line in enumerate(lines):
        line = line.strip()
        
        # Пропускаме кратки редове и URL-и
        if len(line) < 10 or line.startswith('http') or line.startswith('[!'):
            continue
        
        # Търсим ред с грамаж (вероятно е продукт)
        if re.search(r'\d+\s*(?:г|мл|ml|g|kg|л)\b', line, re.IGNORECASE):
            name = clean_product_name(line)
            
            if not is_valid_product_name(name):
                continue
            
            if not is_food_product(name):
                continue
            
            name_key = name.lower()[:30]
            if name_key in seen:
                continue
            
            # Търсим цена в следващите редове
            context = '\n'.join(lines[i:i+5])
            eur = extract_eur_price(context)
            bgn = extract_bgn_price(context)
            
            if eur or bgn:
                seen.add(name_key)
                products.append({
                    "name": name,
                    "eur": eur,
                    "bgn": bgn,
                    "source": "text_line",
                })
    
    # ===========================================
    # МЕТОД 3: HTML data атрибути и структура
    # ===========================================
    
    # Търсим product titles в HTML
    html_title_patterns = [
        r'class="[^"]*product[^"]*title[^"]*"[^>]*>([^<]+)<',
        r'class="[^"]*title[^"]*"[^>]*>([^<]{10,80})<',
        r'<h\d[^>]*>([^<]{10,60}(?:г|мл|ml|g|kg|л)[^<]{0,20})</h\d>',
    ]
    
    for pattern in html_title_patterns:
        matches = re.findall(pattern, html, re.IGNORECASE)
        for name in matches:
            name = clean_product_name(name)
            
            if not is_valid_product_name(name):
                continue
            
            if not is_food_product(name):
                continue
            
            name_key = name.lower()[:30]
            if name_key in seen:
                continue
            
            # Търсим цена в HTML контекст
            idx = html.find(name)
            if idx >= 0:
                context = html[idx:idx+500]
                eur = extract_eur_price(context)
                bgn = extract_bgn_price(context)
                
                if eur or bgn:
                    seen.add(name_key)
                    products.append({
                        "name": name,
                        "eur": eur,
                        "bgn": bgn,
                        "source": "html",
                    })
    
    print(f"  [DEBUG] Total valid products: {len(products)}")
    
    return products


def clean_product_name(name):
    """Почиства име на продукт."""
    if not name:
        return ""
    
    # Премахваме markdown форматиране
    name = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', name)
    
    # Премахваме URL-и
    name = re.sub(r'https?://[^\s]+', '', name)
    
    # Премахваме ценови фрагменти
    name = re.sub(r'\d+[.,]\d{2}\s*(?:лв|€|EUR|BGN)\.?', '', name)
    name = re.sub(r'/\s*\d+[.,]\d{2}\s*лв\.?', '', name)
    
    # Премахваме водещи/крайни символи
    name = re.sub(r'^[\-\*\•\>\|\s/\(\)]+', '', name)
    name = re.sub(r'[\-\*\•\>\|\s/\(\)]+$', '', name)
    
    # Нормализираме интервали
    name = re.sub(r'\s+', ' ', name)
    name = name.strip()
    
    return name[:80] if name else ""


# =============================================================================
# STORE MATCHING (ПОДОБРЕНО)
# =============================================================================

def find_product_in_store(product_name, store_text):
    """
    Търси продукт в текста на магазин.
    Използва fuzzy matching по ключови думи.
    """
    # Извличаме ключови думи от името
    keywords = extract_search_keywords(product_name)
    
    if not keywords:
        return None
    
    text_lower = store_text.lower()
    
    # Търсим блокове с продукти (около цени)
    blocks = re.split(r'\n\s*\n', store_text)
    
    best_match = None
    best_score = 0
    
    for block in blocks:
        if len(block) < 20:
            continue
        
        block_lower = block.lower()
        
        # Броим съвпадащи keywords
        score = 0
        for kw in keywords:
            if kw in block_lower:
                score += 1
                # Бонус за по-дълги keywords
                if len(kw) > 5:
                    score += 0.5
        
        # Изискваме поне 2 съвпадения (или 1 ако е много специфично)
        min_score = 2 if len(keywords) > 2 else 1
        
        if score >= min_score and score > best_score:
            # Проверяваме дали има цена в блока
            if re.search(r'\d+[.,]\d{2}', block):
                best_score = score
                best_match = block
    
    if best_match:
        return {
            "eur": extract_eur_price(best_match),
            "bgn": extract_bgn_price(best_match),
            "score": best_score,
        }
    
    return None


def extract_search_keywords(product_name):
    """
    Извлича ключови думи за търсене.
    """
    name_lower = product_name.lower()
    
    # Премахваме общи думи
    name_lower = name_lower.replace("harmonica", "").replace("хармоника", "")
    name_lower = name_lower.replace("био", "").replace("organic", "")
    
    # Извличаме думи (мин 3 букви) и числа с мерни единици
    words = re.findall(r'[а-я]{3,}|[a-z]{3,}|\d+\s*(?:г|мл|ml|g|kg|л|%)', name_lower)
    
    # Филтрираме стоп думи
    stopwords = {"без", "със", "от", "за", "при", "или", "the", "and", "with"}
    keywords = [w.strip() for w in words if w.strip() not in stopwords]
    
    return keywords


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
    print(f"Scroll: {scroll_times}x")
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
            return {"success": False, "store": store_name, "store_key": store_key, "error": result.error_message}
        
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
        return {"success": False, "store": store_name, "store_key": store_key, "error": str(e)}


async def crawl_all_stores():
    """Сканира всички магазини."""
    
    browser_config = BrowserConfig(
        headless=True,
        viewport_width=1920,
        viewport_height=1080,
    )
    
    results = {}
    
    async with AsyncWebCrawler(config=browser_config) as crawler:
        # Първо Кашон (референтен)
        results["kashon"] = await crawl_store(crawler, "kashon", STORES["kashon"])
        await asyncio.sleep(3)
        
        # После останалите
        for store_key, store_config in STORES.items():
            if store_key == "kashon":
                continue
            results[store_key] = await crawl_store(crawler, store_key, store_config)
            await asyncio.sleep(3)
    
    return results


# =============================================================================
# PROCESSING
# =============================================================================

def process_results(crawl_results):
    """Обработва резултатите."""
    
    print(f"\n{'='*60}")
    print("PROCESSING RESULTS")
    print("="*60)
    
    # Извличаме референтен списък от Кашон
    kashon = crawl_results.get("kashon", {})
    
    if not kashon.get("success"):
        print("ERROR: Кашон не е зареден!")
        return {"error": "Kashon failed", "products": []}
    
    print("\n--- STEP 1: Extract products from Kashon ---")
    
    products = extract_kashon_products(
        kashon.get("markdown", ""),
        kashon.get("html", "")
    )
    
    print(f"\nExtracted {len(products)} food products from Kashon")
    
    if products:
        print("\nSample products:")
        for p in products[:10]:
            eur = f"{p['eur']:.2f}€" if p['eur'] else "N/A"
            bgn = f"{p['bgn']:.2f}лв" if p['bgn'] else "N/A"
            print(f"  - {p['name'][:45]}: {eur} / {bgn}")
    
    # Търсим в другите магазини
    print("\n--- STEP 2: Find products in other stores ---")
    
    for product in products:
        product["stores"] = {
            "kashon": {"eur": product["eur"], "bgn": product["bgn"]}
        }
        
        for store_key, store_data in crawl_results.items():
            if store_key == "kashon" or not store_data.get("success"):
                continue
            
            match = find_product_in_store(
                product["name"],
                store_data.get("markdown", "") + "\n" + store_data.get("html", "")[:50000]
            )
            
            if match and (match["eur"] or match["bgn"]):
                product["stores"][store_key] = {
                    "eur": match["eur"],
                    "bgn": match["bgn"],
                }
    
    # Статистика
    print("\n--- STEP 3: Statistics ---")
    
    for store_key in STORES.keys():
        count = sum(1 for p in products if store_key in p.get("stores", {}))
        store_name = STORES[store_key]["name"]
        pct = (count / len(products) * 100) if products else 0
        print(f"  {store_name}: {count}/{len(products)} ({pct:.0f}%)")
    
    return {"reference_count": len(products), "products": products}


# =============================================================================
# MAIN
# =============================================================================

async def main():
    """Main function."""
    
    print("\n" + "="*60)
    print("EXP-001: CRAWL4AI DYNAMIC TRACKER v6.1")
    print("="*60)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Stores: {len(STORES)}")
    print("Mode: Dynamic products from Kashon (improved extraction)")
    
    if not CRAWL4AI_AVAILABLE:
        print("\nERROR: Crawl4AI not available!")
        return
    
    total_start = time.time()
    
    # Crawl
    print("\n" + "="*60)
    print("PHASE 1: CRAWLING")
    print("="*60)
    
    crawl_results = await crawl_all_stores()
    
    # Process
    print("\n" + "="*60)
    print("PHASE 2: PROCESSING")
    print("="*60)
    
    processed = process_results(crawl_results)
    
    total_time = time.time() - total_start
    
    # Summary
    print(f"\n{'='*60}")
    print("FINAL SUMMARY")
    print("="*60)
    print(f"Total time: {total_time:.2f}s")
    print(f"Reference products: {processed.get('reference_count', 0)}")
    
    products = processed.get("products", [])
    
    if products:
        print("\nStore coverage:")
        for store_key, cfg in STORES.items():
            count = sum(1 for p in products if store_key in p.get("stores", {}))
            pct = (count / len(products) * 100) if products else 0
            print(f"  {cfg['name']}: {count}/{len(products)} ({pct:.0f}%)")
        
        print("\nSample products with all prices:")
        for p in products[:5]:
            print(f"\n  {p['name'][:50]}:")
            for store_key, prices in p.get("stores", {}).items():
                store_name = STORES[store_key]["name"]
                eur = f"{prices['eur']:.2f}€" if prices.get('eur') else "N/A"
                bgn = f"{prices['bgn']:.2f}лв" if prices.get('bgn') else "N/A"
                print(f"    {store_name}: {eur} / {bgn}")
    
    # Save
    output = {
        "experiment": "EXP-001-v6.1",
        "date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "total_time": total_time,
        "reference_count": processed.get("reference_count", 0),
        "products": products,
        "crawl_stats": {
            k: {"success": v.get("success"), "elapsed": v.get("elapsed_time")}
            for k, v in crawl_results.items()
        },
    }
    
    try:
        os.makedirs("experimental", exist_ok=True)
        with open("experimental/pilot_results.json", "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2, default=str)
        print(f"\nResults saved to: experimental/pilot_results.json")
    except Exception as e:
        print(f"\nSave error: {e}")
    
    print(f"\n{'='*60}")
    print("END")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
