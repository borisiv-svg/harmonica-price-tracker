"""
Harmonica Price Tracker v10.1
==============================
Unified scraper — async архитектура (Crawl4AI + curl_cffi + Firecrawl).
Claude Sonnet валидация на outlier цени (EUR).
Продуктов списък от harmonica_products.json (месечен sync с Кашон).

Магазини: Кашон, eBag, Balev, Lilly, DM, T-Market, Metro, Randi,
          Zelen, BioMarket, BeFit, Laika + Glovo (Fantastico, Billa, CBA, Kaufland).
"""

import asyncio
import functools
import time
import json
import os
import re
import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('scraper.log', encoding='utf-8'),
    ]
)
logger = logging.getLogger('harmonica')

try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
    CRAWL4AI_AVAILABLE = True
except ImportError:
    CRAWL4AI_AVAILABLE = False
    logger.error("Crawl4AI not installed")

try:
    import capsolver
    CAPSOLVER_AVAILABLE = True
except ImportError:
    CAPSOLVER_AVAILABLE = False
    logger.warning("capsolver not installed — anti-bot bypass disabled")

try:
    import gspread
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False
    logger.warning("gspread not installed — Sheets write disabled")

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    logger.warning("beautifulsoup4 not installed — using regex fallback for Lilly")

try:
    from curl_cffi.requests import AsyncSession as CurlAsyncSession
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False
    logger.warning("curl_cffi not installed — TLS impersonation disabled")

try:
    from firecrawl import FirecrawlApp
    FIRECRAWL_AVAILABLE = True
except ImportError:
    FIRECRAWL_AVAILABLE = False
    logger.warning("firecrawl not installed — Glovo JS rendering disabled")

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    logger.warning("anthropic not installed — Claude price validation disabled")


# =============================================================================
# CONSTANTS
# =============================================================================

EUR_BGN_RATE = 1.9558  # Фиксиран курс
PROXY_URL = os.environ.get("PROXY_URL")  # Optional: http://user:pass@host:port
GLOVO_AUTH_TOKEN = os.environ.get("GLOVO_AUTH_TOKEN")  # Optional: Glovo Bearer token
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY")  # Optional: Firecrawl API key
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")  # Optional: Claude API key за валидация

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")

PRODUCTS_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "data", "products", "harmonica_products.json")


def load_product_list():
    """
    Зарежда референтен списък продукти от harmonica_products.json.
    Връща списък от активни продукти с name, ref_eur, ref_bgn, status.
    Fallback: ако файлът не съществува, връща празен списък.
    """
    if not os.path.exists(PRODUCTS_JSON_PATH):
        logger.warning(f"Продуктов файл не е намерен: {PRODUCTS_JSON_PATH}")
        return []

    try:
        with open(PRODUCTS_JSON_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)

        products = []
        for p in data.get("products", []):
            ref_eur = p.get("ref_eur")
            ref_bgn = p.get("ref_bgn")
            # Изчисляваме EUR от BGN ако липсва
            if not ref_eur and ref_bgn:
                ref_eur = round(ref_bgn / EUR_BGN_RATE, 2)

            products.append({
                "name": p["name"],
                "ref_eur": ref_eur,
                "ref_bgn": ref_bgn,
                "status": p.get("status", "active"),
                "active": p.get("active", True),
            })

        active = [p for p in products if p["active"]]
        logger.info(f"Заредени {len(active)} активни продукта от {os.path.basename(PRODUCTS_JSON_PATH)}")
        return active
    except Exception as e:
        logger.error(f"Грешка при зареждане на продуктов файл: {e}")
        return []


def update_product_list_with_new(reference_products, kashon_products):
    """
    Сравнява референтния списък (от JSON) с извлечените от Кашон продукти.
    Добавя нови продукти с status='new'. Връща обновен reference list.
    """
    ref_names_lower = {p["name"].lower() for p in reference_products}
    new_count = 0

    for kp in kashon_products:
        if kp["name"].lower() not in ref_names_lower:
            reference_products.append({
                "name": kp["name"],
                "ref_eur": kp.get("eur"),
                "ref_bgn": kp.get("bgn"),
                "status": "new",
                "active": True,
            })
            ref_names_lower.add(kp["name"].lower())
            new_count += 1

    if new_count:
        logger.info(f"Открити {new_count} нови продукта от Кашон (маркирани като 'new')")

    return reference_products


def save_product_list(reference_products):
    """Записва обновения списък обратно в harmonica_products.json."""
    try:
        os.makedirs(os.path.dirname(PRODUCTS_JSON_PATH), exist_ok=True)
        products_data = []
        for i, p in enumerate(reference_products, 1):
            ref_eur = p.get("ref_eur")
            ref_bgn = p.get("ref_bgn")
            name = p["name"]
            # Генериране на keywords от името
            words = re.findall(r'[а-яА-Яa-zA-Z]+|\d+[.,]?\d*\s*(?:г|мл|ml|g|kg|кг|л|l|%)',
                               name.lower())
            keywords = [w.strip() for w in words if len(w.strip()) > 1]

            products_data.append({
                "id": i,
                "name": name,
                "keywords": keywords,
                "ref_eur": ref_eur,
                "ref_bgn": ref_bgn,
                "url_slug": "",
                "active": p.get("active", True),
                "status": p.get("status", "active"),
                "added_date": p.get("added_date", datetime.now().strftime("%Y-%m-%d")),
            })

        output = {
            "version": "2.0",
            "last_sync": datetime.now().strftime("%Y-%m-%d"),
            "source": "kashonharmonica.bg",
            "total_products": len(products_data),
            "products": products_data,
        }

        with open(PRODUCTS_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        logger.info(f"Продуктов файл обновен: {len(products_data)} продукта")
    except Exception as e:
        logger.error(f"Грешка при запис на продуктов файл: {e}")


def _parse_proxy_url(proxy_url):
    """Парсва proxy URL за Playwright proxy_config (server, username, password)."""
    if not proxy_url:
        return None
    from urllib.parse import urlparse
    parsed = urlparse(proxy_url)
    if parsed.username:
        return {
            "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
            "username": parsed.username,
            "password": parsed.password or "",
        }
    return {"server": proxy_url}


# =============================================================================
# STORES
# =============================================================================

STORES = {
    "kashon": {
        "name": "Кашон",
        "url": "https://kashonharmonica.bg/bg/products/field_producer/harmonica-144",
        "scroll_times": 20,
        "scroll_delay": 2000,
        "is_master": True,
    },
    "ebag": {
        "name": "eBag",
        "url": "https://www.ebag.bg/search/?products%5BrefinementList%5D%5Bbrand_name_bg%5D%5B0%5D=%D0%A5%D0%B0%D1%80%D0%BC%D0%BE%D0%BD%D0%B8%D0%BA%D0%B0",
        "scroll_times": 12,
    },
    "balev": {
        "name": "Balev Bio",
        "url": "https://balevbiomarket.com/productBrands/harmonica",
        "scroll_times": 8,
    },
    "lilly": {
        "name": "Lilly",
        "url": "https://lillydrogerie.bg/brands/harmonica",
        "scroll_times": 4,
        "brand_page": True,
        "use_magic": True,
    },
    "dm": {
        "name": "DM",
        "url": "https://www.dm-drogeriemarkt.bg/search?query=harmonica&searchType=product",
        "scroll_times": 5,
        "needs_captcha_solver": True,
        "algolia_enabled": True,
    },
    "tmarket": {
        "name": "T-Market",
        "url": "https://tmarketonline.bg/vendor/harmonica-1881705916",
        "scroll_times": 8,
        "brand_page": True,
        "needs_captcha_solver": True,
    },
    "metro": {
        "name": "Metro",
        "url": "https://shop.metro.bg/shop/search?q=%D1%85%D0%B0%D1%80%D0%BC%D0%BE%D0%BD%D0%B8%D0%BA%D0%B0",
        "scroll_times": 15,
    },
    "zelen": {
        "name": "Zelen",
        "url": "https://zelen.bg/brand/94/harmonica",
        "scroll_times": 10,
        "brand_page": True,
    },
    "randi": {
        "name": "Randi",
        "url": "https://randi.bg/search?search=harmonica",
        "scroll_times": 10,
    },
    "biomarket": {
        "name": "Bio-Market",
        "url": "https://bio-market.bg/brand/harmonica",
        "scroll_times": 10,
        "brand_page": True,
    },
    "befit": {
        "name": "BeFit",
        "url": "https://befit.bg/brands/harmonica",
        "scroll_times": 10,
        "brand_page": True,
    },
    "laika": {
        "name": "Laika",
        "url": "https://laika.bg/harmonica-bio-bulgaria-proizvodstvo-magi-maleeva-shoko-ghi-kefir-boza-koze-sirene-ovche-izvara-bulgarska-tzena-kade-da-kupia-magazin-online",
        "scroll_times": 10,
        "brand_page": True,
    },
}

# Glovo магазини в София — ще се сканират чрез Glovo API
GLOVO_STORES = {
    "glovo_kaufland": {
        "name": "Kaufland",
        "slug": "kaufland-sof",
        "city_code": "SOF",
    },
    "glovo_billa": {
        "name": "Billa",
        "slug": "billa-sof1",
        "city_code": "SOF",
    },
    "glovo_cba": {
        "name": "CBA",
        "slug": "cba-supermarket-cherni-vruh-sof",
        "city_code": "SOF",
    },
    "glovo_fantastico": {
        "name": "Fantastico",
        "slug": "coca-cola-real-magic-sof",
        "city_code": "SOF",
    },
}

GLOVO_API_BASE = "https://api.glovoapp.com/v3"


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
    "мармалад", "леща", "киноа", "боб", "мунг", "ориз",
]

NON_FOOD_KEYWORDS = [
    "потник", "тениска", "блуза", "дреха", "шапка", "чанта", "раница",
    "козметика", "крем", "шампоан", "сапун", "гел", "лосион",
    "загадки", "книга", "игра", "пъзел", "играчка",
]

# Приоритетни пренасочвания: (подниз, категория) — проверяват се преди основните
# ключови думи, за да решат конфликти като "фъстъчено масло" ≠ "масло" (млечно).
CATEGORY_OVERRIDES = [
    ("гранола", "Други"),
    ("smiles", "Други"),
    ("бисквит", "Вафли и сладки"),
    ("фъстъчено масло", "Тахани, ядки и бобови"),
    ("кокосово масло", "Тахани, ядки и бобови"),
]

# Категории за групиране на продуктите в таблицата
PRODUCT_CATEGORIES = [
    ("Млечни продукти", [
        "мляко", "айран", "кефир", "сирене", "кашкавал", "масло", "сметана",
        "извара", "йогурт", "крема", "кисело",
    ]),
    ("Вафли и сладки", [
        "вафла", "бисквит", "шоколад", "бонбон", "сладко", "халва",
        "локум", "мармалад", "smiles", "топчета",
    ]),
    ("Тахани, ядки и бобови", [
        "тахан", "фъстъчено", "лешник", "бадем", "орех",
        "хумус", "нахут", "леща", "киноа", "боб", "мунг",
    ]),
    ("Зеленчукови и сосове", [
        "домат", "кетчуп", "лютеница", "пюре",
    ]),
    ("Напитки", [
        "сок", "лимонада", "боза", "сироп", "чай",
    ]),
    ("Хляб, тесто и зърнени", [
        "кори", "хляб", "паста", "ориз",
    ]),
    ("Други", [
        "олио", "оцет", "зехтин", "мед", "яйца",
        "претцел", "солет", "крекер", "соленки",
    ]),
]


def categorize_product(name):
    """Определя категорията на продукт по име. Връща (индекс, име на категория)."""
    name_lower = name.lower()
    # Приоритетни пренасочвания (решават конфликти между категории)
    for override_kw, override_cat in CATEGORY_OVERRIDES:
        if override_kw in name_lower:
            for idx, (cat_name, _) in enumerate(PRODUCT_CATEGORIES):
                if cat_name == override_cat:
                    return (idx, cat_name)
    for idx, (cat_name, keywords) in enumerate(PRODUCT_CATEGORIES):
        for kw in keywords:
            if kw in name_lower:
                return (idx, cat_name)
    return (len(PRODUCT_CATEGORIES), "Други")


# Продукти на Кашон страницата, които не са Harmonica бранд
KASHON_BRAND_BLACKLIST = [
    "черноморски улов",
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
# RETRY DECORATOR
# =============================================================================

def retry_async(max_retries=3, backoff_base=2):
    """Декоратор за автоматичен retry при мрежови грешки."""
    # Грешки, които заслужават retry (мрежови проблеми)
    RETRYABLE = (ConnectionError, TimeoutError, OSError)

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except RETRYABLE as e:
                    last_error = e
                    if attempt < max_retries:
                        wait = backoff_base ** attempt
                        logger.warning(
                            f"Retry {attempt+1}/{max_retries} за {func.__name__} "
                            f"след {wait}s: {str(e)[:60]}"
                        )
                        await asyncio.sleep(wait)
                except Exception as e:
                    # Програмни грешки не се retry-ват
                    logger.error(f"{func.__name__}: {e}")
                    return {"success": False, "error": str(e)}
            logger.error(f"Всички {max_retries} retry-а неуспешни за {func.__name__}: {last_error}")
            return {"success": False, "error": str(last_error)}
        return wrapper
    return decorator


# =============================================================================
# UTILITY FUNCTIONS — споделени между всички extractors
# =============================================================================

# Ценови граници
PRICE_RANGE_EUR = (0.20, 100)
PRICE_RANGE_BGN = (0.40, 200)


def extract_eur_price(text):
    """Извлича EUR цена от текст. Поддържа формати: 2.50€, 2,50 €, 2.5€"""
    # Опит 1: стандартен формат с 2 десетични
    match = re.search(r'(\d+)[,.](\d{1,2})\s*€', text)
    if match:
        try:
            decimals = match.group(2).ljust(2, '0')  # "5" -> "50"
            price = float(f"{match.group(1)}.{decimals}")
            if PRICE_RANGE_EUR[0] <= price <= PRICE_RANGE_EUR[1]:
                return round(price, 2)
        except ValueError:
            logger.debug(f"EUR parse error: {match.group()}")
    # Опит 2: формат €2.50 (валута отпред)
    match = re.search(r'€\s*(\d+)[,.](\d{1,2})', text)
    if match:
        try:
            decimals = match.group(2).ljust(2, '0')
            price = float(f"{match.group(1)}.{decimals}")
            if PRICE_RANGE_EUR[0] <= price <= PRICE_RANGE_EUR[1]:
                return round(price, 2)
        except ValueError:
            logger.debug(f"EUR parse error: {match.group()}")
    return None


def extract_bgn_price(text):
    """Извлича BGN цена от текст. Поддържа формати: 2.50лв, 2,50 лв, 2.5лв"""
    match = re.search(r'(\d+)[,.](\d{1,2})\s*лв', text)
    if match:
        try:
            decimals = match.group(2).ljust(2, '0')
            price = float(f"{match.group(1)}.{decimals}")
            if PRICE_RANGE_BGN[0] <= price <= PRICE_RANGE_BGN[1]:
                return round(price, 2)
        except ValueError:
            logger.debug(f"BGN parse error: {match.group()}")
    return None


def extract_price_fallback(text):
    """Извлича цена без валутен символ. Връща (price, 'BGN') или None."""
    match = re.search(r'(?:^|\s)(\d+)[,.](\d{2})(?:\s|$)', text)
    if match:
        try:
            price = float(f"{match.group(1)}.{match.group(2)}")
            if PRICE_RANGE_BGN[0] <= price <= PRICE_RANGE_BGN[1]:
                return round(price, 2)
        except ValueError:
            pass
    return None


def clean_product_name(name):
    """Почиства име на продукт от markdown, URL-и, bold и префикси."""
    name = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'\1', name)   # [text](url) -> text
    name = re.sub(r'!\[[^\]]*\]\([^\)]*\)', '', name)        # ![alt](url) -> ""
    name = re.sub(r'https?://[^\s]+', '', name)               # URL-и
    name = re.sub(r'\*\*([^\*]+)\*\*', r'\1', name)           # **bold** -> bold
    name = re.sub(r'^\s*[\-\*\#\|\>]+\s*', '', name)          # Markdown префикси
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def deduplicate_check(name, seen_set, key_length=30):
    """Проверява за дубликат. Връща True ако е дубликат (вече видян)."""
    key = name.lower()[:key_length]
    if key in seen_set:
        return True
    seen_set.add(key)
    return False


# =============================================================================
# KASHON EXTRACTION
# =============================================================================

def extract_kashon_products(markdown):
    """Извлича продукти от Кашон. Формат: [Име](URL) с цени наблизо."""
    products = []
    seen = set()

    pattern = r'\[([^\]]{5,80})\]\(https://kashonharmonica\.bg/bg/products/([^\)]+)\)'

    for match in re.finditer(pattern, markdown):
        name = match.group(1).strip()

        if name.startswith('!') or 'logo' in name.lower():
            continue
        if len(re.findall(r'[а-яА-Яa-zA-Z]', name)) < 3:
            continue
        if deduplicate_check(name, seen):
            continue
        if not is_food_product(name):
            continue
        if any(bl in name.lower() for bl in KASHON_BRAND_BLACKLIST):
            continue

        idx = match.end()
        context = markdown[idx:idx+300]

        eur = extract_eur_price(context)
        bgn = extract_bgn_price(context)

        if not eur and bgn:
            eur = round(bgn / EUR_BGN_RATE, 2)

        if eur or bgn:
            products.append({"name": name, "eur": eur, "bgn": bgn})

    return products


# =============================================================================
# EBAG EXTRACTION
# =============================================================================

def extract_ebag_products(markdown):
    """Извлича продукти от eBag. Два формата: image links + title pattern."""
    products = []
    seen = set()

    img_pattern = r'\[!\[([^\]]+)\]\([^\)]+\)\]\([^\)]+\)'

    for match in re.finditer(img_pattern, markdown):
        name = match.group(1).strip()

        if len(name) < 5 or 'flag' in name.lower():
            continue
        if not is_harmonica_product(name):
            continue
        if deduplicate_check(name, seen):
            continue

        idx = match.start()
        context = markdown[max(0, idx-50):idx+500]

        eur = extract_eur_price(context)
        bgn = extract_bgn_price(context)

        if eur or bgn:
            products.append({"name": name, "eur": eur, "bgn": bgn})

    title_pattern = r'###\s*\[\s*([^\]]+?)\s+Годно до:[^\]]*?(\d+[,\.]\d{2})\s*€[^\]]*?(\d+[,\.]\d{2})\s*лв'

    for match in re.finditer(title_pattern, markdown):
        name = match.group(1).strip()

        if len(name) < 5 or not is_harmonica_product(name):
            continue

        name_key = name.lower()[:30]
        if name_key in seen:
            continue

        try:
            eur = float(match.group(2).replace(",", "."))
            bgn = float(match.group(3).replace(",", "."))

            if 0.20 <= eur <= 100 and 0.50 <= bgn <= 200:
                seen.add(name_key)
                products.append({"name": name, "eur": round(eur, 2), "bgn": round(bgn, 2)})
        except ValueError:
            pass

    return products


# =============================================================================
# BALEV EXTRACTION
# =============================================================================

def extract_balev_products(markdown):
    """Извлича продукти от Balev. Формат: редове с грамаж + контекстни цени."""
    products = []
    seen = set()

    lines = markdown.split('\n')

    for i, line in enumerate(lines):
        line = line.strip()

        if not re.search(r'\d+\s*(?:г|мл|ml|g)\b', line, re.IGNORECASE):
            continue

        name = clean_product_name(line)

        if len(name) < 5 or len(name) > 80:
            continue
        if len(re.findall(r'[а-яА-Яa-zA-Z]', name)) < 3:
            continue

        if not (is_harmonica_product(name) or 'harmonica' in markdown[max(0,i-5):i+5].lower()):
            context_lines = '\n'.join(lines[max(0,i-3):i+3])
            if not ('harmonica' in context_lines.lower() or 'хармоника' in context_lines.lower()):
                continue

        if deduplicate_check(name, seen):
            continue
        if not is_food_product(name):
            continue

        context = '\n'.join(lines[max(0, i - 3):i + 10])
        eur = extract_eur_price(context)
        bgn = extract_bgn_price(context)

        if not bgn and not eur:
            bgn = extract_price_fallback(context)

        if bgn and not eur:
            eur = round(bgn / EUR_BGN_RATE, 2)

        if eur or bgn:
            products.append({"name": name, "eur": eur, "bgn": bgn})

    return products


# =============================================================================
# GENERIC EXTRACTION — универсален fallback за нови магазини
# =============================================================================

def _extract_generic_products(markdown, brand_page=False):
    """
    Универсален fallback extractor. Работи с всякакъв markdown.

    Стратегия:
    1. Разделя markdown на блокове (двоен нов ред)
    2. Търси блокове с BGN цена (X,XX лв)
    3. Извлича най-подходящия текст като име на продукт
    4. Ако brand_page=True, не проверява за "harmonica" в името
    5. Ако block-based подход извлече < 3 продукта, пробва line-by-line
    """
    products = _extract_generic_block_based(markdown, brand_page)

    # Ако block-based намери малко, пробваме line-by-line (като Metro)
    if len(products) < 3:
        line_products = _extract_generic_line_by_line(markdown, brand_page)
        if len(line_products) > len(products):
            products = line_products

    return products


def _extract_generic_block_based(markdown, brand_page=False):
    """Block-based extraction: разделя по двоен нов ред."""
    products = []
    seen = set()

    blocks = re.split(r'\n{2,}', markdown)

    for block in blocks:
        if not brand_page and not is_harmonica_product(block):
            continue

        bgn = extract_bgn_price(block)
        eur = extract_eur_price(block)
        if not bgn and not eur:
            bgn = extract_price_fallback(block)
        if not bgn and not eur:
            continue

        if bgn and not eur:
            eur = round(bgn / EUR_BGN_RATE, 2)

        name = None

        link_match = re.search(r'(?<!!)\[([^\]]{5,100})\]\([^\)]+\)', block)
        if link_match:
            candidate = link_match.group(1).strip()
            if len(candidate) > 5 and is_food_product(candidate):
                name = candidate

        if not name:
            heading_match = re.search(r'#+\s*(.{5,80})', block)
            if heading_match:
                candidate = heading_match.group(1).strip()
                if is_food_product(candidate):
                    name = candidate

        if not name:
            for line in block.split('\n'):
                line = clean_product_name(line)
                if (len(line) > 10 and
                        len(re.findall(r'[а-яА-Яa-zA-Z]', line)) >= 3 and
                        is_food_product(line)):
                    name = line
                    break

        if not name:
            continue
        if deduplicate_check(name, seen):
            continue

        products.append({"name": name, "eur": eur, "bgn": bgn})

    return products


def _extract_generic_line_by_line(markdown, brand_page=False):
    """Line-by-line extraction: сканира ред по ред (за сайтове без двойни нови редове)."""
    products = []
    seen = set()
    lines = markdown.split('\n')

    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if not line_stripped or len(line_stripped) < 5:
            continue

        name = None

        # Опит 1: Link текст
        link_match = re.search(r'(?<!!)\[([^\]]{5,120})\]\(([^\)]+)\)', line_stripped)
        if link_match:
            candidate = link_match.group(1).strip()
            if is_food_product(candidate) and len(candidate) >= 8:
                name = candidate
        else:
            # Опит 2: Текстов ред с грамаж (признак за продукт)
            if re.search(r'\d+\s*(?:г|мл|ml|g|kg|кг|л)\b', line_stripped, re.IGNORECASE):
                candidate = clean_product_name(line_stripped)
                if is_food_product(candidate) and 8 <= len(candidate) <= 150:
                    name = candidate

        if not name:
            continue

        # Проверка за harmonica (освен при brand_page)
        if not brand_page:
            if not is_harmonica_product(name):
                context_lines = '\n'.join(lines[max(0, i - 5):i + 5])
                if not is_harmonica_product(context_lines):
                    continue

        if deduplicate_check(name, seen):
            continue

        # Търсим цена в контекст ±3 реда (по-тесен за brand pages с гъсти продукти)
        context = '\n'.join(lines[max(0, i - 2):i + 5])
        bgn = extract_bgn_price(context)
        if not bgn:
            bgn = extract_price_fallback(context)
        eur = extract_eur_price(context)

        if bgn or eur:
            if bgn and not eur:
                eur = round(bgn / EUR_BGN_RATE, 2)
            products.append({"name": name, "eur": eur, "bgn": bgn})

    return products


# =============================================================================
# METRO EXTRACTION
# =============================================================================

def extract_metro_products(markdown):
    """
    Извлича продукти от Metro markdown.

    Metro формат: продуктите са line-by-line, често с формат:
    - Линк или текст с име + грамаж
    - Цена X,XX лв на близък ред (понякога на същия ред)
    Блоковете не са разделени с двоен нов ред (generic extractor не работи).
    """
    products = []
    seen = set()

    lines = markdown.split('\n')

    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if not line_stripped:
            continue

        # Търсим линкове с продуктови имена
        link_match = re.search(r'(?<!!)\[([^\]]{5,120})\]\(([^\)]+)\)', line_stripped)
        name = None

        if link_match:
            candidate = link_match.group(1).strip()
            if is_food_product(candidate) and len(candidate) >= 8:
                name = candidate
        else:
            # Пробваме текстов ред с грамаж
            if re.search(r'\d+\s*(?:г|мл|ml|g)\b', line_stripped, re.IGNORECASE):
                candidate = clean_product_name(line_stripped)
                if is_food_product(candidate) and 8 <= len(candidate) <= 120:
                    name = candidate

        if not name:
            continue

        if not is_harmonica_product(name):
            context_lines = '\n'.join(lines[max(0, i - 5):i + 5])
            if 'harmonica' not in context_lines.lower() and 'хармоника' not in context_lines.lower():
                continue

        if deduplicate_check(name, seen):
            continue

        context = '\n'.join(lines[max(0, i - 3):i + 10])
        bgn = extract_bgn_price(context)
        if not bgn:
            bgn = extract_price_fallback(context)
        eur = extract_eur_price(context)

        if bgn or eur:
            if bgn and not eur:
                eur = round(bgn / EUR_BGN_RATE, 2)
            products.append({"name": name, "eur": eur, "bgn": bgn})

    return products


# =============================================================================
# T-MARKET EXTRACTION
# =============================================================================

def extract_tmarket_products(markdown, html_text=None, brand_page=True):
    """
    Извлича Harmonica продукти от T-Market Online.

    T-Market vendor page: tmarketonline.bg/vendor/harmonica-1881705916
    На vendor page всички продукти са Harmonica → skip harmonica name check.
    Цени в BGN.
    """
    products = []
    seen = set()

    # Pattern 1: Всички links с продуктови имена
    link_pattern = r'\[([^\]]{5,120})\]\(((?:https?://[^\)]+|/[^\)]+))\)'
    for match in re.finditer(link_pattern, markdown):
        name = match.group(1).strip()

        if name.startswith('!') or 'logo' in name.lower():
            continue
        if len(re.findall(r'[а-яА-Яa-zA-Z]', name)) < 3:
            continue
        if not brand_page and not is_harmonica_product(name):
            continue
        if not is_food_product(name):
            continue

        name_key = name.lower()[:30]
        if name_key in seen:
            continue

        idx = match.end()
        context = markdown[max(0, idx - 150):idx + 400]

        bgn = extract_bgn_price(context)
        eur = extract_eur_price(context)

        if bgn and not eur:
            eur = round(bgn / EUR_BGN_RATE, 2)

        if bgn or eur:
            seen.add(name_key)
            products.append({"name": name, "eur": eur, "bgn": bgn})

    # Pattern 2: Generic text blocks + BS4 fallback
    if not products:
        products = _extract_generic_products(markdown, brand_page=brand_page)

    if BS4_AVAILABLE and html_text and not products:
        soup = BeautifulSoup(html_text, 'html.parser')
        for item in soup.select('.product-card, .product-item, .product, [class*=product]'):
            text = item.get_text(' ', strip=True)
            if not brand_page and not is_harmonica_product(text):
                continue
            name_el = item.select_one('h2, h3, h4, a.product-name, [class*=title], [class*=name]')
            if not name_el:
                for link in item.find_all('a', href=True):
                    link_text = link.get_text(strip=True)
                    if len(link_text) > 10:
                        name_el = link
                        break
            if not name_el:
                continue
            product_name = name_el.get_text(strip=True)
            name_key = product_name.lower()[:30]
            if name_key in seen or not is_food_product(product_name):
                continue
            bgn = extract_bgn_price(text)
            eur = extract_eur_price(text)
            if bgn and not eur:
                eur = round(bgn / EUR_BGN_RATE, 2)
            if bgn or eur:
                seen.add(name_key)
                products.append({"name": product_name, "eur": eur, "bgn": bgn})

    if not products:
        logger.warning(f"T-Market: 0 продукта, markdown len={len(markdown)}, "
                       f"preview: {markdown[:500]}")
    else:
        logger.info(f"T-Market: {len(products)} продукта извлечени")
    return products


# =============================================================================
# LILLY DROGERIE EXTRACTION (EXP-003) — BeautifulSoup с regex fallback
# =============================================================================

def extract_lilly_products(markdown_text, html_text=None):
    """
    Извлича Harmonica продукти от Lilly Drogerie brand page.

    Предпочита BeautifulSoup + HTML за по-стабилно парсване.
    Ако BS4 не е наличен или HTML липсва, използва regex + markdown.

    Връща list of dicts с допълнително поле 'in_stock' (bool).
    """
    products = []
    if BS4_AVAILABLE and html_text:
        products = _extract_lilly_bs4(html_text)
    if not products:
        products = _extract_lilly_regex(markdown_text)
    if not products:
        # Допълнителен debug: какво съдържа HTML-а
        html_preview = ""
        if html_text:
            soup = BeautifulSoup(html_text, 'html.parser') if BS4_AVAILABLE else None
            if soup:
                # Проверяваме за Harmonica ключова дума в HTML
                harmonica_count = html_text.upper().count('HARMONICA')
                # Проверяваме за типични Magento product selectors
                selectors = ['.product-item', '.product-items', 'ol.products',
                             '.products-grid', '.category-products', '[data-role=product]']
                found_selectors = [s for s in selectors if soup.select_one(s)]
                html_preview = (f"harmonica_refs={harmonica_count}, "
                               f"selectors={found_selectors or 'NONE'}, "
                               f"title={soup.title.string if soup.title else 'N/A'}")
        logger.warning(f"Lilly: 0 продукта, markdown len={len(markdown_text)}, "
                       f"html len={len(html_text) if html_text else 0}, "
                       f"{html_preview}")
    return products


def _find_product_container(element, max_levels=6):
    """
    Вървим нагоре от element до намерим контейнер с цена.
    Връща контейнер или None.
    """
    current = element
    for _ in range(max_levels):
        parent = current.parent
        if not parent or parent.name in ('body', 'html', '[document]'):
            break
        if parent.name in ('header', 'footer', 'nav', 'head'):
            return None

        text = parent.get_text(' ', strip=True)
        if len(text) > 3000:
            cur_text = current.get_text(' ', strip=True)
            return current if re.search(r'\d+[.,]\d{2}', cur_text) else None

        if re.search(r'\d+[.,]\d{2}', text):
            if len(text) < 500:
                current = parent
                continue
            return parent

        current = parent

    if current and current.name not in ('body', 'html', '[document]'):
        text = current.get_text(' ', strip=True)
        if re.search(r'\d+[.,]\d{2}', text) and len(text) < 3000:
            return current
    return None


def _extract_lilly_bs4(html_text):
    """
    Извлича Lilly продукти с BeautifulSoup.

    Lilly използва Hyvä Theme (Alpine.js + Tailwind CSS) —
    стандартните Magento CSS selectors не съществуват.

    Стратегии:
    1. JSON-LD structured data (@type: Product / ItemList)
    2. Елементи с HARMONICA в text, title, alt атрибути
    3. Legacy Magento CSS selectors (fallback)
    """
    products = []
    seen = set()
    soup = BeautifulSoup(html_text, 'html.parser')

    # Стратегия 1: JSON-LD structured data
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string or '')
            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                if data.get('@type') == 'ItemList':
                    items = data.get('itemListElement', [])
                elif data.get('@type') == 'Product':
                    items = [data]
                elif 'itemListElement' in data:
                    items = data['itemListElement']

            for item in items:
                product = item.get('item', item) if isinstance(item, dict) else {}
                name = product.get('name', '')
                if not name:
                    continue

                price = None
                offers = product.get('offers', {})
                if isinstance(offers, dict):
                    price = offers.get('price')
                elif isinstance(offers, list) and offers:
                    price = offers[0].get('price')

                if price:
                    price_bgn = round(float(price), 2)
                    price_eur = round(price_bgn / EUR_BGN_RATE, 2)
                    name_key = name.lower()[:40]
                    if name_key not in seen:
                        seen.add(name_key)
                        in_stock = True
                        if isinstance(offers, dict):
                            avail = offers.get('availability', '')
                            in_stock = 'OutOfStock' not in avail
                        products.append({
                            'name': name,
                            'eur': price_eur,
                            'bgn': price_bgn,
                            'in_stock': in_stock,
                        })
        except (json.JSONDecodeError, ValueError, TypeError):
            continue

    if products:
        logger.info(f"Lilly BS4: {len(products)} продукта от JSON-LD")
        return products

    # Стратегия 2: Намиране на product containers
    product_containers = []
    found_container_ids = set()

    # 2a: <a> tags с HARMONICA в text content
    for link in soup.find_all('a', href=True):
        link_text = link.get_text(strip=True)
        href = link.get('href', '')
        if not link_text or 'harmonica' not in link_text.lower():
            continue
        if len(link_text) < 5:
            continue
        if any(x in href.lower() for x in ['/media/', '.jpg', '.png', '.svg', '.css', '.js']):
            continue
        container = _find_product_container(link)
        if container:
            cid = id(container)
            if cid not in found_container_ids:
                found_container_ids.add(cid)
                product_containers.append(container)

    # 2b: <a> и <img> с HARMONICA в title/alt атрибути
    for attr_name in ['title', 'alt']:
        for el in soup.find_all(attrs={attr_name: re.compile(r'harmonica', re.IGNORECASE)}):
            if el.find_parent(['header', 'nav', 'footer', 'head']):
                continue
            container = _find_product_container(el)
            if container:
                cid = id(container)
                if cid not in found_container_ids:
                    found_container_ids.add(cid)
                    product_containers.append(container)

    # 2c: Text nodes с HARMONICA (за Hyvä span/div)
    for text_node in soup.find_all(string=re.compile(r'harmonica', re.IGNORECASE)):
        parent = text_node.find_parent()
        if not parent:
            continue
        if parent.name in ('script', 'style', 'meta', 'title', 'head', 'noscript'):
            continue
        if parent.find_parent(['header', 'nav', 'footer', 'head']):
            continue
        container = _find_product_container(parent)
        if container:
            cid = id(container)
            if cid not in found_container_ids:
                found_container_ids.add(cid)
                product_containers.append(container)

    logger.info(f"Lilly BS4: {len(product_containers)} потенциални контейнери")

    for container in product_containers:
        text = container.get_text(' ', strip=True)

        product_name = None

        # Опит 1: <a> с HARMONICA text content
        for link in container.find_all('a', href=True):
            lt = link.get_text(strip=True)
            href = link.get('href', '')
            if lt and 'harmonica' in lt.lower() and len(lt) > 10:
                if not any(x in href.lower() for x in ['/media/', '.jpg', '.png', '.svg']):
                    product_name = lt
                    break

        # Опит 2: <a title> с HARMONICA
        if not product_name:
            for link in container.find_all('a', attrs={'title': True}):
                title = link.get('title', '')
                if 'harmonica' in title.lower() and len(title) > 10:
                    product_name = title
                    break

        # Опит 3: <img alt> с HARMONICA
        if not product_name:
            for img in container.find_all('img', attrs={'alt': True}):
                alt = img.get('alt', '')
                if 'harmonica' in alt.lower() and len(alt) > 10:
                    product_name = alt
                    break

        # Опит 4: <span>, <div>, <h2-h5>, <strong>, <p> с HARMONICA
        if not product_name:
            for tag in container.find_all(['h2', 'h3', 'h4', 'h5', 'span', 'strong', 'p', 'div']):
                tag_text = tag.get_text(strip=True)
                if tag_text and 'harmonica' in tag_text.lower() and 10 < len(tag_text) < 200:
                    if is_food_product(tag_text):
                        product_name = tag_text
                        break

        if not product_name:
            continue

        if any(x in product_name.lower() for x in ['навигация', 'меню', 'cookie', 'продукти на']):
            continue

        name_key = product_name.lower()[:40]
        if name_key in seen:
            continue

        # Цени
        price_bgn = extract_bgn_price(text)
        price_eur = extract_eur_price(text)

        if not price_bgn and not price_eur:
            price_match = re.search(r'(\d+)[,.](\d{2})', text)
            if price_match:
                try:
                    price = float(f"{price_match.group(1)}.{price_match.group(2)}")
                    if 0.50 <= price <= 100:
                        price_bgn = round(price, 2)
                except ValueError:
                    pass

        if price_bgn and not price_eur:
            price_eur = round(price_bgn / EUR_BGN_RATE, 2)

        in_stock = 'изчерпан' not in text.lower()

        if product_name and (price_eur or price_bgn):
            seen.add(name_key)
            products.append({
                'name': product_name,
                'eur': price_eur,
                'bgn': price_bgn,
                'in_stock': in_stock,
            })

    # Стратегия 3: Legacy Magento CSS selectors
    if not products:
        product_items = soup.select(
            '.product-item, .product-item-info, li.item.product, '
            '.products-grid .item, .category-products .item'
        )
        for item in product_items:
            text = item.get_text(' ', strip=True)
            if 'harmonica' not in text.lower():
                continue
            for link in item.find_all('a', href=True):
                lt = link.get_text(strip=True)
                if lt and 'harmonica' in lt.lower() and len(lt) > 5:
                    name_key = lt.lower()[:40]
                    if name_key not in seen:
                        price_bgn = extract_bgn_price(text)
                        price_eur = extract_eur_price(text)
                        if price_bgn or price_eur:
                            seen.add(name_key)
                            products.append({
                                'name': lt,
                                'eur': price_eur,
                                'bgn': price_bgn,
                                'in_stock': 'изчерпан' not in text.lower(),
                            })
                    break

    logger.info(f"Lilly BS4: {len(products)} продукта извлечени")
    return products


def _extract_lilly_regex(markdown_text):
    """Извлича Lilly продукти с regex (fallback)."""
    products = []
    product_blocks = re.split(r'\n\s*\*\s+', markdown_text)

    for block in product_blocks:
        if 'lillydrogerie.bg' not in block:
            continue

        name_match = re.search(
            r'(?<!!)\[([^\]]*HARMONICA[^\]]*)\]\(https://lillydrogerie\.bg/(?!media/)([^\s\)]+)',
            block
        )
        if not name_match:
            continue

        product_name = name_match.group(1).strip()
        product_slug = name_match.group(2).strip('" ')
        product_url = f"https://lillydrogerie.bg/{product_slug}"

        eur_match = re.search(r'(\d+[.,]\d{2})\s*€', block)
        price_eur = float(eur_match.group(1).replace(',', '.')) if eur_match else None

        bgn_match = re.search(r'(\d+[.,]\d{2})\s*лв', block)
        price_bgn = float(bgn_match.group(1).replace(',', '.')) if bgn_match else None

        in_stock = 'Изчерпан' not in block

        if product_name and (price_eur or price_bgn):
            products.append({
                'name': product_name,
                'eur': price_eur,
                'bgn': price_bgn,
                'in_stock': in_stock,
                'url': product_url,
            })

    logger.info(f"Lilly regex: {len(products)} продукта извлечени")
    return products


# =============================================================================
# DM BULGARIA EXTRACTION — CapSolver за anti-bot bypass
# =============================================================================

def extract_dm_products(markdown_text, html_text=None):
    """
    Извлича Harmonica продукти от DM Bulgaria.

    DM.bg показва продукти в search резултати с имена и цени.
    Предпочита BS4 + HTML ако е наличен, иначе regex + markdown.
    """
    if BS4_AVAILABLE and html_text:
        return _extract_dm_bs4(html_text)
    return _extract_dm_regex(markdown_text)


def _extract_dm_bs4(html_text):
    """Извлича DM продукти с BeautifulSoup."""
    products = []
    seen = set()
    soup = BeautifulSoup(html_text, 'html.parser')

    # DM.bg типично използва product cards/tiles в search results
    product_items = soup.select(
        '[data-testid="product-tile"], .product-tile, .product-card, '
        '.search-result-item, .product-item, article.product'
    )

    # Fallback: търсим всички елементи с текст "Harmonica"
    if not product_items:
        for el in soup.find_all(['div', 'li', 'article', 'section']):
            text = el.get_text(strip=True)
            if ('harmonica' in text.lower() or 'хармоника' in text.lower()):
                # Избягваме parent контейнери (> 2000 chars = вероятно wrapper)
                if len(text) < 2000 and el not in product_items:
                    product_items.append(el)

    for item in product_items:
        text = item.get_text(' ', strip=True)
        if not ('harmonica' in text.lower() or 'хармоника' in text.lower()):
            continue

        # Име на продукт — от заглавен link или heading
        product_name = None
        for tag in item.find_all(['a', 'h2', 'h3', 'h4', 'span', 'p']):
            tag_text = tag.get_text(strip=True)
            if (tag_text and len(tag_text) > 10
                    and ('harmonica' in tag_text.lower() or 'хармоника' in tag_text.lower())):
                product_name = tag_text
                break

        if not product_name:
            continue

        name_key = product_name.lower()[:40]
        if name_key in seen:
            continue

        if not is_food_product(product_name):
            continue

        # Цени — EUR и BGN
        price_eur = extract_eur_price(text)
        price_bgn = extract_bgn_price(text)

        # DM.bg може да показва цена само в лева
        if not price_bgn and not price_eur:
            # Търсим цена без валутен суфикс (напр. "3.99")
            price_match = re.search(r'(\d+)[,.](\d{2})', text)
            if price_match:
                try:
                    price = float(f"{price_match.group(1)}.{price_match.group(2)}")
                    if PRICE_RANGE_BGN[0] <= price <= PRICE_RANGE_BGN[1]:
                        price_bgn = round(price, 2)
                except ValueError:
                    pass

        if product_name and (price_eur or price_bgn):
            seen.add(name_key)
            products.append({
                'name': product_name,
                'eur': price_eur,
                'bgn': price_bgn,
            })

    logger.info(f"DM BS4: {len(products)} продукта извлечени")
    return products


def _extract_dm_regex(markdown_text):
    """Извлича DM продукти с regex (fallback ако BS4 не е наличен)."""
    products = []
    seen = set()

    # Pattern 1: [Product Name](url) с цени наблизо
    link_pattern = r'\[([^\]]*(?:harmonica|хармоника)[^\]]*)\]\([^\)]+\)'
    for match in re.finditer(link_pattern, markdown_text, re.IGNORECASE):
        name = match.group(1).strip()
        if name.startswith('!') or len(name) < 10:
            continue

        name_key = name.lower()[:40]
        if name_key in seen:
            continue
        if not is_food_product(name):
            continue

        idx = match.end()
        context = markdown_text[max(0, idx - 100):idx + 400]

        eur = extract_eur_price(context)
        bgn = extract_bgn_price(context)

        if eur or bgn:
            seen.add(name_key)
            products.append({"name": name, "eur": eur, "bgn": bgn})

    # Pattern 2: Просто текстови блокове с Harmonica + цени
    blocks = re.split(r'\n{2,}', markdown_text)
    for block in blocks:
        if not ('harmonica' in block.lower() or 'хармоника' in block.lower()):
            continue

        # Извличаме потенциално име (първия ред с Harmonica)
        for line in block.split('\n'):
            if 'harmonica' in line.lower() or 'хармоника' in line.lower():
                name = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'\1', line)
                name = re.sub(r'[#*_>|]', '', name).strip()
                if len(name) > 10:
                    name_key = name.lower()[:40]
                    if name_key not in seen and is_food_product(name):
                        eur = extract_eur_price(block)
                        bgn = extract_bgn_price(block)
                        if eur or bgn:
                            seen.add(name_key)
                            products.append({"name": name, "eur": eur, "bgn": bgn})
                    break

    logger.info(f"DM regex: {len(products)} продукта извлечени")
    return products


# =============================================================================
# CAPSOLVER — решаване на Cloudflare Turnstile/Challenge
# =============================================================================

def detect_cloudflare_challenge(html_text):
    """Проверява дали страницата съдържа Cloudflare challenge."""
    if not html_text:
        return False, None

    indicators = [
        'cf-turnstile', 'challenges.cloudflare.com',
        'cf-challenge-running', 'cf_chl_opt',
        'Just a moment', 'Checking your browser',
    ]
    is_challenge = any(ind in html_text for ind in indicators)

    # Извличане на sitekey ако е Turnstile
    sitekey = None
    sitekey_match = re.search(r'data-sitekey=["\']([^"\']+)["\']', html_text)
    if sitekey_match:
        sitekey = sitekey_match.group(1)
    else:
        # Алтернативен pattern от JS
        sitekey_match = re.search(r'sitekey\s*[=:]\s*["\']([0-9x\-]+)["\']', html_text)
        if sitekey_match:
            sitekey = sitekey_match.group(1)

    return is_challenge, sitekey


async def solve_turnstile(website_url, website_key):
    """Решава Cloudflare Turnstile чрез CapSolver API."""
    api_key = os.environ.get('CAPSOLVER_API_KEY')
    if not api_key:
        logger.error("CAPSOLVER_API_KEY не е зададен")
        return None

    capsolver.api_key = api_key

    try:
        logger.info(f"CapSolver: решаване на Turnstile за {website_url}")
        solution = capsolver.solve({
            "type": "AntiTurnstileTaskProxyLess",
            "websiteURL": website_url,
            "websiteKey": website_key,
        })
        token = solution.get("token")
        if token:
            logger.info(f"CapSolver: Turnstile решен успешно (token: {token[:20]}...)")
        return token
    except Exception as e:
        logger.error(f"CapSolver грешка: {e}")
        return None


@retry_async(max_retries=1, backoff_base=5)
async def crawl_with_captcha_solver(crawler, store_key, store_config):
    """
    Краулва сайт с anti-bot защита. Стратегия:
    1. Опит с magic mode (симулира човешко поведение)
    2. Ако има Cloudflare challenge → CapSolver API
    3. Инжектиране на token + повторно зареждане
    """
    store_name = store_config["name"]
    url = store_config["url"]

    logger.info(f"CRAWLING (anti-bot): {store_name}")
    start = time.time()

    # Стъпка 1: Опит с magic mode
    magic_config = CrawlerRunConfig(
        magic=True,
        page_timeout=60000,
        remove_overlay_elements=True,
        cache_mode=CacheMode.BYPASS,
    )

    result = await crawler.arun(url=url, config=magic_config)

    # Проверка за DNS / мрежови грешки преди всичко
    if not result.success:
        error_msg = str(getattr(result, 'error_message', '') or '')
        elapsed = time.time() - start
        if 'ERR_NAME_NOT_RESOLVED' in error_msg:
            logger.warning(f"{store_name}: DNS грешка {elapsed:.1f}s — домейнът не е достъпен")
            return {"success": False, "error": "DNS error: domain not resolved"}
        if any(e in error_msg for e in ('ERR_CONNECTION_REFUSED', 'ERR_CONNECTION_TIMED_OUT',
                                        'ERR_NETWORK_CHANGED', 'net::ERR_')):
            logger.warning(f"{store_name}: Мрежова грешка {elapsed:.1f}s — {error_msg[:120]}")
            return {"success": False, "error": f"Network error: {error_msg[:120]}"}

    # Проверка дали magic mode е достатъчен
    if result.success and result.markdown and len(result.markdown) > 500:
        # Проверяваме дали съдържанието е реално (не Cloudflare challenge page)
        html = getattr(result, 'html', '') or ''
        is_challenge, _ = detect_cloudflare_challenge(html)
        if not is_challenge:
            elapsed = time.time() - start
            logger.info(f"{store_name}: OK (magic mode) {elapsed:.1f}s, {len(result.markdown)} chars")
            return {
                "success": True,
                "store_key": store_key,
                "elapsed": elapsed,
                "markdown": result.markdown,
                "html": html,
                "method": "magic",
            }

    # Стъпка 2: Cloudflare challenge детектиран — CapSolver
    html = getattr(result, 'html', '') or ''
    is_challenge, sitekey = detect_cloudflare_challenge(html)

    if not is_challenge:
        # Не е Cloudflare — може би друг тип блокировка
        elapsed = time.time() - start
        logger.warning(f"{store_name}: Блокиран (не е Cloudflare) {elapsed:.1f}s")
        logger.warning(f"  HTML preview: {html[:200]}")
        return {"success": False, "error": f"Blocked by non-Cloudflare protection"}

    if not CAPSOLVER_AVAILABLE:
        return {"success": False, "error": "CapSolver not installed"}

    if not sitekey:
        logger.warning(f"{store_name}: Cloudflare challenge без sitekey — опит с AntiCloudflareTask")
        # За Cloudflare Challenge (5s check) без Turnstile widget
        # Пробваме по-агресивен подход: повторно зареждане след кратко чакане
        wait_config = CrawlerRunConfig(
            magic=True,
            page_timeout=90000,
            remove_overlay_elements=True,
            cache_mode=CacheMode.BYPASS,
            wait_for="js:() => !document.querySelector('#cf-challenge-running')",
        )
        result = await crawler.arun(url=url, config=wait_config)
        html = getattr(result, 'html', '') or ''
        is_still_challenge, sitekey = detect_cloudflare_challenge(html)

        if not is_still_challenge and result.success and len(result.markdown or '') > 500:
            elapsed = time.time() - start
            logger.info(f"{store_name}: OK (wait bypass) {elapsed:.1f}s")
            return {
                "success": True,
                "store_key": store_key,
                "elapsed": elapsed,
                "markdown": result.markdown,
                "html": html,
                "method": "wait_bypass",
            }

        if not sitekey:
            return {"success": False, "error": "Cloudflare challenge: sitekey not found"}

    # Стъпка 3: CapSolver Turnstile
    token = await solve_turnstile(url, sitekey)
    if not token:
        return {"success": False, "error": "CapSolver failed to solve Turnstile"}

    # Стъпка 4: Инжектиране на token
    inject_js = f"""
    (function() {{
        var input = document.querySelector('input[name="cf-turnstile-response"]');
        if (input) {{
            input.value = '{token}';
        }}
        var hidden = document.querySelector('[name="cf-turnstile-response"]');
        if (hidden) {{
            hidden.value = '{token}';
        }}
        // Опит да submit-нем формата
        var form = document.querySelector('form');
        if (form) form.submit();
        // Или кликнем бутон
        var btn = document.querySelector('button[type="submit"], input[type="submit"]');
        if (btn) btn.click();
    }})();
    """

    inject_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        js_code=inject_js,
        js_only=True,
        page_timeout=30000,
        wait_for="js:() => document.querySelectorAll('[class*=product]').length > 0",
    )

    result = await crawler.arun(url=url, config=inject_config)
    elapsed = time.time() - start

    if result.success and result.markdown and len(result.markdown) > 300:
        logger.info(f"{store_name}: OK (CapSolver) {elapsed:.1f}s, {len(result.markdown)} chars")
        return {
            "success": True,
            "store_key": store_key,
            "elapsed": elapsed,
            "markdown": result.markdown,
            "html": getattr(result, 'html', None),
            "method": "capsolver",
        }

    logger.error(f"{store_name}: FAILED след CapSolver inject {elapsed:.1f}s")
    return {"success": False, "error": "CapSolver token injected but page didn't load"}


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


def _fetch_dm_via_firecrawl(query="harmonica"):
    """
    Firecrawl: рендерира DM.bg search page с headless browser.
    DM.bg има силна Cloudflare защита, която блокира proxy + curl_cffi.
    Firecrawl използва собствена инфраструктура и може да bypass-не.
    Синхронна функция — ще се изпълнява в thread pool.
    """
    if not FIRECRAWL_AVAILABLE or not FIRECRAWL_API_KEY:
        return None

    start = time.time()
    url = f"https://www.dm-drogeriemarkt.bg/search?query={query}&searchType=product"

    try:
        app = FirecrawlApp(api_key=FIRECRAWL_API_KEY)

        # Firecrawl scrape с wait за JS rendering
        result = app.scrape_url(
            url,
            params={
                "formats": ["markdown", "html"],
                "actions": [
                    {"type": "wait", "milliseconds": 5000},
                    {"type": "scroll", "direction": "down"},
                    {"type": "wait", "milliseconds": 2000},
                    {"type": "scrape"},
                ],
                "timeout": 60000,
            },
        )
        elapsed = time.time() - start

        markdown = ""
        html = ""
        if isinstance(result, dict):
            markdown = result.get("markdown", "")
            html = result.get("html", "")
        elif hasattr(result, "markdown"):
            markdown = result.markdown or ""
            html = getattr(result, "html", "") or ""

        if not markdown and not html:
            logger.info(f"DM Firecrawl: празен резултат ({elapsed:.1f}s)")
            return None

        # Парсване на продукти от HTML/markdown
        products = []
        if html:
            products = extract_dm_from_curl_html(html)
        if not products and markdown:
            products = extract_dm_products(markdown, html_text=html)

        logger.info(f"DM Firecrawl: {len(products)} продукта ({elapsed:.1f}s)")

        if products:
            return {
                "success": True,
                "method": "firecrawl",
                "products": products,
                "elapsed": elapsed,
                "html": html,
            }

        # Firecrawl успя, но не можахме да парснем продукти
        harmonica_refs = len(re.findall(r'(?i)harmonica|хармоника', markdown))
        logger.info(f"DM Firecrawl: 0 парсирани, {harmonica_refs} refs в markdown ({elapsed:.1f}s)")
        return {
            "success": True,
            "method": "firecrawl",
            "products": [],
            "html": html,
            "markdown": markdown,
            "elapsed": elapsed,
        }

    except Exception as e:
        elapsed = time.time() - start
        logger.warning(f"DM Firecrawl грешка: {e} ({elapsed:.1f}s)")
        return None


# =============================================================================
# RANDI FIRECRAWL FETCH
# =============================================================================

def _fetch_randi_via_firecrawl():
    """
    Firecrawl: рендерира Randi.bg search page с headless browser.
    Randi.bg зарежда продуктите с JS — Crawl4AI не улавя всичко.
    Синхронна функция — ще се изпълнява в thread pool.
    """
    if not FIRECRAWL_AVAILABLE or not FIRECRAWL_API_KEY:
        return None

    start = time.time()
    url = "https://randi.bg/search?search=harmonica"

    try:
        app = FirecrawlApp(api_key=FIRECRAWL_API_KEY)

        result = app.scrape_url(
            url,
            params={
                "formats": ["markdown"],
                "actions": [
                    {"type": "wait", "milliseconds": 3000},
                    {"type": "scroll", "direction": "down", "amount": 8},
                    {"type": "wait", "milliseconds": 2000},
                    {"type": "scrape"},
                ],
                "timeout": 60000,
            },
        )
        elapsed = time.time() - start

        markdown = ""
        if isinstance(result, dict):
            markdown = result.get("markdown", "")
        elif hasattr(result, "markdown"):
            markdown = result.markdown or ""

        if not markdown:
            logger.info(f"Randi Firecrawl: празен резултат ({elapsed:.1f}s)")
            return None

        products = extract_randi_products(markdown)
        logger.info(f"Randi Firecrawl: {len(products)} продукта ({elapsed:.1f}s)")

        if products:
            return {
                "success": True,
                "method": "firecrawl",
                "products": products,
                "elapsed": elapsed,
                "markdown": markdown,
            }

        harmonica_refs = len(re.findall(r'(?i)harmonica|хармоника', markdown))
        logger.info(f"Randi Firecrawl: 0 парсирани, {harmonica_refs} refs в markdown ({elapsed:.1f}s)")
        return {
            "success": True,
            "method": "firecrawl",
            "products": [],
            "markdown": markdown,
            "elapsed": elapsed,
        }

    except Exception as e:
        elapsed = time.time() - start
        logger.warning(f"Randi Firecrawl грешка: {e} ({elapsed:.1f}s)")
        return None


# =============================================================================
# RANDI EXTRACTION
# =============================================================================

def extract_randi_products(markdown):
    """
    Извлича продукти от Randi.bg markdown.

    Randi формат: продуктовите блокове съдържат линк с име + цена X,XX лв
    на отделен ред. Блоковете са разделени визуално.
    """
    products = []
    seen = set()

    lines = markdown.split('\n')

    for i, line in enumerate(lines):
        line_stripped = line.strip()

        # Търсим линкове с продуктови имена
        link_match = re.search(r'(?<!!)\[([^\]]{5,120})\]\(([^\)]+)\)', line_stripped)
        if not link_match:
            continue

        name = link_match.group(1).strip()

        # Филтрираме навигационни линкове
        if not is_food_product(name):
            continue
        if len(name) < 8:
            continue
        if not is_harmonica_product(name):
            # Проверяваме контекста за harmonica
            context_lines = '\n'.join(lines[max(0, i - 3):i + 5])
            if 'harmonica' not in context_lines.lower() and 'хармоника' not in context_lines.lower():
                continue

        name_key = name.lower()[:30]
        if name_key in seen:
            continue

        # Търсим цена в контекст от ±5 реда
        context = '\n'.join(lines[max(0, i - 3):i + 8])
        bgn = extract_bgn_price(context)
        if not bgn:
            # Опит: цена без "лв" суфикс (напр. "2.99" или "2,99")
            price_match = re.search(r'(\d+)[,.](\d{2})\b', context)
            if price_match:
                try:
                    price = float(f"{price_match.group(1)}.{price_match.group(2)}")
                    if 0.50 <= price <= 100:
                        bgn = round(price, 2)
                except ValueError:
                    pass
        eur = extract_eur_price(context)

        if bgn or eur:
            if bgn and not eur:
                eur = round(bgn / EUR_BGN_RATE, 2)
            seen.add(name_key)
            products.append({"name": name, "eur": eur, "bgn": bgn})

    return products


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
            proxy = PROXY_URL if PROXY_URL else None

            # Стъпка 1: Fetch dm.bg за Algolia config
            logger.info("DM Algolia: извличане на конфигурация от dm.bg...")
            resp = await session.get(
                "https://www.dm-drogeriemarkt.bg/search?query=harmonica&searchType=product",
                proxy=proxy,
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
                        js_resp = await session.get(js_url, proxy=proxy, timeout=15)
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
                proxy=proxy,
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


def extract_dm_from_curl_html(html_text):
    """
    Парсва DM продукти от HTML, получен чрез curl_cffi.
    Използва се когато Algolia API не е наличен, но curl_cffi bypass-ва Cloudflare.
    """
    if not html_text:
        return []
    if BS4_AVAILABLE:
        return _extract_dm_bs4(html_text)
    return []


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
            proxy = PROXY_URL if PROXY_URL else None

            # Опит 1: GraphQL API
            try:
                resp = await session.post(
                    "https://lillydrogerie.bg/graphql",
                    proxy=proxy,
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
                    proxy=proxy,
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
            proxy = PROXY_URL if PROXY_URL else None
            resp = await session.get(
                url,
                proxy=proxy,
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


# =============================================================================
# GLOVO — търсене на Harmonica продукти чрез Firecrawl / API / HTML
# =============================================================================

def _fetch_glovo_via_firecrawl(slug, store_name, query="harmonica"):
    """
    Firecrawl: рендерира Glovo SPA с headless browser, използва actions за
    да взаимодейства с търсачката в магазина и извлича продукти.
    Синхронна функция — ще се изпълнява в thread pool.
    """
    if not FIRECRAWL_AVAILABLE or not FIRECRAWL_API_KEY:
        return None

    start = time.time()
    store_url = f"https://glovoapp.com/bg/bg/sofia/stores/{slug}"

    # JS: намира и фокусира search input в Glovo SPA
    find_search_js = """
    (function() {
        var selectors = [
            'input[type="search"]',
            'input[placeholder*="Търси"]',
            'input[placeholder*="Search"]',
            'input[placeholder*="търси"]',
            '[data-testid*="search"] input',
            '[role="search"] input',
            'input[aria-label*="Search"]',
            'input[aria-label*="Търси"]',
        ];
        for (var i = 0; i < selectors.length; i++) {
            var el = document.querySelector(selectors[i]);
            if (el) { el.click(); el.focus(); return 'found:' + selectors[i]; }
        }
        var btns = document.querySelectorAll('button, [role="button"], a');
        for (var j = 0; j < btns.length; j++) {
            var t = (btns[j].textContent || '').toLowerCase();
            var a = (btns[j].getAttribute('aria-label') || '').toLowerCase();
            if (t.indexOf('search') >= 0 || t.indexOf('търси') >= 0 ||
                a.indexOf('search') >= 0 || a.indexOf('търси') >= 0) {
                btns[j].click();
                return 'clicked-button';
            }
        }
        return 'not-found';
    })()
    """.strip()

    try:
        app = FirecrawlApp(api_key=FIRECRAWL_API_KEY)

        # Подход 1: Actions — взаимодействие с search box на store page
        search_actions = [
            {"type": "wait", "milliseconds": 4000},
            {"type": "executeJavascript", "script": find_search_js},
            {"type": "wait", "milliseconds": 1500},
            {"type": "write", "text": query},
            {"type": "wait", "milliseconds": 1000},
            {"type": "press", "key": "Enter"},
            {"type": "wait", "milliseconds": 5000},
            {"type": "scroll", "direction": "down"},
            {"type": "wait", "milliseconds": 2000},
            {"type": "scrape"},
        ]

        try:
            result = app.scrape_url(
                store_url,
                params={
                    "formats": ["markdown"],
                    "actions": search_actions,
                    "timeout": 60000,
                },
            )
            elapsed = time.time() - start

            if isinstance(result, dict):
                markdown = result.get("markdown", "")
            elif hasattr(result, "markdown"):
                markdown = result.markdown or ""
            else:
                markdown = str(result) if result else ""

            if markdown:
                harmonica_refs = len(re.findall(r'(?i)harmonica|хармоника', markdown))
                logger.info(f"Glovo {store_name}: Firecrawl [search-actions] — "
                            f"{len(markdown)} chars, {harmonica_refs} harmonica refs ({elapsed:.1f}s)")

                if harmonica_refs > 0:
                    products = _parse_glovo_markdown(markdown, store_name, query)
                    if products:
                        return {
                            "success": True,
                            "method": "firecrawl_search_actions",
                            "products": products,
                            "elapsed": elapsed,
                        }
                else:
                    logger.info(f"  preview: {markdown[:300].replace(chr(10), ' ')}")
            else:
                logger.info(f"Glovo {store_name}: Firecrawl [search-actions] — празен markdown ({elapsed:.1f}s)")

        except Exception as e:
            elapsed = time.time() - start
            logger.info(f"Glovo {store_name}: Firecrawl actions грешка: {e} ({elapsed:.1f}s)")

        elapsed = time.time() - start
        logger.info(f"Glovo {store_name}: Firecrawl — 0 продукта ({elapsed:.1f}s)")
        return None

    except Exception as e:
        elapsed = time.time() - start
        logger.warning(f"Glovo {store_name}: Firecrawl грешка: {e} ({elapsed:.1f}s)")
        return None


def _parse_glovo_markdown(markdown, store_name, query):
    """Парсва Firecrawl markdown от Glovo store page за Harmonica продукти."""
    products = []
    seen = set()
    query_lower = query.lower()

    # Pattern 1: Продукт с цена на следващ ред (markdown формат)
    # Примери: "Harmonica Био кисело мляко 2% 400г\n3.29 лв" или "3,29 лв"
    lines = markdown.split('\n')
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if not line_stripped:
            continue

        # Търсим ред с harmonica/хармоника
        if query_lower not in line_stripped.lower() and 'хармоника' not in line_stripped.lower():
            continue

        if not is_food_product(line_stripped):
            continue

        name_key = line_stripped.lower()[:30]
        if name_key in seen:
            continue

        # Търсим цена в текущия ред или следващите 3 реда
        context = '\n'.join(lines[i:i+4])
        bgn = extract_bgn_price(context)
        if not bgn:
            eur_only = extract_eur_price(context)
            if eur_only:
                bgn = round(eur_only * EUR_BGN_RATE, 2)

        if bgn and bgn > 0:
            eur = round(bgn / EUR_BGN_RATE, 2)
            # Чистим името
            name = re.sub(r'\s*\d+[.,]\d{2}\s*(?:лв|bgn|eur|€)?\s*$', '', line_stripped,
                          flags=re.IGNORECASE).strip()
            if len(name) > 5:
                seen.add(name_key)
                products.append({"name": name, "eur": eur, "bgn": bgn})

    # Pattern 2: Link формат [Име](url) с цена наблизо
    link_pattern = r'\[([^\]]*(?:harmonica|хармоника)[^\]]*)\]\([^\)]+\)'
    for match in re.finditer(link_pattern, markdown, re.IGNORECASE):
        name = match.group(1).strip()
        if not name or not is_food_product(name):
            continue

        name_key = name.lower()[:30]
        if name_key in seen:
            continue

        idx = match.end()
        context = markdown[idx:idx + 200]
        bgn = extract_bgn_price(context)
        if bgn and bgn > 0:
            eur = round(bgn / EUR_BGN_RATE, 2)
            seen.add(name_key)
            products.append({"name": name, "eur": eur, "bgn": bgn})

    return products


async def fetch_glovo_store_products(store_key, store_config, query="harmonica"):
    """
    Търси Harmonica продукти в Glovo магазин.

    Подходи по приоритет:
    1. Firecrawl (JS rendering, headless browser)
    2. Glovo API v3 (с auth token)
    3. curl_cffi HTML (fallback)
    """
    slug = store_config["slug"]
    city_code = store_config.get("city_code", "SOF")
    store_name = store_config["name"]

    logger.info(f"Glovo {store_name}: търсене на '{query}'...")
    start = time.time()

    # === Подход 1: Firecrawl (JS rendering) ===
    if FIRECRAWL_AVAILABLE and FIRECRAWL_API_KEY:
        # Firecrawl е синхронен — run в thread pool
        loop = asyncio.get_event_loop()
        fc_result = await loop.run_in_executor(
            None, _fetch_glovo_via_firecrawl, slug, store_name, query
        )
        if fc_result and fc_result.get("success"):
            return fc_result

    # === Подход 2: Glovo API (с auth token) ===
    if GLOVO_AUTH_TOKEN and CURL_CFFI_AVAILABLE:
        proxy = PROXY_URL if PROXY_URL else None
        glovo_headers = {
            "Accept": "application/json",
            "Accept-Language": "bg-BG,bg;q=0.9,en;q=0.8",
            "Glovo-Location-City-Code": city_code,
            "Glovo-Api-Version": "14",
            "Glovo-App-Platform": "web",
            "Glovo-App-Type": "customer",
            "Authorization": f"Bearer {GLOVO_AUTH_TOKEN}",
        }

        try:
            async with CurlAsyncSession(impersonate="chrome") as session:
                # API search
                search_url = f"{GLOVO_API_BASE}/stores/{slug}/search"
                resp = await session.get(
                    search_url, params={"query": query},
                    proxy=proxy, headers=glovo_headers, timeout=20,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    products = _parse_glovo_products(data, store_name)
                    if products:
                        elapsed = time.time() - start
                        logger.info(f"Glovo {store_name}: API search → "
                                    f"{len(products)} продукта ({elapsed:.1f}s)")
                        return {"success": True, "method": "glovo_api_search",
                                "products": products, "elapsed": elapsed}
                else:
                    logger.info(f"Glovo {store_name}: API search HTTP {resp.status_code}")

                # API catalog
                catalog_url = f"{GLOVO_API_BASE}/stores/{slug}"
                resp = await session.get(
                    catalog_url, proxy=proxy, headers=glovo_headers, timeout=20,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    products = _parse_glovo_catalog(data, store_name, query)
                    if products:
                        elapsed = time.time() - start
                        logger.info(f"Glovo {store_name}: API catalog → "
                                    f"{len(products)} продукта ({elapsed:.1f}s)")
                        return {"success": True, "method": "glovo_api_catalog",
                                "products": products, "elapsed": elapsed}
                else:
                    logger.info(f"Glovo {store_name}: API catalog HTTP {resp.status_code}")
        except Exception as e:
            logger.info(f"Glovo {store_name}: API грешка: {e}")

    elapsed = time.time() - start
    logger.warning(f"Glovo {store_name}: не намерени Harmonica продукти ({elapsed:.1f}s)")
    return {"success": False, "error": "No products found"}


def _parse_glovo_products(data, store_name):
    """Парсва продукти от Glovo API search response."""
    products = []
    seen = set()

    # Glovo search response може да е dict с "products" или list
    items = []
    if isinstance(data, dict):
        items = data.get("products", data.get("items", data.get("results", [])))
        # Опит: sections → products
        for section in data.get("sections", []):
            items.extend(section.get("products", section.get("items", [])))
    elif isinstance(data, list):
        items = data

    for item in items:
        name = item.get("name", item.get("productName", ""))
        if not name:
            continue
        if not is_harmonica_product(name):
            continue
        if not is_food_product(name):
            continue

        name_key = name.lower()[:30]
        if name_key in seen:
            continue

        # Price — Glovo обикновено връща в стотинки или пряко в BGN
        price_bgn = None
        price_obj = item.get("price", item.get("priceInfo", {}))
        if isinstance(price_obj, (int, float)):
            price_bgn = round(float(price_obj) / 100, 2) if price_obj > 100 else float(price_obj)
        elif isinstance(price_obj, dict):
            amount = price_obj.get("amount", price_obj.get("value", 0))
            if amount:
                price_bgn = round(float(amount) / 100, 2) if amount > 100 else float(amount)

        if price_bgn and price_bgn > 0:
            price_eur = round(price_bgn / EUR_BGN_RATE, 2)
            seen.add(name_key)
            products.append({
                "name": name,
                "eur": price_eur,
                "bgn": price_bgn,
            })

    return products


def _parse_glovo_catalog(data, store_name, query):
    """Парсва целия каталог и филтрира по query."""
    all_products = []

    # Каталогът може да е в categories → sections → products
    categories = data.get("categories", data.get("menu", {}).get("categories", []))
    for cat in categories:
        sections = cat.get("sections", cat.get("groups", []))
        for section in sections:
            items = section.get("products", section.get("items", []))
            all_products.extend(items)
        # Директни продукти в категорията
        all_products.extend(cat.get("products", []))

    # Филтрираме за Harmonica
    products = []
    seen = set()
    query_lower = query.lower()

    for item in all_products:
        name = item.get("name", "")
        if not name:
            continue
        if query_lower not in name.lower() and "хармоника" not in name.lower():
            continue
        if not is_food_product(name):
            continue

        name_key = name.lower()[:30]
        if name_key in seen:
            continue

        price_bgn = None
        price_obj = item.get("price", item.get("priceInfo", {}))
        if isinstance(price_obj, (int, float)):
            price_bgn = round(float(price_obj) / 100, 2) if price_obj > 100 else float(price_obj)
        elif isinstance(price_obj, dict):
            amount = price_obj.get("amount", price_obj.get("value", 0))
            if amount:
                price_bgn = round(float(amount) / 100, 2) if amount > 100 else float(amount)

        if price_bgn and price_bgn > 0:
            price_eur = round(price_bgn / EUR_BGN_RATE, 2)
            seen.add(name_key)
            products.append({
                "name": name,
                "eur": price_eur,
                "bgn": price_bgn,
            })

    return products


async def fetch_all_glovo_products(query="harmonica"):
    """Търси Harmonica продукти във всички Glovo магазини паралелно."""
    if not GLOVO_STORES:
        return {}

    has_firecrawl = FIRECRAWL_AVAILABLE and FIRECRAWL_API_KEY
    has_api = GLOVO_AUTH_TOKEN and CURL_CFFI_AVAILABLE

    if not has_firecrawl and not has_api:
        logger.warning("Glovo: нито FIRECRAWL_API_KEY, нито GLOVO_AUTH_TOKEN — пропускане")
        return {}

    if has_firecrawl:
        logger.info("Glovo: ще използваме Firecrawl (JS rendering)")
    elif has_api:
        logger.info("Glovo: ще използваме API с auth token")

    tasks = {}
    for store_key, config in GLOVO_STORES.items():
        tasks[store_key] = asyncio.create_task(
            fetch_glovo_store_products(store_key, config, query)
        )

    results = {}
    for store_key, task in tasks.items():
        try:
            result = await task
            results[store_key] = result
            if result.get("success"):
                products = result.get("products", [])
                logger.info(f"Glovo {GLOVO_STORES[store_key]['name']}: "
                            f"{len(products)} Harmonica продукта")
            else:
                logger.info(f"Glovo {GLOVO_STORES[store_key]['name']}: "
                            f"{result.get('error', 'неизвестна грешка')}")
        except Exception as e:
            logger.error(f"Glovo {GLOVO_STORES[store_key]['name']}: {e}")
            results[store_key] = {"success": False, "error": str(e)}

    return results


# =============================================================================
# MATCHING — подобрено с нормализация и тежести
# =============================================================================

def normalize_name(name):
    """Разширена нормализация на имена за по-добро съпоставяне."""
    name = name.lower()
    # Премахване на бранд
    name = re.sub(r'\b(harmonica|хармоника)\b', '', name)
    name = re.sub(r'\bbio\b|\bбио\b', '', name)
    # Нормализация на тегловни единици
    name = re.sub(r'(\d+)\s*ml\b', r'\1мл', name)
    name = re.sub(r'(\d+)\s*g\b', r'\1г', name)
    name = re.sub(r'(\d+)\s*kg\b', lambda m: f"{int(m.group(1))*1000}г", name)
    name = re.sub(r'(\d+)[,.](\d+)\s*(?:кг|kg)\b',
                  lambda m: f"{int(float(f'{m.group(1)}.{m.group(2)}')*1000)}г", name)
    # Премахване на пунктуация (запазваме % и цифри)
    name = re.sub(r'[^\w\s%]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def extract_keywords(name):
    """Извлича значими ключови думи от име на продукт."""
    name = normalize_name(name)
    keywords = re.findall(r'[а-яa-z]{3,}|\d+(?:г|мл|%|л)?', name)
    return set(keywords)


def extract_weight_grams(name):
    """Извлича тегло в грамове за сравнение. '400г' → 400, '0.5кг' → 500."""
    name_lower = name.lower()
    match = re.search(r'(\d+[.,]?\d*)\s*(г|g|мл|ml|кг|kg|л|l)\b', name_lower)
    if match:
        value = float(match.group(1).replace(',', '.'))
        unit = match.group(2)
        if unit in ('кг', 'kg', 'л', 'l'):
            return int(value * 1000)
        return int(value)
    return None


def match_products(ref_products, store_products):
    """
    Съпоставяне на референтни (Кашон) продукти с магазинни продукти.

    Scoring:
    - Базов: брой общи keywords
    - Грамаж: +3 при съвпадение, -1 при несъвпадение (мек penalty)
    - Процент: +2 при еднакъв % (напр. 3.6%)
    - Минимален праг: пропорционален на размера на keyword set-а
    """
    matches = {}
    used_indices = set()

    for ref in ref_products:
        ref_keywords = extract_keywords(ref["name"])
        ref_weight = extract_weight_grams(ref["name"])
        best_match = None
        best_score = 0
        best_idx = -1

        # Динамичен минимален праг — поне 40% от keywords трябва да съвпаднат
        min_threshold = max(2, len(ref_keywords) * 4 // 10)

        for idx, store_prod in enumerate(store_products):
            if idx in used_indices:
                continue

            store_keywords = extract_keywords(store_prod["name"])
            common = ref_keywords & store_keywords

            if not common:
                continue

            score = len(common)

            # Тежестен бонус/наказание (мек penalty за различен грамаж)
            store_weight = extract_weight_grams(store_prod["name"])
            if ref_weight and store_weight:
                if ref_weight == store_weight:
                    score += 3
                else:
                    score -= 1  # Мек penalty — не убива match-а

            # Процентен бонус (напр. 3,6% мастленост)
            ref_pct = re.findall(r'(\d+[.,]?\d*)\s*%', ref["name"])
            store_pct = re.findall(r'(\d+[.,]?\d*)\s*%', store_prod["name"])
            if (ref_pct and store_pct and
                    ref_pct[0].replace(',', '.') == store_pct[0].replace(',', '.')):
                score += 2

            if score >= min_threshold and score > best_score:
                best_score = score
                best_match = store_prod
                best_idx = idx

        if best_match:
            matches[ref["name"]] = best_match
            used_indices.add(best_idx)

    return matches


# =============================================================================
# CLAUDE PRICE VALIDATION — Sonnet 4.5 за проверка на съмнителни цени
# =============================================================================

def validate_prices_with_claude(final_products, all_store_keys):
    """
    Използва Claude Sonnet за валидация на съмнителни цени.
    Открива outlier-и (>50% отклонение от медианата) и ги изпраща за оценка.
    Връща final_products с добавени полета 'flagged' и 'claude_note'.
    """
    if not ANTHROPIC_AVAILABLE or not ANTHROPIC_API_KEY:
        logger.warning("Claude валидация пропусната — липсва API ключ или anthropic модул")
        return final_products, {}

    # 1. Намираме съмнителни цени — сравняваме по EUR
    suspicious = []
    for product in final_products:
        eur_prices = {}
        for sk in ["kashon"] + list(all_store_keys):
            data = product.get(sk)
            if data and data.get("eur") and data["eur"] > 0:
                eur_prices[sk] = data["eur"]

        if len(eur_prices) < 3:
            continue

        values = sorted(eur_prices.values())
        median = values[len(values) // 2]

        for store, price in eur_prices.items():
            deviation = abs(price - median) / median * 100
            if deviation > 50:
                suspicious.append({
                    "product": product["name"],
                    "store": store,
                    "price_eur": price,
                    "median_eur": round(median, 2),
                    "deviation_pct": round(deviation, 1),
                    "all_prices": {k: round(v, 2) for k, v in eur_prices.items()},
                })

    if not suspicious:
        logger.info("Claude валидация: няма съмнителни цени (всички в ±50% от медианата)")
        return final_products, {}

    logger.info(f"Claude валидация: {len(suspicious)} съмнителни цени открити, изпращаме към Sonnet...")

    # 2. Изпращаме batch към Claude Sonnet
    price_lines = []
    for i, s in enumerate(suspicious, 1):
        prices_str = ", ".join(f"{k}={v:.2f}€" for k, v in s["all_prices"].items())
        price_lines.append(
            f"{i}. Продукт: \"{s['product']}\"\n"
            f"   Магазин: {s['store']} → {s['price_eur']:.2f}€ (медиана: {s['median_eur']:.2f}€, "
            f"отклонение: {s['deviation_pct']:.0f}%)\n"
            f"   Всички цени: {prices_str}"
        )

    prompt = f"""Ти си експерт по цените на био храни и напитки в България от марката Хармоника (Harmonica).

Анализирай следните съмнителни цени (в EUR). За всяка реши:
- "ГРЕШНА" — цената е очевидно грешна (грешен match, грешно извлечена цена, цена за друг продукт или друг грамаж)
- "ВЯРНА" — цената е реална, макар и различна (промоция, по-висока цена в определен магазин)
- "СЪМНИТЕЛНА" — не можеш да прецениш със сигурност

Контекст за типични цени в EUR (1 EUR = 1.9558 BGN, фиксиран курс):
- Кисело мляко 400г: 1.28-1.79€
- Кисело мляко 2кг: 4.09-6.14€ (затова 4-5€ за 2кг е нормално!)
- Вафла 30г: 0.46-0.77€
- Сирене краве 400г: 5.11-7.67€
- Айран 500мл: 0.77-1.28€
- Масло 125г: 1.53-2.56€
- Тахан 250г: 2.56-4.09€

ВАЖНО: Внимавай за грамажа! Ако едни магазини продават 400г, а съмнителната цена може да е за 2кг версия — тя може да е вярна.

Съмнителни цени:
{chr(10).join(price_lines)}

Отговори САМО в JSON формат (без markdown):
[
  {{"index": 1, "verdict": "ГРЕШНА|ВЯРНА|СЪМНИТЕЛНА", "reason": "кратко обяснение", "action": "remove|keep|flag"}},
  ...
]"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        start_t = time.time()
        # ~150 tokens per verdict + buffer; minimum 2000
        needed_tokens = max(2000, len(suspicious) * 150 + 500)
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=needed_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.time() - start_t
        response_text = message.content[0].text.strip()
        logger.info(f"Claude Sonnet отговори за {elapsed:.1f}s ({message.usage.input_tokens} in, "
                    f"{message.usage.output_tokens} out)")

        # Парсваме JSON
        # Отстраняваме markdown wrapper ако има
        if response_text.startswith("```"):
            response_text = re.sub(r'^```(?:json)?\s*', '', response_text)
            response_text = re.sub(r'\s*```$', '', response_text)

        try:
            verdicts = json.loads(response_text)
        except json.JSONDecodeError:
            # Truncated JSON — опитваме да спасим валидните verdict-и
            logger.warning("Claude JSON truncated — опит за частично парсване...")
            # Намираме последния пълен обект (завършващ на })
            last_brace = response_text.rfind('}')
            if last_brace > 0:
                truncated = response_text[:last_brace + 1]
                # Затваряме масива
                if not truncated.rstrip().endswith(']'):
                    truncated = truncated.rstrip().rstrip(',') + '\n]'
                try:
                    verdicts = json.loads(truncated)
                    logger.info(f"  Спасени {len(verdicts)}/{len(suspicious)} verdict-и от truncated JSON")
                except json.JSONDecodeError as e2:
                    logger.error(f"Claude JSON repair неуспешен: {e2}")
                    logger.error(f"Отговор: {response_text[:500]}")
                    return final_products, {}
            else:
                logger.error(f"Claude JSON грешка: няма валидни verdict-и")
                logger.error(f"Отговор: {response_text[:500]}")
                return final_products, {}

    except Exception as e:
        logger.error(f"Claude API грешка: {e}")
        return final_products, {}

    # 3. Прилагаме решенията
    removed_count = 0
    flagged_count = 0
    kept_count = 0
    validation_log = {}

    for verdict in verdicts:
        idx = verdict.get("index", 0) - 1
        if idx < 0 or idx >= len(suspicious):
            continue

        s = suspicious[idx]
        action = verdict.get("action", "flag")
        reason = verdict.get("reason", "")
        verdict_text = verdict.get("verdict", "?")

        log_key = f"{s['product']}|{s['store']}"
        validation_log[log_key] = {
            "verdict": verdict_text,
            "action": action,
            "reason": reason,
            "price_eur": s["price_eur"],
            "median_eur": s["median_eur"],
        }

        if action == "remove":
            # Нулираме грешната цена
            for product in final_products:
                if product["name"] == s["product"] and product.get(s["store"]):
                    product[s["store"]] = None
                    removed_count += 1
                    logger.info(f"  ✗ ПРЕМАХНАТА: {s['store']} {s['product'][:40]} "
                                f"({s['price_eur']:.2f}€) — {reason}")
                    break
        elif action == "flag":
            # Маркираме за ръчна проверка
            for product in final_products:
                if product["name"] == s["product"] and product.get(s["store"]):
                    if not product.get("_flags"):
                        product["_flags"] = []
                    product["_flags"].append(f"{s['store']}: {reason}")
                    flagged_count += 1
                    logger.info(f"  ⚠ ФЛАГ: {s['store']} {s['product'][:40]} "
                                f"({s['price_eur']:.2f}€) — {reason}")
                    break
        else:
            kept_count += 1
            logger.info(f"  ✓ OK: {s['store']} {s['product'][:40]} "
                        f"({s['price_eur']:.2f}€) — {reason}")

    logger.info(f"Claude валидация: {removed_count} премахнати, {flagged_count} флагнати, "
                f"{kept_count} потвърдени")

    return final_products, validation_log


# =============================================================================
# CRAWLING — с retry и паралелно изпълнение
# =============================================================================

@retry_async(max_retries=2, backoff_base=3)
async def crawl_store(crawler, store_key, store_config):
    """Сканира един магазин с retry при грешка."""
    store_name = store_config["name"]
    url = store_config["url"]
    scroll_times = store_config.get("scroll_times", 5)
    use_magic = store_config.get("use_magic", False)

    logger.info(f"CRAWLING{'(magic)' if use_magic else ''}: {store_name}")

    scroll_delay = store_config.get("scroll_delay", 1500)
    scroll_js = ""
    if scroll_times > 0 and not use_magic:
        scroll_js = f"""
        async function scrollPage() {{
            const step = window.innerHeight || 800;
            for (let i = 0; i < {scroll_times}; i++) {{
                window.scrollBy(0, step);
                await new Promise(r => setTimeout(r, {scroll_delay}));
            }}
            // Final: scroll to absolute bottom twice to catch stragglers
            window.scrollTo(0, document.body.scrollHeight);
            await new Promise(r => setTimeout(r, {scroll_delay}));
            window.scrollTo(0, document.body.scrollHeight);
            await new Promise(r => setTimeout(r, {scroll_delay}));
        }}
        await scrollPage();
        """

    wait_for = store_config.get("wait_for")

    if use_magic:
        config = CrawlerRunConfig(
            magic=True,
            page_timeout=60000,
            remove_overlay_elements=True,
            cache_mode=CacheMode.BYPASS,
        )
    else:
        config = CrawlerRunConfig(
            page_timeout=90000,
            remove_overlay_elements=True,
            js_code=scroll_js if scroll_js else None,
            wait_for=wait_for,
        )

    start = time.time()
    result = await crawler.arun(url=url, config=config)
    elapsed = time.time() - start

    if not result.success:
        logger.error(f"{store_name}: FAILED — {result.error_message}")
        return {"success": False, "error": result.error_message}

    logger.info(f"{store_name}: OK {elapsed:.1f}s, {len(result.markdown)} chars")

    return {
        "success": True,
        "store_key": store_key,
        "elapsed": elapsed,
        "markdown": result.markdown,
        "html": getattr(result, 'html', None),
    }


async def crawl_all():
    """Сканира всички магазини паралелно с asyncio.gather."""
    browser_kwargs = {
        "headless": True,
        "viewport_width": 1920,
        "viewport_height": 1080,
    }
    if PROXY_URL:
        proxy_cfg = _parse_proxy_url(PROXY_URL)
        browser_kwargs["proxy_config"] = proxy_cfg
        logger.info(f"Proxy: {proxy_cfg['server']} (user: {proxy_cfg.get('username', 'N/A')})")

    browser_config = BrowserConfig(**browser_kwargs)

    results = {}

    # DM: Firecrawl (primary) в thread pool — стартираме рано
    dm_firecrawl_future = None
    dm_config = STORES.get("dm", {})
    if dm_config and FIRECRAWL_AVAILABLE and FIRECRAWL_API_KEY:
        loop = asyncio.get_event_loop()
        dm_firecrawl_future = loop.run_in_executor(None, _fetch_dm_via_firecrawl, "harmonica")

    # Randi: Firecrawl (primary) в thread pool — Crawl4AI не улавя JS
    randi_firecrawl_future = None
    if "randi" in STORES and FIRECRAWL_AVAILABLE and FIRECRAWL_API_KEY:
        loop = asyncio.get_event_loop()
        randi_firecrawl_future = loop.run_in_executor(None, _fetch_randi_via_firecrawl)

    # curl_cffi паралелни задачи (DM Algolia fallback, Lilly GraphQL, T-Market)
    curl_tasks = {}

    # DM Algolia само ако нямаме Firecrawl
    if not dm_firecrawl_future and dm_config.get("algolia_enabled") and CURL_CFFI_AVAILABLE:
        curl_tasks["dm"] = asyncio.create_task(fetch_dm_via_algolia("harmonica"))

    if CURL_CFFI_AVAILABLE and "lilly" in STORES:
        curl_tasks["lilly"] = asyncio.create_task(fetch_lilly_via_curl())

    if CURL_CFFI_AVAILABLE and "tmarket" in STORES:
        curl_tasks["tmarket"] = asyncio.create_task(fetch_tmarket_via_curl())

    # Crawl4AI задачи (пропускаме stores с curl_cffi/firecrawl path)
    crawl4ai_ok = False
    try:
        async with AsyncWebCrawler(config=browser_config) as crawler:
            crawl4ai_ok = True
            tasks = {}
            for key, cfg in STORES.items():
                if key in curl_tasks:
                    continue
                if key == "dm" and dm_firecrawl_future:
                    continue
                if key == "randi" and randi_firecrawl_future:
                    continue
                if cfg.get("needs_captcha_solver"):
                    tasks[key] = crawl_with_captcha_solver(crawler, key, cfg)
                else:
                    tasks[key] = crawl_store(crawler, key, cfg)

            task_results = await asyncio.gather(*tasks.values(), return_exceptions=True)

            for key, result in zip(tasks.keys(), task_results):
                if isinstance(result, Exception):
                    logger.error(f"{key}: Неочаквана грешка — {result}")
                    results[key] = {"success": False, "error": str(result)}
                else:
                    results[key] = result
    except Exception as e:
        logger.error(f"Crawl4AI browser launch failed: {e}")
        logger.warning("Continuing with curl_cffi/Firecrawl stores only")
        # Mark all Crawl4AI-only stores as failed
        for key, cfg in STORES.items():
            if key not in results and key not in curl_tasks:
                if key == "dm" and dm_firecrawl_future:
                    continue
                if key == "randi" and randi_firecrawl_future:
                    continue
                results[key] = {"success": False, "error": f"Crawl4AI unavailable: {e}"}

    # curl_cffi резултати с fallback към Crawl4AI
    for store_key, task in curl_tasks.items():
        try:
            curl_result = await task
            if curl_result.get("success"):
                results[store_key] = curl_result
                logger.info(f"{STORES[store_key]['name']}: curl_cffi успех "
                            f"(method: {curl_result.get('method')})")
            else:
                logger.warning(f"{STORES[store_key]['name']}: curl_cffi failed: "
                               f"{curl_result.get('error')}")
                if crawl4ai_ok:
                    logger.info(f"{STORES[store_key]['name']}: fallback към Crawl4AI")
                    async with AsyncWebCrawler(config=browser_config) as crawler:
                        cfg = STORES[store_key]
                        if cfg.get("needs_captcha_solver"):
                            results[store_key] = await crawl_with_captcha_solver(
                                crawler, store_key, cfg)
                        else:
                            results[store_key] = await crawl_store(
                                crawler, store_key, cfg)
                else:
                    results[store_key] = curl_result
        except Exception as e:
            logger.error(f"{STORES[store_key]['name']}: curl_cffi грешка: {e}")
            results[store_key] = {"success": False, "error": str(e)}

    # DM Firecrawl резултат с fallback към Algolia/curl_cffi
    if dm_firecrawl_future:
        try:
            dm_fc_result = await dm_firecrawl_future
            if dm_fc_result and dm_fc_result.get("success") and dm_fc_result.get("products"):
                results["dm"] = dm_fc_result
                logger.info(f"DM: Firecrawl успех — {len(dm_fc_result['products'])} продукта")
            else:
                logger.warning("DM: Firecrawl без продукти — fallback към Algolia/curl_cffi")
                if dm_config.get("algolia_enabled") and CURL_CFFI_AVAILABLE:
                    algolia_result = await fetch_dm_via_algolia("harmonica")
                    results["dm"] = algolia_result
                elif "dm" not in results:
                    results["dm"] = {"success": False, "error": "Firecrawl failed, no fallback"}
        except Exception as e:
            logger.error(f"DM Firecrawl грешка: {e}")
            if "dm" not in results:
                results["dm"] = {"success": False, "error": str(e)}

    # Randi Firecrawl резултат с fallback към Crawl4AI
    if randi_firecrawl_future:
        try:
            randi_fc_result = await randi_firecrawl_future
            if randi_fc_result and randi_fc_result.get("success") and randi_fc_result.get("products"):
                results["randi"] = randi_fc_result
                logger.info(f"Randi: Firecrawl успех — {len(randi_fc_result['products'])} продукта")
            else:
                logger.warning("Randi: Firecrawl без продукти")
                if "randi" not in results and crawl4ai_ok:
                    logger.info("Randi: fallback към Crawl4AI")
                    async with AsyncWebCrawler(config=browser_config) as crawler:
                        results["randi"] = await crawl_store(crawler, "randi", STORES["randi"])
                elif "randi" not in results:
                    results["randi"] = {"success": False, "error": "Firecrawl failed, Crawl4AI unavailable"}
        except Exception as e:
            logger.error(f"Randi Firecrawl грешка: {e}")
            if "randi" not in results and crawl4ai_ok:
                async with AsyncWebCrawler(config=browser_config) as crawler:
                    results["randi"] = await crawl_store(crawler, "randi", STORES["randi"])
            elif "randi" not in results:
                results["randi"] = {"success": False, "error": str(e)}

    # Glovo магазини (паралелно, отделен pipeline)
    has_glovo_method = (FIRECRAWL_AVAILABLE and FIRECRAWL_API_KEY) or \
                       (GLOVO_AUTH_TOKEN and CURL_CFFI_AVAILABLE)
    if GLOVO_STORES and has_glovo_method:
        glovo_results = await fetch_all_glovo_products("harmonica")
        results.update(glovo_results)

    return results


# =============================================================================
# GOOGLE SHEETS WRITER — универсален, с in_stock сиво форматиране
# =============================================================================

def extract_weight(name):
    """Извлича грамаж от име на продукт. Напр. 'Био вафли 40г' → '40г', '1.7 kg' → '1.7kg'"""
    match = re.search(r'(\d+[.,]?\d*)\s*(г|мл|ml|g|kg|кг|л|l)\b', name, re.IGNORECASE)
    if match:
        return f"{match.group(1)}{match.group(2)}"
    return ""


def write_to_sheets(final_products, stats):
    """
    Записва данните в Google Sheets.
    Формат: № | Продукт | Грамаж | Кашон BGN | Кашон EUR | Store1 EUR | ... | Ср.EUR | Статус
    Кашон показва и BGN и EUR, всички останали магазини — само EUR.
    """
    if not GSPREAD_AVAILABLE:
        logger.warning("gspread not available — skipping Sheets write")
        return False

    SPREADSHEET_NAME = "Harmonica Price Tracker"
    BASE_TAB = "Ценови Тракер"
    tab_suffix = os.environ.get("SHEET_TAB_SUFFIX", "")
    tab_name = f"{BASE_TAB}{tab_suffix}"

    # Магазини без Кашон (те показват само EUR) + Glovo магазини
    store_columns = [key for key, cfg in STORES.items() if not cfg.get("is_master")]
    store_columns += list(GLOVO_STORES.keys())
    store_display_names = {key: cfg["name"] for key, cfg in STORES.items()}
    store_display_names.update({k: f"Glovo {cfg['name']}" for k, cfg in GLOVO_STORES.items()})

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    logger.info(f"Google Sheets: записване в '{tab_name}'")
    logger.info(f"Магазини: Кашон + {', '.join(store_display_names[s] for s in store_columns)}")

    try:
        creds_json = os.environ.get("GOOGLE_CREDENTIALS")
        if creds_json:
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                f.write(creds_json)
                creds_path = f.name
            gc = gspread.service_account(filename=creds_path)
            os.unlink(creds_path)
        else:
            gc = gspread.service_account(filename='credentials.json')

        spreadsheet_id = os.environ.get("SPREADSHEET_ID")
        if spreadsheet_id:
            spreadsheet = gc.open_by_key(spreadsheet_id)
        else:
            spreadsheet = gc.open(SPREADSHEET_NAME)

        try:
            sheet = spreadsheet.worksheet(tab_name)
        except gspread.exceptions.WorksheetNotFound:
            sheet = spreadsheet.add_worksheet(title=tab_name, rows=200, cols=26)
            logger.info(f"Създаден нов таб: {tab_name}")

        logger.info(f"Свързан с '{tab_name}'")

    except Exception as e:
        logger.error(f"Google Sheets връзка неуспешна: {e}")
        return False

    # --- Изграждане на данните ---
    # Колони: №(0) | Продукт(1) | Грамаж(2) | Кашон BGN(3) | Кашон EUR(4) | Store1(5) | ... | Ср.EUR | Статус | Откл.%
    HEADER_ROW = 4           # 1-indexed sheet row (0-indexed: 3)
    KASHON_COL_START = 3     # Кашон BGN
    STORE_COL_START = 5      # Първи external store

    headers = ['№', 'Продукт', 'Грамаж', 'Кашон BGN', 'Кашон EUR']
    for store_key in store_columns:
        headers.append(store_display_names[store_key])
    headers.extend(['Ср.EUR', 'Статус', 'Откл.%'])

    DEVIATION_COL = len(headers) - 1  # Последната колона

    all_data = []

    all_data.append([f'HARMONICA - Ценови Тракер v10.1'] + [''] * (len(headers) - 1))

    meta = [f'Актуализация: {now}', '', f'Курс: 1 EUR = {EUR_BGN_RATE} BGN', '',
            f'Магазини: {len(STORES) + len(GLOVO_STORES)}']
    meta.extend([''] * (len(headers) - len(meta)))
    all_data.append(meta)

    all_data.append([''] * len(headers))
    all_data.append(headers)

    # --- Сортиране по категории ---
    sorted_products = sorted(final_products, key=lambda p: categorize_product(p["name"]))

    out_of_stock_cells = []
    deviation_cells_high = []   # (row, col) — цена >10% над средната
    deviation_cells_low = []    # (row, col) — цена >10% под средната
    category_separator_rows = []  # row indices за форматиране на разделителите
    new_product_rows = []         # row indices за нови продукти (зелен фон)
    removed_product_rows = []     # row indices за отпаднали продукти (жълт фон)

    current_category = None
    product_num = 0

    for product in sorted_products:
        cat_idx, cat_name = categorize_product(product["name"])

        # Добавяме разделител при нова категория
        if cat_name != current_category:
            current_category = cat_name
            separator_row = ['', cat_name] + [''] * (len(headers) - 2)
            all_data.append(separator_row)
            category_separator_rows.append(len(all_data) - 1)  # 0-indexed

        product_num += 1

        # Проследяване на статус за цветово кодиране
        product_status = product.get("status", "active")
        row_0idx_status = len(all_data)  # текущ row index за цветово маркиране
        if product_status == "new":
            new_product_rows.append(row_0idx_status)
        elif product_status == "removed":
            removed_product_rows.append(row_0idx_status)

        kashon = product.get("kashon") or {}
        kashon_bgn = kashon.get("bgn")
        kashon_eur = kashon.get("eur")

        row = [
            product_num,
            product["name"],
            extract_weight(product["name"]),
            kashon_bgn if kashon_bgn else '',
            kashon_eur if kashon_eur else '',
        ]

        # Събираме всички EUR цени (включително Кашон) за средната
        all_prices_eur = []
        if kashon_eur:
            all_prices_eur.append(kashon_eur)

        store_prices_info = []  # [(col_index, price_eur)] за deviation check

        # 0-indexed sheet row за текущия продукт
        row_0idx = len(all_data)

        for col_offset, store_key in enumerate(store_columns):
            store_data = product.get(store_key)
            col_index = STORE_COL_START + col_offset

            if store_data:
                price_eur = store_data.get("eur")
                row.append(price_eur if price_eur else '')

                if price_eur:
                    all_prices_eur.append(price_eur)
                    store_prices_info.append((col_index, price_eur))

                if not store_data.get("in_stock", True):
                    out_of_stock_cells.append((row_0idx, col_index))
            else:
                row.append('')

        # Средна EUR (от ВСИЧКИ магазини, включително Кашон)
        if all_prices_eur:
            avg_eur = round(sum(all_prices_eur) / len(all_prices_eur), 2)
            row.append(avg_eur)
        else:
            avg_eur = None
            row.append('')

        # Статус: в колко магазина е намерен
        matched_count = sum(1 for s in store_columns if product.get(s))
        row.append(f"{matched_count}/{len(store_columns)}")

        # Откл.%: максимално процентно отклонение от средната в този ред
        max_deviation_pct = None
        if avg_eur and len(all_prices_eur) >= 2:
            threshold_high = avg_eur * 1.10
            threshold_low = avg_eur * 0.90

            all_deviations = []

            # Проверяваме Кашон EUR (col 4)
            if kashon_eur:
                dev_pct = ((kashon_eur - avg_eur) / avg_eur) * 100
                all_deviations.append(dev_pct)
                if kashon_eur > threshold_high:
                    deviation_cells_high.append((row_0idx, 4))
                elif kashon_eur < threshold_low:
                    deviation_cells_low.append((row_0idx, 4))

            # Проверяваме external магазини
            for col_idx, price in store_prices_info:
                dev_pct = ((price - avg_eur) / avg_eur) * 100
                all_deviations.append(dev_pct)
                if price > threshold_high:
                    deviation_cells_high.append((row_0idx, col_idx))
                elif price < threshold_low:
                    deviation_cells_low.append((row_0idx, col_idx))

            # Намираме макс. отклонение по абсолютна стойност
            if all_deviations:
                max_dev = max(all_deviations, key=abs)
                max_deviation_pct = round(max_dev, 1)

        if max_deviation_pct is not None:
            sign = "+" if max_deviation_pct > 0 else ""
            row.append(f"{sign}{max_deviation_pct}%")
        else:
            row.append('')

        all_data.append(row)

    # Добавяме стрелки (↑/↓) в клетките с отклонение
    for row_idx, col_idx in deviation_cells_high:
        if HEADER_ROW <= row_idx < len(all_data):
            val = all_data[row_idx][col_idx]
            if val and val != '':
                all_data[row_idx][col_idx] = f"{val} ↑"

    for row_idx, col_idx in deviation_cells_low:
        if HEADER_ROW <= row_idx < len(all_data):
            val = all_data[row_idx][col_idx]
            if val and val != '':
                all_data[row_idx][col_idx] = f"{val} ↓"

    try:
        sheet.clear()
        sheet.update(values=all_data, range_name='A1')
        logger.info(f"Записани {len(all_data)} реда × {len(headers)} колони")
    except Exception as e:
        logger.error(f"Грешка при запис: {e}")
        return False

    # --- Форматиране ---
    try:
        last_row = len(all_data)
        last_col = len(headers)
        format_requests = []

        # Заглавен ред
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

        format_requests.append({
            "mergeCells": {
                "range": {"sheetId": sheet.id,
                          "startRowIndex": 0, "endRowIndex": 1,
                          "startColumnIndex": 0, "endColumnIndex": last_col},
                "mergeType": "MERGE_ALL"
            }
        })

        # Метаданни
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

        # Header
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

        # Ресет: бял фон + черен текст за всички data клетки (изчистваме остатъци)
        if last_row > HEADER_ROW:
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id,
                              "startRowIndex": HEADER_ROW, "endRowIndex": last_row,
                              "startColumnIndex": 0, "endColumnIndex": last_col},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": {"red": 1, "green": 1, "blue": 1},
                        "textFormat": {
                            "foregroundColor": {"red": 0, "green": 0, "blue": 0},
                            "bold": False, "italic": False, "fontSize": 10,
                        }
                    }},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)"
                }
            })

        # Категорийни разделители — тъмнозелен фон с бял bold текст
        for sep_row_idx in category_separator_rows:
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id,
                              "startRowIndex": sep_row_idx, "endRowIndex": sep_row_idx + 1,
                              "startColumnIndex": 0, "endColumnIndex": last_col},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": {"red": 0.18, "green": 0.49, "blue": 0.20},
                        "textFormat": {"bold": True, "fontSize": 10,
                                       "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                    }},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)"
                }
            })

        # Ширини
        col_widths = {0: 35, 1: 250, 2: 55, 3: 80, 4: 80}  # №, Продукт, Грамаж, Кашон BGN/EUR
        for offset in range(len(store_columns)):
            col_widths[STORE_COL_START + offset] = 80
        avg_col = STORE_COL_START + len(store_columns)
        col_widths[avg_col] = 75       # Ср.EUR
        col_widths[avg_col + 1] = 55   # Статус
        col_widths[DEVIATION_COL] = 65  # Откл.%

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

        # Сиво форматиране за изчерпани (OOS)
        for row_idx, col_idx in out_of_stock_cells:
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id,
                              "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                              "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1},
                    "cell": {"userEnteredFormat": {
                        "textFormat": {
                            "foregroundColor": {"red": 0.6, "green": 0.6, "blue": 0.6}
                        }
                    }},
                    "fields": "userEnteredFormat.textFormat.foregroundColor"
                }
            })

        # Червено (↑) за цени >10% над средната
        for row_idx, col_idx in deviation_cells_high:
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id,
                              "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                              "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": {"red": 0.96, "green": 0.80, "blue": 0.80},
                        "textFormat": {
                            "foregroundColor": {"red": 0.7, "green": 0.0, "blue": 0.0},
                            "bold": True,
                        }
                    }},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)"
                }
            })

        # Светлосиньо (↓) за цени >10% под средната
        for row_idx, col_idx in deviation_cells_low:
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id,
                              "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                              "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": {"red": 0.82, "green": 0.91, "blue": 0.98},
                        "textFormat": {
                            "foregroundColor": {"red": 0.0, "green": 0.3, "blue": 0.6},
                            "bold": True,
                        }
                    }},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)"
                }
            })

        # Светлозелен фон за нови продукти (добавени при последен sync)
        for row_idx in new_product_rows:
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id,
                              "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                              "startColumnIndex": 0, "endColumnIndex": last_col},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": {"red": 0.85, "green": 0.95, "blue": 0.85},
                        "textFormat": {
                            "foregroundColor": {"red": 0.1, "green": 0.4, "blue": 0.1},
                        }
                    }},
                    "fields": "userEnteredFormat(backgroundColor,textFormat.foregroundColor)"
                }
            })

        # Жълт фон за отпаднали продукти
        for row_idx in removed_product_rows:
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id,
                              "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                              "startColumnIndex": 0, "endColumnIndex": last_col},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": {"red": 1.0, "green": 0.95, "blue": 0.80},
                        "textFormat": {
                            "foregroundColor": {"red": 0.6, "green": 0.5, "blue": 0.0},
                            "strikethrough": True,
                        }
                    }},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)"
                }
            })

        if format_requests:
            sheet.spreadsheet.batch_update({"requests": format_requests})
            logger.info(f"Форматиране: {len(format_requests)} заявки")
            if category_separator_rows:
                logger.info(f"Категории: {len(category_separator_rows)} разделителни реда")
            if new_product_rows:
                logger.info(f"Нови продукти: {len(new_product_rows)} реда (зелен фон)")
            if removed_product_rows:
                logger.info(f"Отпаднали продукти: {len(removed_product_rows)} реда (жълт фон)")
            if out_of_stock_cells:
                logger.info(f"Сиво форматиране: {len(out_of_stock_cells)} изчерпани клетки")
            if deviation_cells_high or deviation_cells_low:
                logger.info(f"Отклонения: {len(deviation_cells_high)} ↑ червени, "
                            f"{len(deviation_cells_low)} ↓ сини")

        return True

    except Exception as e:
        logger.warning(f"Форматиране пропуснато (данните са записани): {e}")
        return True


# =============================================================================
# EMAIL REPORT
# =============================================================================

def send_email_report(final_products, stats):
    """
    Изпраща HTML имейл с обобщение на резултатите от experimental scraper.
    """
    gmail_user = os.environ.get('GMAIL_USER')
    gmail_pass = os.environ.get('GMAIL_APP_PASSWORD')
    recipients = os.environ.get('ALERT_EMAIL', gmail_user)
    spreadsheet_id = os.environ.get('SPREADSHEET_ID', '')

    if not gmail_user or not gmail_pass:
        logger.warning("Gmail credentials не са зададени — пропускане на имейл")
        return

    if not recipients:
        logger.warning("ALERT_EMAIL не е зададен — пропускане на имейл")
        return

    sheets_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}" if spreadsheet_id else ""
    date_str = datetime.now().strftime("%d.%m.%Y")
    time_str = datetime.now().strftime("%H:%M")

    # Статистики
    total_products = len(final_products)
    store_keys = [key for key, cfg in STORES.items() if not cfg.get("is_master")]
    store_keys += list(GLOVO_STORES.keys())

    # Покритие по магазини
    store_coverage = {}
    all_display = {}
    all_display.update({k: cfg["name"] for k, cfg in STORES.items()})
    all_display.update({k: f"Glovo {cfg['name']}" for k, cfg in GLOVO_STORES.items()})

    for sk in store_keys:
        count = len([p for p in final_products if p.get(sk)])
        store_coverage[all_display.get(sk, sk)] = count

    # Продукти с отклонение >10%
    alerts = []
    for p in final_products:
        all_prices = []
        kashon = p.get("kashon") or {}
        if kashon.get("eur"):
            all_prices.append(kashon["eur"])
        for sk in store_keys:
            sd = p.get(sk)
            if sd and sd.get("eur"):
                all_prices.append(sd["eur"])
        if len(all_prices) >= 2:
            avg = sum(all_prices) / len(all_prices)
            max_dev = max(((pr - avg) / avg) * 100 for pr in all_prices)
            min_dev = min(((pr - avg) / avg) * 100 for pr in all_prices)
            extreme = max_dev if abs(max_dev) >= abs(min_dev) else min_dev
            if abs(extreme) > 10:
                alerts.append({"name": p["name"], "deviation": round(extreme, 1)})

    warning_count = len(alerts)
    ok_count = total_products - warning_count

    if warning_count > 0:
        subject = f"Harmonica: {warning_count} продукта с отклонение >10%"
    else:
        subject = f"Harmonica: Всички цени в норма ({total_products} продукта)"

    html = f"""<html><head><style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .header {{ background: #2e7d32; color: white; padding: 20px; text-align: center; }}
        .header h1 {{ margin: 0; font-size: 22px; }}
        .header p {{ margin: 5px 0 0; font-size: 13px; opacity: 0.9; }}
        .summary {{ background: #f5f5f5; padding: 15px; margin: 20px; border-radius: 5px; }}
        .stats {{ display: flex; justify-content: space-around; text-align: center; }}
        .stat-box {{ padding: 10px; }}
        .stat-number {{ font-size: 28px; font-weight: bold; }}
        .stat-label {{ font-size: 12px; color: #666; }}
        .ok {{ color: #2e7d32; }}
        .warning {{ color: #d32f2f; }}
        .alert-section {{ background: #ffebee; border-left: 4px solid #d32f2f; padding: 15px; margin: 20px; }}
        .coverage {{ margin: 20px; }}
        .bar-bg {{ background: #e0e0e0; height: 18px; border-radius: 9px; margin: 4px 0; overflow: hidden; }}
        .bar-fill {{ background: #4caf50; height: 100%; }}
        .footer {{ background: #f5f5f5; padding: 15px; text-align: center; font-size: 12px; color: #666; }}
        .button {{ display: inline-block; background: #2e7d32; color: white; padding: 10px 20px;
                   text-decoration: none; border-radius: 5px; margin: 10px; }}
    </style></head><body>
    <div class="header">
        <h1>HARMONICA Price Tracker</h1>
        <p>Отчет за {date_str} в {time_str} ч.</p>
    </div>
    <div class="summary">
        <h2 style="color:#2e7d32; margin-top:0;">Обобщение</h2>
        <div class="stats">
            <div class="stat-box"><div class="stat-number">{total_products}</div><div class="stat-label">Продукта</div></div>
            <div class="stat-box"><div class="stat-number ok">{ok_count}</div><div class="stat-label">В норма</div></div>
            <div class="stat-box"><div class="stat-number warning">{warning_count}</div><div class="stat-label">С отклонение</div></div>
            <div class="stat-box"><div class="stat-number">{len(STORES)+len(GLOVO_STORES)}</div><div class="stat-label">Магазина</div></div>
        </div>
    </div>"""

    if alerts:
        html += f'<div class="alert-section"><h2 style="color:#d32f2f;margin-top:0;">Отклонения &gt;10%</h2>'
        for a in alerts[:15]:
            arrow = "↑" if a["deviation"] > 0 else "↓"
            color = "#d32f2f" if a["deviation"] > 0 else "#1565c0"
            html += f'<p><strong>{a["name"]}</strong>: <span style="color:{color}">{arrow} {abs(a["deviation"]):.1f}%</span></p>'
        if len(alerts) > 15:
            html += f'<p><em>... и още {len(alerts)-15} продукта</em></p>'
        html += '</div>'
    else:
        html += '<div class="summary" style="background:#e8f5e9;border-left:4px solid #2e7d32;margin:20px;"><h2 style="color:#2e7d32;margin-top:0;">Всички цени са в норма</h2></div>'

    html += '<div class="coverage"><h2 style="color:#2e7d32;">Покритие по магазини</h2>'
    for store_name, count in store_coverage.items():
        pct = (count / total_products * 100) if total_products else 0
        html += f'<div style="font-size:13px;color:#666;"><strong>{store_name}</strong>: {count}/{total_products} ({pct:.0f}%)</div>'
        html += f'<div class="bar-bg"><div class="bar-fill" style="width:{pct}%"></div></div>'
    html += '</div>'

    if sheets_url:
        html += f'<div style="text-align:center;margin:20px;"><a href="{sheets_url}" class="button">Отвори в Google Sheets</a></div>'

    html += f'<div class="footer"><p><strong>Harmonica Price Tracker v10.1</strong></p><p>Автоматично генерирано на {date_str} в {time_str} ч.</p></div></body></html>'

    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = gmail_user
        msg['To'] = recipients
        msg['Subject'] = subject
        msg.attach(MIMEText(html, 'html', 'utf-8'))

        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(gmail_user, gmail_pass)
            server.send_message(msg)

        logger.info(f"Имейл изпратен до {recipients}")
    except Exception as e:
        logger.error(f"Имейл грешка: {str(e)[:80]}")


# =============================================================================
# MAIN
# =============================================================================

async def main():
    logger.info("=" * 60)
    total_stores = len(STORES) + len(GLOVO_STORES)
    logger.info(f"HARMONICA PRICE TRACKER v10.1 — {total_stores} магазина")
    logger.info("=" * 60)
    logger.info(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Магазини: {len(STORES)} + {len(GLOVO_STORES)} Glovo, BS4: {BS4_AVAILABLE}, "
                f"CapSolver: {CAPSOLVER_AVAILABLE}, curl_cffi: {CURL_CFFI_AVAILABLE}")
    if PROXY_URL:
        logger.info(f"Proxy: {PROXY_URL[:30]}...")
    if FIRECRAWL_AVAILABLE and FIRECRAWL_API_KEY:
        logger.info(f"Firecrawl: YES (key: {FIRECRAWL_API_KEY[:8]}...)")
    elif FIRECRAWL_API_KEY and not FIRECRAWL_AVAILABLE:
        logger.warning(f"Firecrawl: KEY SET but import FAILED — DM/Randi/Glovo Firecrawl disabled")
    if GLOVO_AUTH_TOKEN:
        logger.info(f"Glovo auth: YES (token length: {len(GLOVO_AUTH_TOKEN)})")
    if not FIRECRAWL_API_KEY and not GLOVO_AUTH_TOKEN:
        logger.info("Glovo: нито Firecrawl, нито auth — Glovo магазините ще се пропуснат")
    if ANTHROPIC_AVAILABLE and ANTHROPIC_API_KEY:
        logger.info(f"Claude: YES ({CLAUDE_MODEL})")
    else:
        logger.info("Claude: НЕ — ценова валидация изключена")

    if not CRAWL4AI_AVAILABLE:
        logger.error("Crawl4AI not available!")
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

    # DM Bulgaria
    dm_products = []
    dm_data = crawl_results.get("dm", {})
    if dm_data.get("success"):
        method = dm_data.get("method", "unknown")
        # Algolia API — продуктите са вече извлечени
        if dm_data.get("products"):
            dm_products = dm_data["products"]
        # curl_cffi HTML или Crawl4AI HTML — парсваме
        elif dm_data.get("html"):
            dm_products = extract_dm_from_curl_html(dm_data["html"])
            if not dm_products:
                dm_products = extract_dm_products(
                    dm_data.get("markdown", ""),
                    html_text=dm_data.get("html"),
                )
        elif dm_data.get("markdown"):
            dm_products = extract_dm_products(dm_data["markdown"])
        logger.info(f"DM: {len(dm_products)} Harmonica products (method: {method})")
    elif dm_data.get("error"):
        logger.warning(f"DM: {dm_data['error']}")

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
            store_info["products"] = _extract_generic_products(
                store_data["markdown"],
                brand_page=store_info["brand_page"],
            )
            logger.info(f"{STORES[store_key]['name']}: {len(store_info['products'])} Harmonica products")
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
        "dm": dm_products,
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
        "version": "v10.1",
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
