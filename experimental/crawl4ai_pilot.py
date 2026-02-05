"""
EXP-001: Crawl4AI Dynamic Tracker v6.3 FINAL
=============================================
Финална версия с правилни patterns за всеки сайт.

Структура на данните:
- Кашон: [Име продукт](URL) с цени наблизо
- eBag: [![Име](img)](url) + ### [Име ... X,XX € ... X,XX лв.]
- Balev: Редове с грамаж + цени EUR/BGN
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
# STORES
# =============================================================================

STORES = {
    "kashon": {
        "name": "Кашон Harmonica",
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
    "извара", "йогурт", "крема", "сок", "лимонада", "боза", "сироп",
    "локум", "бисквит", "вафла", "шоколад", "бонбон", "сладко", "халва",
    "претцел", "солет", "крекер", "соленки", "лешник", "бадем", "орех",
    "домат", "кетчуп", "лютеница", "пюре", "паста", "хляб", "кори",
    "олио", "оцет", "зехтин", "мед", "чай", "smiles", "топчета",
    "нахут", "хумус", "яйца", "тахан", "фъстъчено",
]

NON_FOOD_KEYWORDS = [
    "потник", "тениска", "блуза", "дреха", "шапка", "чанта", "раница",
    "козметика", "крем", "шампоан", "сапун", "гел", "лосион",
]


def is_food_product(name):
    """Проверява дали е храна."""
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


def is_harmonica_product(name):
    """Проверява дали е Harmonica продукт."""
    name_lower = name.lower()
    return "harmonica" in name_lower or "хармоника" in name_lower


# =============================================================================
# PRICE EXTRACTION
# =============================================================================

def extract_eur_price(text):
    """Извлича EUR цена."""
    # Pattern: X,XX € или X.XX €
    match = re.search(r'(\d+)[,.](\d{2})\s*€', text)
    if match:
        try:
            price = float(f"{match.group(1)}.{match.group(2)}")
            if 0.20 <= price <= 100:
                return round(price, 2)
        except:
            pass
    return None


def extract_bgn_price(text):
    """Извлича BGN цена."""
    # Pattern: X,XX лв или X.XX лв
    match = re.search(r'(\d+)[,.](\d{2})\s*лв', text)
    if match:
        try:
            price = float(f"{match.group(1)}.{match.group(2)}")
            if 0.50 <= price <= 200:
                return round(price, 2)
        except:
            pass
    return None


# =============================================================================
# KASHON EXTRACTION
# =============================================================================

def extract_kashon_products(markdown):
    """
    Извлича продукти от Кашон.
    Формат: [Име на продукт](https://kashonharmonica.bg/bg/products/...)
    """
    products = []
    seen = set()
    
    # Pattern за markdown links към продукти
    pattern = r'\[([^\]]{5,80})\]\(https://kashonharmonica\.bg/bg/products/([^\)]+)\)'
    
    for match in re.finditer(pattern, markdown):
        name = match.group(1).strip()
        
        # Пропускаме невалидни
        if name.startswith('!') or 'logo' in name.lower():
            continue
        if len(re.findall(r'[а-яА-Яa-zA-Z]', name)) < 3:
            continue
        
        # Проверяваме за дубликати
        name_key = name.lower()[:30]
        if name_key in seen:
            continue
        
        # Филтрираме само храни
        if not is_food_product(name):
            continue
        
        # Търсим цена в контекста (следващите 300 символа)
        idx = match.end()
        context = markdown[idx:idx+300]
        
        eur = extract_eur_price(context)
        bgn = extract_bgn_price(context)
        
        if eur or bgn:
            seen.add(name_key)
            products.append({
                "name": name,
                "eur": eur,
                "bgn": bgn,
            })
    
    return products


# =============================================================================
# EBAG EXTRACTION
# =============================================================================

def extract_ebag_products(markdown):
    """
    Извлича продукти от eBag.
    
    Формат 1: [![Име продукт](image_url)](product_url)
    Формат 2: ### [Име продукт Годно до: XX/XX/XXXX X,XX €X,XX € X,XX лв.X,XX лв.]
    """
    products = []
    seen = set()
    
    # Pattern 1: Alt текст на изображения
    img_pattern = r'\[!\[([^\]]+)\]\([^\)]+\)\]\([^\)]+\)'
    
    for match in re.finditer(img_pattern, markdown):
        name = match.group(1).strip()
        
        if len(name) < 5 or 'flag' in name.lower():
            continue
        
        # Проверяваме дали е Harmonica
        if not is_harmonica_product(name):
            continue
        
        name_key = name.lower()[:30]
        if name_key in seen:
            continue
        
        # Търсим цени в контекста
        idx = match.start()
        context = markdown[max(0, idx-50):idx+500]
        
        eur = extract_eur_price(context)
        bgn = extract_bgn_price(context)
        
        if eur or bgn:
            seen.add(name_key)
            products.append({
                "name": name,
                "eur": eur,
                "bgn": bgn,
            })
    
    # Pattern 2: Заглавия с цени
    # ### [Био Боза Harmonica от Ръж Годно до: 15/02/2026 1,88 €2,35 € 3,68 лв.4,60 лв. ...]
    title_pattern = r'###\s*\[\s*([^\]]+?)\s+Годно до:[^\]]*?(\d+[,\.]\d{2})\s*€[^\]]*?(\d+[,\.]\d{2})\s*лв'
    
    for match in re.finditer(title_pattern, markdown):
        name = match.group(1).strip()
        
        if len(name) < 5:
            continue
        
        if not is_harmonica_product(name):
            continue
        
        name_key = name.lower()[:30]
        if name_key in seen:
            continue
        
        try:
            eur = float(match.group(2).replace(",", "."))
            bgn = float(match.group(3).replace(",", "."))
            
            if 0.20 <= eur <= 100 and 0.50 <= bgn <= 200:
                seen.add(name_key)
                products.append({
                    "name": name,
                    "eur": round(eur, 2),
                    "bgn": round(bgn, 2),
                })
        except:
            pass
    
    return products


# =============================================================================
# BALEV EXTRACTION
# =============================================================================

def extract_balev_products(markdown):
    """
    Извлича продукти от Balev.
    
    Формат: Редове с грамаж близо до цени EUR/BGN.
    Пример: "Био пълнозърнести солети 60г" + "1.07€" / "2.09лв"
    """
    products = []
    seen = set()
    
    lines = markdown.split('\n')
    
    for i, line in enumerate(lines):
        line = line.strip()
        
        # Търсим редове с грамаж
        if not re.search(r'\d+\s*(?:г|мл|ml|g)\b', line, re.IGNORECASE):
            continue
        
        # Почистваме името
        name = line
        name = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'\1', name)  # [text](url) -> text
        name = re.sub(r'!\[[^\]]*\]\([^\)]*\)', '', name)  # ![alt](url) -> remove
        name = re.sub(r'https?://[^\s]+', '', name)
        name = re.sub(r'\*\*([^\*]+)\*\*', r'\1', name)  # **bold** -> bold
        name = re.sub(r'^\s*[\-\*\#\|\>]+\s*', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if len(name) < 5 or len(name) > 80:
            continue
        
        if len(re.findall(r'[а-яА-Яa-zA-Z]', name)) < 3:
            continue
        
        # Проверяваме дали е Harmonica
        if not (is_harmonica_product(name) or 'harmonica' in markdown[max(0,i-5):i+5].lower()):
            # Проверяваме контекста за Harmonica
            context_lines = '\n'.join(lines[max(0,i-3):i+3])
            if not ('harmonica' in context_lines.lower() or 'хармоника' in context_lines.lower()):
                continue
        
        name_key = name.lower()[:30]
        if name_key in seen:
            continue
        
        if not is_food_product(name):
            continue
        
        # Търсим цени в контекста
        context = '\n'.join(lines[max(0,i-2):i+5])
        
        eur = extract_eur_price(context)
        bgn = extract_bgn_price(context)
        
        if eur or bgn:
            seen.add(name_key)
            products.append({
                "name": name,
                "eur": eur,
                "bgn": bgn,
            })
    
    return products


# =============================================================================
# MATCHING
# =============================================================================

def normalize_name(name):
    """Нормализира име за сравнение."""
    name = name.lower()
    name = re.sub(r'harmonica|хармоника|био\s*', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def extract_keywords(name):
    """Извлича ключови думи от име."""
    name = normalize_name(name)
    # Думи + числа с мерни единици
    keywords = re.findall(r'[а-я]{3,}|\d+(?:\s*(?:г|мл|ml|g|%|л))?', name)
    return set(keywords)


def match_products(ref_products, store_products):
    """
    Съпоставя продукти от магазин с референтния списък.
    Връща dict с matches.
    """
    matches = {}
    
    for ref in ref_products:
        ref_keywords = extract_keywords(ref["name"])
        best_match = None
        best_score = 0
        
        for store_prod in store_products:
            store_keywords = extract_keywords(store_prod["name"])
            
            # Общи keywords
            common = ref_keywords & store_keywords
            score = len(common)
            
            # Бонус за съвпадение на грамаж
            ref_weight = re.search(r'(\d+)\s*(?:г|мл|ml|g)', ref["name"].lower())
            store_weight = re.search(r'(\d+)\s*(?:г|мл|ml|g)', store_prod["name"].lower())
            
            if ref_weight and store_weight and ref_weight.group(1) == store_weight.group(1):
                score += 2
            
            if score >= 2 and score > best_score:
                best_score = score
                best_match = store_prod
        
        if best_match:
            matches[ref["name"]] = best_match
    
    return matches


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
    print("="*60)
    
    scroll_js = f"""
    async function scrollPage() {{
        for (let i = 0; i < {scroll_times}; i++) {{
            window.scrollTo(0, document.body.scrollHeight);
            await new Promise(r => setTimeout(r, 1500));
        }}
    }}
    await scrollPage();
    """
    
    config = CrawlerRunConfig(
        page_timeout=90000,
        remove_overlay_elements=True,
        js_code=scroll_js,
    )
    
    start = time.time()
    
    try:
        result = await crawler.arun(url=url, config=config)
        elapsed = time.time() - start
        
        if not result.success:
            print(f"FAILED: {result.error_message}")
            return {"success": False, "error": result.error_message}
        
        print(f"SUCCESS: {elapsed:.2f}s, {len(result.markdown)} chars")
        
        return {
            "success": True,
            "store_key": store_key,
            "elapsed": elapsed,
            "markdown": result.markdown,
        }
    except Exception as e:
        print(f"ERROR: {e}")
        return {"success": False, "error": str(e)}


async def crawl_all():
    """Сканира всички магазини."""
    
    browser_config = BrowserConfig(headless=True, viewport_width=1920, viewport_height=1080)
    results = {}
    
    async with AsyncWebCrawler(config=browser_config) as crawler:
        for key, cfg in STORES.items():
            results[key] = await crawl_store(crawler, key, cfg)
            await asyncio.sleep(2)
    
    return results


# =============================================================================
# MAIN
# =============================================================================

async def main():
    print("\n" + "="*60)
    print("EXP-001: CRAWL4AI v6.3 FINAL")
    print("="*60)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if not CRAWL4AI_AVAILABLE:
        print("ERROR: Crawl4AI not available!")
        return
    
    total_start = time.time()
    
    # 1. Crawl
    crawl_results = await crawl_all()
    
    # 2. Extract products
    print("\n" + "="*60)
    print("EXTRACTING PRODUCTS")
    print("="*60)
    
    # Кашон (референтен)
    kashon_products = []
    if crawl_results.get("kashon", {}).get("success"):
        kashon_products = extract_kashon_products(crawl_results["kashon"]["markdown"])
        print(f"\nКашон: {len(kashon_products)} Harmonica products")
        for p in kashon_products[:10]:
            eur = f"{p['eur']:.2f}€" if p['eur'] else "N/A"
            bgn = f"{p['bgn']:.2f}лв" if p['bgn'] else "N/A"
            print(f"  - {p['name'][:45]}: {eur} / {bgn}")
    
    # eBag
    ebag_products = []
    if crawl_results.get("ebag", {}).get("success"):
        ebag_products = extract_ebag_products(crawl_results["ebag"]["markdown"])
        print(f"\neBag: {len(ebag_products)} Harmonica products")
        for p in ebag_products[:10]:
            eur = f"{p['eur']:.2f}€" if p['eur'] else "N/A"
            bgn = f"{p['bgn']:.2f}лв" if p['bgn'] else "N/A"
            print(f"  - {p['name'][:45]}: {eur} / {bgn}")
    
    # Balev
    balev_products = []
    if crawl_results.get("balev", {}).get("success"):
        balev_products = extract_balev_products(crawl_results["balev"]["markdown"])
        print(f"\nBalev: {len(balev_products)} Harmonica products")
        for p in balev_products[:10]:
            eur = f"{p['eur']:.2f}€" if p['eur'] else "N/A"
            bgn = f"{p['bgn']:.2f}лв" if p['bgn'] else "N/A"
            print(f"  - {p['name'][:45]}: {eur} / {bgn}")
    
    # 3. Match products
    print("\n" + "="*60)
    print("MATCHING PRODUCTS")
    print("="*60)
    
    # Построяваме финален списък
    final_products = []
    
    for ref in kashon_products:
        product = {
            "name": ref["name"],
            "kashon": {"eur": ref["eur"], "bgn": ref["bgn"]},
            "ebag": None,
            "balev": None,
        }
        final_products.append(product)
    
    # Match с eBag
    ebag_matches = match_products(kashon_products, ebag_products)
    for product in final_products:
        if product["name"] in ebag_matches:
            m = ebag_matches[product["name"]]
            product["ebag"] = {"eur": m["eur"], "bgn": m["bgn"]}
    
    # Match с Balev
    balev_matches = match_products(kashon_products, balev_products)
    for product in final_products:
        if product["name"] in balev_matches:
            m = balev_matches[product["name"]]
            product["balev"] = {"eur": m["eur"], "bgn": m["bgn"]}
    
    # 4. Statistics
    print("\n" + "="*60)
    print("FINAL STATISTICS")
    print("="*60)
    
    kashon_count = len([p for p in final_products if p["kashon"]])
    ebag_count = len([p for p in final_products if p["ebag"]])
    balev_count = len([p for p in final_products if p["balev"]])
    
    print(f"\nReference products (Кашон): {kashon_count}")
    print(f"eBag matches: {ebag_count} ({ebag_count/kashon_count*100:.0f}%)" if kashon_count else "")
    print(f"Balev matches: {balev_count} ({balev_count/kashon_count*100:.0f}%)" if kashon_count else "")
    
    # Показваме примерни продукти с цени от всички магазини
    print("\n--- Sample products with prices ---")
    matched_products = [p for p in final_products if p["ebag"] or p["balev"]][:10]
    
    for p in matched_products:
        print(f"\n{p['name'][:50]}:")
        if p["kashon"]:
            eur = f"{p['kashon']['eur']:.2f}€" if p['kashon'].get('eur') else "N/A"
            bgn = f"{p['kashon']['bgn']:.2f}лв" if p['kashon'].get('bgn') else "N/A"
            print(f"  Кашон: {eur} / {bgn}")
        if p["ebag"]:
            eur = f"{p['ebag']['eur']:.2f}€" if p['ebag'].get('eur') else "N/A"
            bgn = f"{p['ebag']['bgn']:.2f}лв" if p['ebag'].get('bgn') else "N/A"
            print(f"  eBag:  {eur} / {bgn}")
        if p["balev"]:
            eur = f"{p['balev']['eur']:.2f}€" if p['balev'].get('eur') else "N/A"
            bgn = f"{p['balev']['bgn']:.2f}лв" if p['balev'].get('bgn') else "N/A"
            print(f"  Balev: {eur} / {bgn}")
    
    total_time = time.time() - total_start
    
    # 5. Save results
    output = {
        "experiment": "EXP-001-v6.3-final",
        "date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "total_time": round(total_time, 2),
        "stats": {
            "kashon_products": kashon_count,
            "ebag_products": len(ebag_products),
            "ebag_matches": ebag_count,
            "balev_products": len(balev_products),
            "balev_matches": balev_count,
        },
        "products": final_products,
    }
    
    try:
        os.makedirs("experimental", exist_ok=True)
        with open("experimental/pilot_results.json", "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n✓ Results saved to: experimental/pilot_results.json")
    except Exception as e:
        print(f"\n✗ Save error: {e}")
    
    print(f"\n{'='*60}")
    print(f"DONE in {total_time:.2f}s")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
