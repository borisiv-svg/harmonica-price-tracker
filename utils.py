"""
Harmonica Price Tracker — Utilities
=====================================
Price extraction, name cleaning, food filtering, retry decorator.
"""

import asyncio
import functools
import re

from config import EUR_BGN_RATE, PRICE_RANGE_EUR, PRICE_RANGE_BGN, logger


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
    "гранола", "овесено",
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


# Продукти на Кашон страницата, които не са Harmonica бранд или не проследяваме
KASHON_BRAND_BLACKLIST = [
    "черноморски улов",
    # Bulk продукти (1.7 kg) — не се продават в retail магазините
    "червена леща 1.7",
    "микс от киноа 1.7",
    "боб мунг 1.7",
]

# Навигационни елементи от Кашон, които не са продукти
KASHON_JUNK_ENTRIES = [
    "frumbaya",
    "apply",
    "млечни",
    "месо",
    "пресни зеленчуци",
    "нови продукти",
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
# PRICE EXTRACTION
# =============================================================================

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
    """Извлича цена без валутен символ. Връща (price, 'BGN') или None.
    По-строг: игнорира числа, следвани от единица мярка (г, мл, g, ml, kg, %).
    """
    for match in re.finditer(r'(?:^|\s)(\d+)[,.](\d{2})(?=\s|$)', text):
        # Проверяваме дали НЕ е грамаж/процент (напр. "3.60%" или "400.00г")
        after = text[match.end():match.end()+5]
        if re.match(r'\s*(?:г|мл|ml|g|kg|кг|л|l|%|бр)', after, re.IGNORECASE):
            continue
        try:
            price = float(f"{match.group(1)}.{match.group(2)}")
            if PRICE_RANGE_BGN[0] <= price <= PRICE_RANGE_BGN[1]:
                return round(price, 2)
        except ValueError:
            pass
    return None


def clean_product_name(name):
    """Почиства име на продукт от markdown, URL-и, bold и префикси."""
    name = re.sub(r'!\[[^\]]*\]\([^\)]*\)', '', name)        # ![alt](url) -> "" (ПРЕДИ links!)
    name = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'\1', name)   # [text](url) -> text
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
