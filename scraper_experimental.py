"""
EXP-001: Crawl4AI Dynamic Tracker v6.3 FINAL
=============================================
Финална версия с правилни patterns за всеки сайт.
+ EXP-003: Lilly Drogerie интеграция с in_stock tracking

Структура на данните:
- Кашон: [Име продукт](URL) с цени наблизо
- eBag: [![Име](img)](url) + ### [Име ... X,XX € ... X,XX лв.]
- Balev: Редове с грамаж + цени EUR/BGN
- Lilly: [![ALT](img)](url) [NAME](url) X,XX € / X,XX лв. Изчерпан
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

try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False
    print("WARNING: gspread not installed — Sheets write disabled")


# =============================================================================
# CONSTANTS
# =============================================================================

EUR_BGN_RATE = 1.9558  # Фиксиран курс


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
    "lilly": {
        "name": "Lilly Drogerie",
        "url": "https://lillydrogerie.bg/brands/harmonica",
        "scroll_times": 3,
        "is_reference": False,
        "wait_for": "div.products-grid, ol.products",  # Magento 2 product grid
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
    # Добавени за Lilly Drogerie продукти:
    "мармалад",
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
    
    pattern = r'\[([^\]]{5,80})\]\(https://kashonharmonica\.bg/bg/products/([^\)]+)\)'
    
    for match in re.finditer(pattern, markdown):
        name = match.group(1).strip()
        
        if name.startswith('!') or 'logo' in name.lower():
            continue
        if len(re.findall(r'[а-яА-Яa-zA-Z]', name)) < 3:
            continue
        
        name_key = name.lower()[:30]
        if name_key in seen:
            continue
        
        if not is_food_product(name):
            continue
        
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
    
    img_pattern = r'\[!\[([^\]]+)\]\([^\)]+\)\]\([^\)]+\)'
    
    for match in re.finditer(img_pattern, markdown):
        name = match.group(1).strip()
        
        if len(name) < 5 or 'flag' in name.lower():
            continue
        
        if not is_harmonica_product(name):
            continue
        
        name_key = name.lower()[:30]
        if name_key in seen:
            continue
        
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
        
        if not re.search(r'\d+\s*(?:г|мл|ml|g)\b', line, re.IGNORECASE):
            continue
        
        name = line
        name = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'\1', name)
        name = re.sub(r'!\[[^\]]*\]\([^\)]*\)', '', name)
        name = re.sub(r'https?://[^\s]+', '', name)
        name = re.sub(r'\*\*([^\*]+)\*\*', r'\1', name)
        name = re.sub(r'^\s*[\-\*\#\|\>]+\s*', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if len(name) < 5 or len(name) > 80:
            continue
        
        if len(re.findall(r'[а-яА-Яa-zA-Z]', name)) < 3:
            continue
        
        if not (is_harmonica_product(name) or 'harmonica' in markdown[max(0,i-5):i+5].lower()):
            context_lines = '\n'.join(lines[max(0,i-3):i+3])
            if not ('harmonica' in context_lines.lower() or 'хармоника' in context_lines.lower()):
                continue
        
        name_key = name.lower()[:30]
        if name_key in seen:
            continue
        
        if not is_food_product(name):
            continue
        
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
# LILLY DROGERIE EXTRACTION (EXP-003)
# =============================================================================
# ^^^ ВАЖНО: Тази функция е на TOP LEVEL (без indent), НЕ вътре в extract_balev!

def extract_lilly_products(markdown_text):
    """
    Извлича Harmonica продукти от Lilly Drogerie brand page.
    
    Markdown структура (Magento 2 SSR):
      [![ALT](img_url)](product_url)    <-- image link (пропускаме)
      [PRODUCT NAME](product_url)        <-- text link (извличаме)
      X,XX € / X,XX лв.                 <-- двойна цена
      Изчерпан                           <-- наличност (опционално)
    
    Връща list of dicts с допълнително поле 'in_stock' (bool).
    Когато in_stock=False, цената е информативна — продуктът не може да се поръча.
    """
    products = []
    product_blocks = re.split(r'\n\s*\*\s+', markdown_text)
    
    for block in product_blocks:
        if 'lillydrogerie.bg' not in block:
            continue
        
        # Име и URL — negative lookbehind за "!" пропуска image линковете
        # Изключваме /media/ URL-и (изображения)
        name_match = re.search(
            r'(?<!!)\[([^\]]*HARMONICA[^\]]*)\]\(https://lillydrogerie\.bg/(?!media/)([^\s\)]+)',
            block
        )
        if not name_match:
            continue
        
        product_name = name_match.group(1).strip()
        product_slug = name_match.group(2).strip('" ')
        product_url = f"https://lillydrogerie.bg/{product_slug}"
        
        # EUR цена (формат: X,XX €)
        eur_match = re.search(r'(\d+[.,]\d{2})\s*€', block)
        price_eur = float(eur_match.group(1).replace(',', '.')) if eur_match else None
        
        # BGN цена (формат: X,XX лв.)
        bgn_match = re.search(r'(\d+[.,]\d{2})\s*лв', block)
        price_bgn = float(bgn_match.group(1).replace(',', '.')) if bgn_match else None
        
        # Наличност — "Изчерпан" означава продуктът е на сайта, но не може да се поръча
        in_stock = 'Изчерпан' not in block
        
        if product_name and (price_eur or price_bgn):
            products.append({
                'name': product_name,
                'eur': price_eur,
                'bgn': price_bgn,
                'in_stock': in_stock,
                'url': product_url,
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
            
            common = ref_keywords & store_keywords
            score = len(common)
            
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
    wait_for_selector = store_config.get("wait_for")
    
    print(f"\n{'='*60}")
    print(f"CRAWLING: {store_name}")
    print("="*60)
    
    # За Lilly (scroll_times=0) няма нужда от scroll JS
    scroll_js = ""
    if scroll_times > 0:
        scroll_js = f"""
        async function scrollPage() {{
            for (let i = 0; i < {scroll_times}; i++) {{
                window.scrollTo(0, document.body.scrollHeight);
                await new Promise(r => setTimeout(r, 1500));
            }}
        }}
        await scrollPage();
        """
    
    config_kwargs = {
        "page_timeout": 90000,
        "remove_overlay_elements": True,
    }
    if scroll_js:
        config_kwargs["js_code"] = scroll_js
    if wait_for_selector:
        config_kwargs["wait_for"] = f"css:{wait_for_selector}"
        print(f"  Waiting for: {wait_for_selector}")
    
    config = CrawlerRunConfig(**config_kwargs)
    
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
# GOOGLE SHEETS WRITER — универсален, с in_stock сиво форматиране
# =============================================================================
#
# ДИЗАЙН ПРИНЦИПИ:
# 1. Колоните на магазините се генерират АВТОМАТИЧНО от STORES dict.
#    Добавяш нов магазин в STORES → той се появява в Sheets без промяна тук.
# 2. in_stock=False → сив текст. Работи за ВСЕКИ магазин, не само за Lilly.
# 3. Цените остават числа (не текст) — формулите за средна цена работят.
# 4. Форматирането е в един batch_update — минимални API заявки.
#

def extract_weight(name):
    """Извлича грамаж от име на продукт. Напр. 'Био вафли 40г' → '40г'"""
    match = re.search(r'(\d+)\s*(г|мл|ml|g|kg|л|l)\b', name, re.IGNORECASE)
    if match:
        return f"{match.group(1)}{match.group(2)}"
    return ""


def write_to_sheets(final_products, stats):
    """
    Записва данните в Google Sheets с автоматично сиво форматиране
    за изчерпани продукти (in_stock=False).
    
    Колоните на магазините се генерират от STORES dict — добавянето
    на нов магазин в STORES автоматично създава нова колона.
    
    Използва SHEET_TAB_SUFFIX env variable за experimental/production tabs.
    """
    if not GSPREAD_AVAILABLE:
        print("\n⚠ gspread not available — skipping Sheets write")
        return False
    
    # --- Настройки ---
    SPREADSHEET_NAME = "Harmonica Price Tracker"
    BASE_TAB = "Ценови Тракер"
    tab_suffix = os.environ.get("SHEET_TAB_SUFFIX", "")
    tab_name = f"{BASE_TAB}{tab_suffix}"
    
    # Кои магазини са не-референтни (те стават колони за цени)
    store_columns = [key for key, cfg in STORES.items() if not cfg.get("is_reference")]
    store_display_names = {key: cfg["name"] for key, cfg in STORES.items()}
    
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    print(f"\n{'='*60}")
    print(f"WRITING TO GOOGLE SHEETS")
    print(f"Tab: {tab_name}")
    print(f"Store columns: {', '.join(store_display_names[s] for s in store_columns)}")
    print("="*60)
    
    # --- Свързване (същият метод като production scraper.py) ---
    try:
        creds_json = os.environ.get("GOOGLE_CREDENTIALS")
        if creds_json:
            # Production pattern: parse JSON → create Credentials → authorize
            credentials_dict = json.loads(creds_json)
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
            credentials = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
            gc = gspread.authorize(credentials)
        else:
            # Локално: credentials.json файл
            gc = gspread.service_account(filename='credentials.json')
        
        spreadsheet = gc.open(SPREADSHEET_NAME)
        
        # Създаваме tab-а ако не съществува
        try:
            sheet = spreadsheet.worksheet(tab_name)
        except gspread.exceptions.WorksheetNotFound:
            sheet = spreadsheet.add_worksheet(title=tab_name, rows=200, cols=26)
            print(f"  Created new tab: {tab_name}")
        
        print(f"  ✓ Connected to '{tab_name}'")
        
    except Exception as e:
        print(f"  ✗ Connection failed: {e}")
        return False
    
    # --- Изграждане на данните ---
    # Колони: №, Продукт, Грамаж, Реф.BGN, Реф.EUR, [магазин1], [магазин2], ..., Ср.BGN, Откл.%, Статус
    #
    # STORE_COL_START е индексът (0-based) на първата магазинна колона.
    # Това е ключът за универсалното сиво форматиране — ние знаем
    # точния col_index на всеки магазин спрямо неговата позиция в store_columns.
    
    HEADER_ROW = 4       # Ред 4 в Sheets (0-based index: 3)
    DATA_START_ROW = 5   # Ред 5 в Sheets (0-based index: 4)
    STORE_COL_START = 5  # Колона F (0-based index: 5) — първият магазин
    
    headers = ['№', 'Продукт', 'Грамаж', 'Реф.BGN', 'Реф.EUR']
    for store_key in store_columns:
        headers.append(store_display_names[store_key])
    headers.extend(['Ср.BGN', 'Откл.%', 'Статус'])
    
    all_data = []
    
    # Ред 1: Заглавие
    all_data.append([f'HARMONICA - Ценови Тракер (EXP-003)'] + [''] * (len(headers) - 1))
    
    # Ред 2: Метаданни
    meta = [f'Актуализация: {now}', '', f'Курс: 1 EUR = {EUR_BGN_RATE} BGN', '',
            f'Магазини: {len(store_columns) + 1}']
    meta.extend([''] * (len(headers) - len(meta)))
    all_data.append(meta)
    
    # Ред 3: Празен
    all_data.append([''] * len(headers))
    
    # Ред 4: Headers
    all_data.append(headers)
    
    # =====================================================================
    # УНИВЕРСАЛЕН ТРАКЕР ЗА ИЗЧЕРПАНИ ПРОДУКТИ
    # 
    # out_of_stock_cells събира (row_index, col_index) за ВСЯКА клетка
    # от ВСЕКИ магазин, където in_stock=False.
    # Не е специфичен за Lilly — работи за всеки магазин.
    # =====================================================================
    out_of_stock_cells = []
    
    # Ред 5+: Данни
    for i, product in enumerate(final_products, 1):
        ref = product.get("kashon") or {}
        ref_bgn = ref.get("bgn")
        ref_eur = ref.get("eur")
        
        row = [
            i,
            product["name"],
            extract_weight(product["name"]),
            ref_bgn if ref_bgn else '',
            ref_eur if ref_eur else '',
        ]
        
        # Магазинни колони — обхождаме store_columns по ред
        store_prices_bgn = []
        
        for col_offset, store_key in enumerate(store_columns):
            store_data = product.get(store_key)
            col_index = STORE_COL_START + col_offset  # абсолютен 0-based индекс
            row_index = DATA_START_ROW - 1 + i        # 0-based row в Sheets
            
            if store_data:
                price_bgn = store_data.get("bgn")
                row.append(price_bgn if price_bgn else '')
                
                if price_bgn:
                    store_prices_bgn.append(price_bgn)
                
                # === УНИВЕРСАЛНО ПРАВИЛО ЗА СИВО ===
                # Ако магазинът има in_stock=False, маркираме клетката.
                # Магазини без in_stock поле (напр. eBag, Balev) 
                # default-ват на True и никога не стават сиви.
                if not store_data.get("in_stock", True):
                    out_of_stock_cells.append((row_index, col_index))
            else:
                row.append('')
        
        # Средна цена (само от наличните магазини)
        if store_prices_bgn:
            avg_bgn = round(sum(store_prices_bgn) / len(store_prices_bgn), 2)
            row.append(avg_bgn)
        else:
            avg_bgn = None
            row.append('')
        
        # Отклонение от референтна цена
        if avg_bgn and ref_bgn and ref_bgn > 0:
            deviation = round((avg_bgn - ref_bgn) / ref_bgn * 100, 1)
            row.append(f"{deviation}%")
        else:
            row.append('')
        
        # Статус
        matched_count = sum(1 for s in store_columns if product.get(s))
        row.append(f"{matched_count}/{len(store_columns)}")
        
        all_data.append(row)
    
    # --- Запис на данните ---
    try:
        sheet.clear()
        sheet.update(values=all_data, range_name='A1')
        print(f"  ✓ Записани {len(all_data)} реда × {len(headers)} колони")
    except Exception as e:
        print(f"  ✗ Data write error: {e}")
        return False
    
    # --- Форматиране ---
    try:
        last_row = HEADER_ROW + len(final_products)
        last_col = len(headers)
        format_requests = []
        
        # 1. Заглавен ред — тъмно зелено
        format_requests.append({
            "repeatCell": {
                "range": {"sheetId": sheet.id,
                          "startRowIndex": 0, "endRowIndex": 1,
                          "startColumnIndex": 0, "endColumnIndex": last_col},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": {"red": 0.13, "green": 0.35, "blue": 0.22},
                    "textFormat": {"bold": True, "fontSize": 14,
                                   "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                    "horizontalAlignment": "CENTER"
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"
            }
        })
        
        # Merge заглавния ред
        format_requests.append({
            "mergeCells": {
                "range": {"sheetId": sheet.id,
                          "startRowIndex": 0, "endRowIndex": 1,
                          "startColumnIndex": 0, "endColumnIndex": last_col},
                "mergeType": "MERGE_ALL"
            }
        })
        
        # 2. Метаданни — светло зелено
        format_requests.append({
            "repeatCell": {
                "range": {"sheetId": sheet.id,
                          "startRowIndex": 1, "endRowIndex": 2,
                          "startColumnIndex": 0, "endColumnIndex": last_col},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": {"red": 0.92, "green": 0.97, "blue": 0.92},
                    "textFormat": {"italic": True, "fontSize": 10}
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat)"
            }
        })
        
        # 3. Header ред — сиво-зелен фон, bold
        format_requests.append({
            "repeatCell": {
                "range": {"sheetId": sheet.id,
                          "startRowIndex": HEADER_ROW - 1, "endRowIndex": HEADER_ROW,
                          "startColumnIndex": 0, "endColumnIndex": last_col},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": {"red": 0.85, "green": 0.92, "blue": 0.85},
                    "textFormat": {"bold": True, "fontSize": 10},
                    "horizontalAlignment": "CENTER"
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"
            }
        })
        
        # 4. Числов формат за ценовите колони
        price_start = 3  # Колона D (Реф.BGN) — 0-based index
        price_end = STORE_COL_START + len(store_columns) + 1  # включва Ср.BGN
        if last_row > HEADER_ROW:
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id,
                              "startRowIndex": HEADER_ROW, "endRowIndex": last_row,
                              "startColumnIndex": price_start, "endColumnIndex": price_end},
                    "cell": {"userEnteredFormat": {
                        "numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}
                    }},
                    "fields": "userEnteredFormat.numberFormat"
                }
            })
        
        # 5. Ширини на колоните
        col_widths = {0: 35, 1: 250, 2: 55}  # №, Продукт, Грамаж
        col_widths[3] = 75   # Реф.BGN
        col_widths[4] = 75   # Реф.EUR
        for offset in range(len(store_columns)):
            col_widths[STORE_COL_START + offset] = 85  # магазинни колони
        col_widths[STORE_COL_START + len(store_columns)] = 75      # Ср.BGN
        col_widths[STORE_COL_START + len(store_columns) + 1] = 65  # Откл.%
        col_widths[STORE_COL_START + len(store_columns) + 2] = 55  # Статус
        
        for col_idx, width in col_widths.items():
            format_requests.append({
                "updateDimensionProperties": {
                    "range": {"sheetId": sheet.id,
                              "dimension": "COLUMNS",
                              "startIndex": col_idx, "endIndex": col_idx + 1},
                    "properties": {"pixelSize": width},
                    "fields": "pixelSize"
                }
            })
        
        # =================================================================
        # 6. УНИВЕРСАЛНО СИВО ФОРМАТИРАНЕ ЗА ИЗЧЕРПАНИ ПРОДУКТИ
        #
        # Всяка клетка в out_of_stock_cells получава сив текст (#999999).
        # Цената остава число — формулите работят нормално.
        # Визуално е ясно, че продуктът не може да се поръча.
        #
        # Това работи за ВСЕКИ магазин — не е Lilly-специфично.
        # Ако утре eBag започне да маркира изчерпани продукти,
        # просто добави in_stock в eBag extraction и всичко работи.
        # =================================================================
        
        for row_idx, col_idx in out_of_stock_cells:
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id,
                              "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                              "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1},
                    "cell": {"userEnteredFormat": {
                        "textFormat": {
                            "foregroundColorStyle": {
                                "rgbColor": {"red": 0.6, "green": 0.6, "blue": 0.6}
                            }
                        }
                    }},
                    "fields": "userEnteredFormat.textFormat.foregroundColorStyle"
                }
            })
        
        # Изпращаме всичко в ЕДИН batch — минимални API заявки
        if format_requests:
            sheet.spreadsheet.batch_update({"requests": format_requests})
            print(f"  ✓ Форматиране приложено ({len(format_requests)} заявки)")
            if out_of_stock_cells:
                print(f"  ✓ Сиво форматиране: {len(out_of_stock_cells)} изчерпани клетки")
        
        return True
        
    except Exception as e:
        print(f"  ⚠ Formatting error (data is saved): {e}")
        return True  # данните са записани, само форматирането е пропуснато


# =============================================================================
# MAIN
# =============================================================================

async def main():
    print("\n" + "="*60)
    print("EXP-003: CRAWL4AI v6.3 + Lilly Drogerie")
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
    
    # Lilly Drogerie (EXP-003)
    lilly_products = []
    if crawl_results.get("lilly", {}).get("success"):
        lilly_md = crawl_results["lilly"]["markdown"]
        # Debug: показваме какво е получено (за диагностика на 1-char проблема)
        print(f"\n[DEBUG] Lilly markdown length: {len(lilly_md)} chars")
        print(f"[DEBUG] Lilly markdown repr: {repr(lilly_md[:500])}")
        
        lilly_products = extract_lilly_products(lilly_md)
        print(f"\nLilly Drogerie: {len(lilly_products)} Harmonica products")
        for p in lilly_products[:10]:
            eur = f"{p['eur']:.2f}€" if p['eur'] else "N/A"
            bgn = f"{p['bgn']:.2f}лв" if p['bgn'] else "N/A"
            stock = "✅" if p['in_stock'] else "⬜"
            print(f"  {stock} {p['name'][:45]}: {eur} / {bgn}")
    
    # 3. Match products
    print("\n" + "="*60)
    print("MATCHING PRODUCTS")
    print("="*60)
    
    # =========================================================================
    # ПОПРАВКА: Lilly е добавена в структурата на final_products
    # =========================================================================
    final_products = []
    
    for ref in kashon_products:
        product = {
            "name": ref["name"],
            "kashon": {"eur": ref["eur"], "bgn": ref["bgn"]},
            "ebag": None,
            "balev": None,
            "lilly": None,   # ← ДОБАВЕНО: слот за Lilly
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
    
    # =========================================================================
    # ДОБАВЕНО: Match с Lilly — запазваме и in_stock за сиво форматиране
    # =========================================================================
    lilly_matches = match_products(kashon_products, lilly_products)
    for product in final_products:
        if product["name"] in lilly_matches:
            m = lilly_matches[product["name"]]
            product["lilly"] = {
                "eur": m["eur"],
                "bgn": m["bgn"],
                "in_stock": m.get("in_stock", True),  # ← ключово за сивото
            }
    
    # 4. Statistics
    print("\n" + "="*60)
    print("FINAL STATISTICS")
    print("="*60)
    
    kashon_count = len([p for p in final_products if p["kashon"]])
    ebag_count = len([p for p in final_products if p["ebag"]])
    balev_count = len([p for p in final_products if p["balev"]])
    lilly_count = len([p for p in final_products if p["lilly"]])
    lilly_oos_count = len([p for p in final_products
                           if p["lilly"] and not p["lilly"].get("in_stock", True)])
    
    print(f"\nReference products (Кашон): {kashon_count}")
    if kashon_count:
        print(f"eBag matches: {ebag_count} ({ebag_count/kashon_count*100:.0f}%)")
        print(f"Balev matches: {balev_count} ({balev_count/kashon_count*100:.0f}%)")
        print(f"Lilly matches: {lilly_count} ({lilly_count/kashon_count*100:.0f}%)"
              f" — {lilly_oos_count} изчерпани")
    
    # Показваме примерни продукти с цени от всички магазини
    print("\n--- Sample products with prices ---")
    matched_products = [p for p in final_products
                        if p["ebag"] or p["balev"] or p["lilly"]][:10]
    
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
        if p["lilly"]:
            eur = f"{p['lilly']['eur']:.2f}€" if p['lilly'].get('eur') else "N/A"
            bgn = f"{p['lilly']['bgn']:.2f}лв" if p['lilly'].get('bgn') else "N/A"
            stock = "✅" if p['lilly'].get('in_stock', True) else "⬜ изчерпан"
            print(f"  Lilly: {eur} / {bgn} {stock}")
    
    total_time = time.time() - total_start
    
    # 5. Write to Google Sheets
    write_to_sheets(final_products, {
        "kashon_products": kashon_count,
        "ebag_matches": ebag_count,
        "balev_matches": balev_count,
        "lilly_matches": lilly_count,
        "lilly_out_of_stock": lilly_oos_count,
    })
    
    # 6. Save JSON (backup / debugging)
    output = {
        "experiment": "EXP-003-lilly-integration",
        "date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "total_time": round(total_time, 2),
        "stats": {
            "kashon_products": kashon_count,
            "ebag_products": len(ebag_products),
            "ebag_matches": ebag_count,
            "balev_products": len(balev_products),
            "balev_matches": balev_count,
            "lilly_products": len(lilly_products),
            "lilly_matches": lilly_count,
            "lilly_out_of_stock": lilly_oos_count,
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
