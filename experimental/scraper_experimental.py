"""
EXP-003: Crawl4AI Experimental Scraper v9.0.4
===============================================
Промени спрямо v9.0.3:
- Lilly: Hyvä Theme поддръжка — JSON-LD, attr search (alt/title), text nodes
- T-Market: curl_cffi TLS impersonation за CloudCart + Cloudflare bypass
- Optima: WooCommerce Store API + curl_cffi fallback
- crawl_all(): паралелни curl_cffi задачи за DM/T-Market/Optima

Промени спрямо v8.0:
- VMV Supermarket, Optima, T-Market добавени (Crawl4AI)
- DM Algolia API (curl_cffi) с CapSolver fallback
- curl_cffi за TLS impersonation (Cloudflare bypass)
- Proxy support (PROXY_URL env var)
- Общо 8 магазина (Кашон + 7 external)
"""

import asyncio
import functools
import time
import json
import os
import re
import logging
from datetime import datetime

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('scraper_experimental.log', encoding='utf-8'),
    ]
)
logger = logging.getLogger('experimental')

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


# =============================================================================
# CONSTANTS
# =============================================================================

EUR_BGN_RATE = 1.9558  # Фиксиран курс
PROXY_URL = os.environ.get("PROXY_URL")  # Optional: http://user:pass@host:port


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
        "scroll_times": 4,
        "is_reference": False,
        "brand_page": True,
        "use_magic": True,
    },
    "dm": {
        "name": "DM Bulgaria",
        "url": "https://www.dm.bg/search?query=harmonica&searchType=product",
        "scroll_times": 5,
        "is_reference": False,
        "needs_captcha_solver": True,
        "algolia_enabled": True,
    },
    "vmv": {
        "name": "VMV Supermarket",
        "url": "https://vmv.bg/search?q=harmonica",
        "scroll_times": 5,
        "is_reference": False,
    },
    "optima": {
        "name": "Optima",
        "url": "https://optima.bg/?s=harmonica&post_type=product",
        "scroll_times": 5,
        "is_reference": False,
        "use_magic": True,
    },
    "tmarket": {
        "name": "T-Market",
        "url": "https://tmarketonline.bg/vendor/harmonica-1881705916",
        "scroll_times": 8,
        "is_reference": False,
        "brand_page": True,
        "needs_captcha_solver": True,
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
# RETRY DECORATOR
# =============================================================================

def retry_async(max_retries=3, backoff_base=2):
    """Декоратор за автоматичен retry при мрежови грешки."""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        wait = backoff_base ** attempt
                        logger.warning(
                            f"Retry {attempt+1}/{max_retries} за {func.__name__} "
                            f"след {wait}s: {str(e)[:60]}"
                        )
                        await asyncio.sleep(wait)
            logger.error(f"Всички {max_retries} retry-а неуспешни за {func.__name__}: {last_error}")
            return {"success": False, "error": str(last_error)}
        return wrapper
    return decorator


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
        except ValueError:
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
        except ValueError:
            pass
    return None


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

        name_key = name.lower()[:30]
        if name_key in seen:
            continue

        idx = match.start()
        context = markdown[max(0, idx-50):idx+500]

        eur = extract_eur_price(context)
        bgn = extract_bgn_price(context)

        if eur or bgn:
            seen.add(name_key)
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
    """
    products = []
    seen = set()

    # Разделяме на блокове
    blocks = re.split(r'\n{2,}', markdown)

    for block in blocks:
        # Проверка за harmonica (освен ако е brand page)
        if not brand_page and not is_harmonica_product(block):
            continue

        # Търсим цена
        bgn = extract_bgn_price(block)
        eur = extract_eur_price(block)
        if not bgn and not eur:
            # Опит: цена без валутен суфикс (напр. "2.99")
            price_match = re.search(r'(\d+)[,.](\d{2})\b', block)
            if price_match:
                try:
                    price = float(f"{price_match.group(1)}.{price_match.group(2)}")
                    if 0.50 <= price <= 100:
                        bgn = round(price, 2)
                except ValueError:
                    pass
        if not bgn and not eur:
            continue

        if bgn and not eur:
            eur = round(bgn / EUR_BGN_RATE, 2)

        # Извличаме продуктово име
        name = None

        # Опит 1: Link текст
        link_match = re.search(r'(?<!!)\[([^\]]{5,100})\]\([^\)]+\)', block)
        if link_match:
            candidate = link_match.group(1).strip()
            if len(candidate) > 5 and is_food_product(candidate):
                name = candidate

        # Опит 2: Heading
        if not name:
            heading_match = re.search(r'#+\s*(.{5,80})', block)
            if heading_match:
                candidate = heading_match.group(1).strip()
                if is_food_product(candidate):
                    name = candidate

        # Опит 3: Най-дълъг текстов ред (вероятно продуктово име)
        if not name:
            for line in block.split('\n'):
                line = line.strip()
                line = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'\1', line)
                line = re.sub(r'[#*_>|!]', '', line).strip()
                line = re.sub(r'\s+', ' ', line)
                if (len(line) > 10 and
                        len(re.findall(r'[а-яА-Яa-zA-Z]', line)) >= 3 and
                        is_food_product(line)):
                    name = line
                    break

        if not name:
            continue

        name_key = name.lower()[:30]
        if name_key in seen:
            continue

        seen.add(name_key)
        products.append({"name": name, "eur": eur, "bgn": bgn})

    return products


# =============================================================================
# VMV SUPERMARKET EXTRACTION
# =============================================================================

def extract_vmv_products(markdown, html_text=None, brand_page=True):
    """
    Извлича Harmonica продукти от VMV Supermarket.

    VMV.bg е онлайн супермаркет. Brand page: vmv.bg/brands/harmonica
    На brand page всички продукти са Harmonica → skip harmonica name check.
    Цени в BGN (лева).
    """
    products = []
    seen = set()

    # Pattern 1: Links — на brand page всички продукти са Harmonica
    link_pattern = r'\[([^\]]{5,100})\]\(((?:https?://[^\)]+|/[^\)]+))\)'
    for match in re.finditer(link_pattern, markdown):
        name = match.group(1).strip()
        url = match.group(2)

        if name.startswith('!') or 'logo' in name.lower() or 'banner' in name.lower():
            continue
        if len(re.findall(r'[а-яА-Яa-zA-Z]', name)) < 3:
            continue
        # На brand page не проверяваме за harmonica в името
        if not brand_page and not is_harmonica_product(name):
            continue

        name_key = name.lower()[:30]
        if name_key in seen:
            continue
        if not is_food_product(name):
            continue

        idx = match.end()
        context = markdown[max(0, idx - 100):idx + 400]

        bgn = extract_bgn_price(context)
        eur = extract_eur_price(context)

        if bgn and not eur:
            eur = round(bgn / EUR_BGN_RATE, 2)

        if bgn or eur:
            seen.add(name_key)
            products.append({"name": name, "eur": eur, "bgn": bgn})

    # Pattern 2: Текстови блокове с цена (без link)
    if not products:
        products = _extract_generic_products(markdown, brand_page=brand_page)

    if not products:
        logger.warning(f"VMV: 0 продукта, markdown preview: {markdown[:500]}")
    else:
        logger.info(f"VMV: {len(products)} продукта извлечени")
    return products


# =============================================================================
# OPTIMA EXTRACTION
# =============================================================================

def extract_optima_products(markdown, html_text=None, brand_page=False):
    """
    Извлича Harmonica продукти от Optima.bg.

    Optima.bg е онлайн супермаркет в София. URL формат:
    optima.bg/магазин/{category}/{id}/{product-slug}
    Цени в BGN. Search page: ?s=harmonica
    """
    products = []
    seen = set()

    # Pattern 1: Links с Harmonica (search page — проверяваме за harmonica)
    link_pattern = r'\[([^\]]{5,120})\]\(((?:https?://[^\)]+|/[^\)]+))\)'
    for match in re.finditer(link_pattern, markdown):
        name = match.group(1).strip()

        if name.startswith('!') or 'logo' in name.lower():
            continue
        if not brand_page and not is_harmonica_product(name):
            continue

        name_key = name.lower()[:30]
        if name_key in seen:
            continue
        if not is_food_product(name):
            continue

        idx = match.end()
        context = markdown[max(0, idx - 100):idx + 400]

        bgn = extract_bgn_price(context)
        eur = extract_eur_price(context)

        if bgn and not eur:
            eur = round(bgn / EUR_BGN_RATE, 2)

        if bgn or eur:
            seen.add(name_key)
            products.append({"name": name, "eur": eur, "bgn": bgn})

    # Pattern 2: Текстови блокове с harmonica + цена
    if not products:
        products = _extract_generic_products(markdown, brand_page=brand_page)

    if not products:
        logger.warning(f"Optima: 0 продукта, markdown len={len(markdown)}, "
                       f"preview: {markdown[:500]}")
    else:
        logger.info(f"Optima: {len(products)} продукта извлечени")
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
                    if 0.50 <= price <= 50:
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
                "https://www.dm.bg/search?query=harmonica&searchType=product",
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
                        js_url = f"https://www.dm.bg{js_url}"
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
# OPTIMA curl_cffi + WooCommerce Store API
# =============================================================================

async def fetch_optima_via_curl(query="harmonica"):
    """
    Опит за fetch на Optima.bg чрез curl_cffi.
    Пробваме WooCommerce Store API и стандартен search.
    """
    if not CURL_CFFI_AVAILABLE:
        return {"success": False, "error": "curl_cffi not available"}

    logger.info("Optima: curl_cffi fetch...")
    start = time.time()

    try:
        async with CurlAsyncSession(impersonate="chrome") as session:
            proxy = PROXY_URL if PROXY_URL else None

            # Опит 1: WooCommerce Store API (публичен, без auth)
            api_url = f"https://optima.bg/wp-json/wc/store/v1/products?search={query}&per_page=50"
            try:
                api_resp = await session.get(
                    api_url,
                    proxy=proxy,
                    timeout=20,
                    headers={
                        "Accept": "application/json",
                        "Accept-Language": "bg-BG,bg;q=0.9",
                    },
                )
                if api_resp.status_code == 200:
                    data = api_resp.json()
                    if isinstance(data, list) and data:
                        products = []
                        for item in data:
                            name = item.get('name', '')
                            if not name:
                                continue
                            prices = item.get('prices', {})
                            price_str = prices.get('price', '0')
                            try:
                                price_bgn = round(int(price_str) / 100, 2) if price_str else None
                            except (ValueError, TypeError):
                                price_bgn = None
                            if price_bgn:
                                price_eur = round(price_bgn / EUR_BGN_RATE, 2)
                                products.append({
                                    "name": name,
                                    "eur": price_eur,
                                    "bgn": price_bgn,
                                })

                        if products:
                            elapsed = time.time() - start
                            logger.info(f"Optima WC API: {len(products)} продукта ({elapsed:.1f}s)")
                            return {
                                "success": True,
                                "method": "wc_store_api",
                                "products": products,
                                "elapsed": elapsed,
                            }
                else:
                    logger.info(f"Optima WC API: HTTP {api_resp.status_code}")
            except Exception as e:
                logger.info(f"Optima WC API: {e}")

            # Опит 2: WP REST API v2
            api_url2 = f"https://optima.bg/wp-json/wp/v2/product?search={query}&per_page=50"
            try:
                api_resp2 = await session.get(
                    api_url2,
                    proxy=proxy,
                    timeout=20,
                    headers={"Accept": "application/json"},
                )
                if api_resp2.status_code == 200:
                    data = api_resp2.json()
                    if isinstance(data, list) and data:
                        elapsed = time.time() - start
                        logger.info(f"Optima WP API: {len(data)} резултата ({elapsed:.1f}s)")
                        # Partial data — return HTML for BS4 parsing
                        return {
                            "success": True,
                            "method": "wp_api",
                            "products": [],
                            "html": "",
                            "api_data": data,
                            "elapsed": elapsed,
                        }
            except Exception:
                pass

            # Опит 3: Стандартен HTML fetch
            search_url = f"https://optima.bg/?s={query}&post_type=product"
            resp = await session.get(
                search_url,
                proxy=proxy,
                timeout=30,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "bg-BG,bg;q=0.9",
                },
            )

            elapsed = time.time() - start

            if resp.status_code != 200:
                logger.warning(f"Optima curl_cffi: HTTP {resp.status_code}")
                return {"success": False, "error": f"HTTP {resp.status_code}"}

            html = resp.text
            logger.info(f"Optima curl_cffi: OK {elapsed:.1f}s, {len(html)} chars")
            return {
                "success": True,
                "method": "curl_cffi_html",
                "html": html,
                "markdown": "",
                "elapsed": elapsed,
                "store_key": "optima",
            }

    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"Optima curl_cffi грешка: {e} ({elapsed:.1f}s)")
        return {"success": False, "error": str(e)}


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
    Подобрено съпоставяне с:
    - Тежестен бонус за съвпадение на грамаж
    - Процентен бонус (3.6% == 3.6%)
    - Наказание за несъвпадение на тегло
    - Предотвратяване на дублиращи се съпоставяния
    """
    matches = {}
    used_indices = set()

    for ref in ref_products:
        ref_keywords = extract_keywords(ref["name"])
        ref_weight = extract_weight_grams(ref["name"])
        best_match = None
        best_score = 0
        best_idx = -1

        for idx, store_prod in enumerate(store_products):
            if idx in used_indices:
                continue

            store_keywords = extract_keywords(store_prod["name"])
            common = ref_keywords & store_keywords

            if not common:
                continue

            score = len(common)

            # Тежестен бонус/наказание
            store_weight = extract_weight_grams(store_prod["name"])
            if ref_weight and store_weight:
                if ref_weight == store_weight:
                    score += 3
                else:
                    score -= 2

            # Процентен бонус (напр. 3,6% мастленост)
            ref_pct = re.findall(r'(\d+[.,]?\d*)\s*%', ref["name"])
            store_pct = re.findall(r'(\d+[.,]?\d*)\s*%', store_prod["name"])
            if (ref_pct and store_pct and
                    ref_pct[0].replace(',', '.') == store_pct[0].replace(',', '.')):
                score += 2

            if score >= 2 and score > best_score:
                best_score = score
                best_match = store_prod
                best_idx = idx

        if best_match:
            matches[ref["name"]] = best_match
            used_indices.add(best_idx)

    return matches


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

    scroll_js = ""
    if scroll_times > 0 and not use_magic:
        scroll_js = f"""
        async function scrollPage() {{
            for (let i = 0; i < {scroll_times}; i++) {{
                window.scrollTo(0, document.body.scrollHeight);
                await new Promise(r => setTimeout(r, 1500));
            }}
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
        browser_kwargs["proxy"] = PROXY_URL
        logger.info(f"Proxy: {PROXY_URL[:30]}...")

    browser_config = BrowserConfig(**browser_kwargs)

    results = {}

    # curl_cffi паралелни задачи (DM Algolia, T-Market, Optima)
    curl_tasks = {}

    dm_config = STORES.get("dm", {})
    if dm_config.get("algolia_enabled") and CURL_CFFI_AVAILABLE:
        curl_tasks["dm"] = asyncio.create_task(fetch_dm_via_algolia("harmonica"))

    if CURL_CFFI_AVAILABLE and "tmarket" in STORES:
        curl_tasks["tmarket"] = asyncio.create_task(fetch_tmarket_via_curl())

    if CURL_CFFI_AVAILABLE and "optima" in STORES:
        curl_tasks["optima"] = asyncio.create_task(fetch_optima_via_curl())

    # Crawl4AI задачи (пропускаме stores с curl_cffi path)
    async with AsyncWebCrawler(config=browser_config) as crawler:
        tasks = {}
        for key, cfg in STORES.items():
            if key in curl_tasks:
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
                               f"{curl_result.get('error')} — fallback Crawl4AI")
                async with AsyncWebCrawler(config=browser_config) as crawler:
                    cfg = STORES[store_key]
                    if cfg.get("needs_captcha_solver"):
                        results[store_key] = await crawl_with_captcha_solver(
                            crawler, store_key, cfg)
                    else:
                        results[store_key] = await crawl_store(
                            crawler, store_key, cfg)
        except Exception as e:
            logger.error(f"{STORES[store_key]['name']}: curl_cffi грешка: {e}")
            results[store_key] = {"success": False, "error": str(e)}

    return results


# =============================================================================
# GOOGLE SHEETS WRITER — универсален, с in_stock сиво форматиране
# =============================================================================

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
    """
    if not GSPREAD_AVAILABLE:
        logger.warning("gspread not available — skipping Sheets write")
        return False

    SPREADSHEET_NAME = "Harmonica Price Tracker"
    BASE_TAB = "Ценови Тракер"
    tab_suffix = os.environ.get("SHEET_TAB_SUFFIX", "")
    tab_name = f"{BASE_TAB}{tab_suffix}"

    store_columns = [key for key, cfg in STORES.items() if not cfg.get("is_reference")]
    store_display_names = {key: cfg["name"] for key, cfg in STORES.items()}

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    logger.info(f"Google Sheets: записване в '{tab_name}'")
    logger.info(f"Магазини: {', '.join(store_display_names[s] for s in store_columns)}")

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
    HEADER_ROW = 4
    DATA_START_ROW = 5
    STORE_COL_START = 5

    headers = ['№', 'Продукт', 'Грамаж', 'Реф.BGN', 'Реф.EUR']
    for store_key in store_columns:
        headers.append(store_display_names[store_key])
    headers.extend(['Ср.BGN', 'Откл.%', 'Статус'])

    all_data = []

    all_data.append([f'HARMONICA - Ценови Тракер (EXP-003)'] + [''] * (len(headers) - 1))

    meta = [f'Актуализация: {now}', '', f'Курс: 1 EUR = {EUR_BGN_RATE} BGN', '',
            f'Магазини: {len(store_columns) + 1}']
    meta.extend([''] * (len(headers) - len(meta)))
    all_data.append(meta)

    all_data.append([''] * len(headers))
    all_data.append(headers)

    out_of_stock_cells = []

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

        store_prices_bgn = []

        for col_offset, store_key in enumerate(store_columns):
            store_data = product.get(store_key)
            col_index = STORE_COL_START + col_offset
            row_index = DATA_START_ROW - 1 + i

            if store_data:
                price_bgn = store_data.get("bgn")
                row.append(price_bgn if price_bgn else '')

                if price_bgn:
                    store_prices_bgn.append(price_bgn)

                if not store_data.get("in_stock", True):
                    out_of_stock_cells.append((row_index, col_index))
            else:
                row.append('')

        if store_prices_bgn:
            avg_bgn = round(sum(store_prices_bgn) / len(store_prices_bgn), 2)
            row.append(avg_bgn)
        else:
            avg_bgn = None
            row.append('')

        if avg_bgn and ref_bgn and ref_bgn > 0:
            deviation = round((avg_bgn - ref_bgn) / ref_bgn * 100, 1)
            row.append(f"{deviation}%")
        else:
            row.append('')

        matched_count = sum(1 for s in store_columns if product.get(s))
        row.append(f"{matched_count}/{len(store_columns)}")

        all_data.append(row)

    try:
        sheet.clear()
        sheet.update(values=all_data, range_name='A1')
        logger.info(f"Записани {len(all_data)} реда × {len(headers)} колони")
    except Exception as e:
        logger.error(f"Грешка при запис: {e}")
        return False

    # --- Форматиране ---
    try:
        last_row = HEADER_ROW + len(final_products)
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

        # Числов формат
        price_start = 3
        price_end = STORE_COL_START + len(store_columns) + 1
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

        # Ширини
        col_widths = {0: 35, 1: 250, 2: 55, 3: 75, 4: 75}
        for offset in range(len(store_columns)):
            col_widths[STORE_COL_START + offset] = 85
        col_widths[STORE_COL_START + len(store_columns)] = 75
        col_widths[STORE_COL_START + len(store_columns) + 1] = 65
        col_widths[STORE_COL_START + len(store_columns) + 2] = 55

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

        # Сиво форматиране за изчерпани
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

        if format_requests:
            sheet.spreadsheet.batch_update({"requests": format_requests})
            logger.info(f"Форматиране: {len(format_requests)} заявки")
            if out_of_stock_cells:
                logger.info(f"Сиво форматиране: {len(out_of_stock_cells)} изчерпани клетки")

        return True

    except Exception as e:
        logger.warning(f"Форматиране пропуснато (данните са записани): {e}")
        return True


# =============================================================================
# MAIN
# =============================================================================

async def main():
    logger.info("=" * 60)
    logger.info("EXP-003: CRAWL4AI v9.0.4 — 8 магазина + curl_cffi bypass")
    logger.info("=" * 60)
    logger.info(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Магазини: {len(STORES)}, BS4: {BS4_AVAILABLE}, "
                f"CapSolver: {CAPSOLVER_AVAILABLE}, curl_cffi: {CURL_CFFI_AVAILABLE}")
    if PROXY_URL:
        logger.info(f"Proxy: {PROXY_URL[:30]}...")

    if not CRAWL4AI_AVAILABLE:
        logger.error("Crawl4AI not available!")
        return

    total_start = time.time()

    # 1. Crawl — паралелно
    crawl_results = await crawl_all()

    # 2. Extract products
    logger.info("=" * 40 + " EXTRACTING " + "=" * 40)

    # Кашон (референтен)
    kashon_products = []
    if crawl_results.get("kashon", {}).get("success"):
        kashon_products = extract_kashon_products(crawl_results["kashon"]["markdown"])
        logger.info(f"Кашон: {len(kashon_products)} Harmonica products")

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
    if crawl_results.get("lilly", {}).get("success"):
        lilly_data = crawl_results["lilly"]
        lilly_products = extract_lilly_products(
            lilly_data["markdown"],
            html_text=lilly_data.get("html"),
        )
        logger.info(f"Lilly: {len(lilly_products)} Harmonica products")
        in_stock = sum(1 for p in lilly_products if p.get('in_stock', True))
        if in_stock < len(lilly_products):
            logger.info(f"  Налични: {in_stock}, Изчерпани: {len(lilly_products) - in_stock}")

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

    # VMV Supermarket
    vmv_products = []
    if crawl_results.get("vmv", {}).get("success"):
        vmv_data = crawl_results["vmv"]
        vmv_products = extract_vmv_products(
            vmv_data["markdown"],
            html_text=vmv_data.get("html"),
            brand_page=STORES["vmv"].get("brand_page", False),
        )
    elif crawl_results.get("vmv", {}).get("error"):
        logger.warning(f"VMV: {crawl_results['vmv']['error']}")

    # Optima
    optima_products = []
    optima_data = crawl_results.get("optima", {})
    if optima_data.get("success"):
        method = optima_data.get("method", "unknown")
        # WC Store API — продуктите са вече извлечени
        if optima_data.get("products"):
            optima_products = optima_data["products"]
        elif optima_data.get("html"):
            optima_products = extract_optima_products(
                optima_data.get("markdown", ""),
                html_text=optima_data.get("html"),
                brand_page=STORES["optima"].get("brand_page", False),
            )
        elif optima_data.get("markdown"):
            optima_products = extract_optima_products(
                optima_data["markdown"],
                brand_page=STORES["optima"].get("brand_page", False),
            )
        logger.info(f"Optima: {len(optima_products)} Harmonica products (method: {method})")
    elif optima_data.get("error"):
        logger.warning(f"Optima: {optima_data['error']}")

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

    # 3. Match products
    logger.info("=" * 40 + " MATCHING " + "=" * 40)

    # Динамично генериране на store keys (без reference)
    store_keys = [key for key, cfg in STORES.items() if not cfg.get("is_reference")]

    final_products = []
    for ref in kashon_products:
        product = {"name": ref["name"], "kashon": {"eur": ref["eur"], "bgn": ref["bgn"]}}
        for sk in store_keys:
            product[sk] = None
        final_products.append(product)

    # Всички магазини и техните продукти
    all_store_products = {
        "ebag": ebag_products,
        "balev": balev_products,
        "lilly": lilly_products,
        "dm": dm_products,
        "vmv": vmv_products,
        "optima": optima_products,
        "tmarket": tmarket_products,
    }

    for store_key, store_prods in all_store_products.items():
        if not store_prods:
            continue
        matches = match_products(kashon_products, store_prods)
        for product in final_products:
            if product["name"] in matches:
                m = matches[product["name"]]
                entry = {"eur": m["eur"], "bgn": m["bgn"]}
                if "in_stock" in m:
                    entry["in_stock"] = m["in_stock"]
                product[store_key] = entry

    # 4. Statistics
    logger.info("=" * 40 + " STATISTICS " + "=" * 40)
    kashon_count = len([p for p in final_products if p.get("kashon")])
    logger.info(f"Референтни (Кашон): {kashon_count}")

    store_counts = {}
    for sk in store_keys:
        count = len([p for p in final_products if p.get(sk)])
        store_counts[sk] = count
        if kashon_count:
            pct = count / kashon_count * 100
            extra = ""
            if sk == "lilly":
                oos = len([p for p in final_products
                           if p.get("lilly") and not p["lilly"].get("in_stock", True)])
                extra = f" — {oos} изчерпани"
                store_counts["lilly_oos"] = oos
            logger.info(f"{STORES[sk]['name']}: {count}/{kashon_count} ({pct:.0f}%){extra}")

    # Примерни продукти
    matched = [p for p in final_products
               if any(p.get(sk) for sk in store_keys)][:5]
    for p in matched:
        parts = [f"{p['name'][:50]}:"]
        for store in ["kashon"] + store_keys:
            if p.get(store):
                bgn = p[store].get('bgn')
                parts.append(f"  {store}={'%.2f' % bgn if bgn else 'N/A'}лв")
        logger.info(" ".join(parts))

    total_time = time.time() - total_start

    # 5. Write to Google Sheets
    stats = {"kashon_products": kashon_count}
    for sk in store_keys:
        stats[f"{sk}_matches"] = store_counts.get(sk, 0)
    stats["lilly_out_of_stock"] = store_counts.get("lilly_oos", 0)
    write_to_sheets(final_products, stats)

    # 6. Save JSON
    json_stats = {"kashon_products": kashon_count}
    for sk, prods in all_store_products.items():
        json_stats[f"{sk}_products"] = len(prods)
        json_stats[f"{sk}_matches"] = store_counts.get(sk, 0)
    json_stats["lilly_out_of_stock"] = store_counts.get("lilly_oos", 0)

    output = {
        "experiment": "EXP-003-v9.0.4",
        "date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "total_time": round(total_time, 2),
        "stores": len(STORES),
        "stats": json_stats,
        "products": final_products,
    }

    try:
        os.makedirs("experimental", exist_ok=True)
        with open("experimental/pilot_results.json", "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        logger.info("Резултати записани в experimental/pilot_results.json")
    except Exception as e:
        logger.error(f"Грешка при запис на JSON: {e}")

    logger.info(f"ГОТОВО за {total_time:.1f}s — {len(STORES)} магазина, "
                f"{kashon_count} референтни продукта")


if __name__ == "__main__":
    asyncio.run(main())
