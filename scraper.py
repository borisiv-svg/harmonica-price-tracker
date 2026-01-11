"""
Harmonica Price Tracker v8.9
- Увеличен max_tokens за Фаза 1 (4000) за магазини с много продукти
- Retry логика за Фаза 2 - опит с Haiku ако Sonnet върне празен резултат
- Подобрено fallback търсене с fuzzy matching и Zelen продуктите
- Конфигурируем price_tolerance за магазини с различни ценови стратегии
- BeFit с разширен толеранс (70%) за промоционални цени
- Изчистване на форматирането преди прилагане на новото
"""

import os
import json
import re
import gc
import time
import smtplib
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from playwright.sync_api import sync_playwright
import gspread
from google.oauth2.service_account import Credentials

# Playwright Stealth за Cloudflare bypass
try:
    from playwright_stealth import stealth_sync
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False
    print("  [WARN] playwright-stealth не е инсталиран, Cloudflare сайтове може да не работят")

# Claude API
try:
    import anthropic
    CLAUDE_AVAILABLE = True
except ImportError:
    CLAUDE_AVAILABLE = False
    print("⚠ Anthropic библиотеката не е налична")

# =============================================================================
# КОНФИГУРАЦИЯ
# =============================================================================

# Фиксиран курс EUR/BGN (официален за еврозоната)
EUR_BGN_RATE = 1.95583
ALERT_THRESHOLD = 10

# Базова валута за сравнение - BGN (до юни 2026)
# След това може да се смени на EUR
BASE_CURRENCY = "BGN"

# Claude модели - хибриден подход за оптимална точност и скорост
# Фаза 1 (извличане): Haiku - бърз и евтин за парсване на HTML
# Фаза 2 (съпоставяне): Sonnet - по-точен за семантично разпознаване на продукти
# Визуална верификация: Haiku - достатъчно добър за разпознаване на опаковки
CLAUDE_MODEL_PHASE1 = "claude-haiku-4-5-20251001"      # Извличане на продукти от HTML
CLAUDE_MODEL_PHASE2 = "claude-sonnet-4-5-20250929"    # Семантично съпоставяне (Sonnet 4.5)
CLAUDE_MODEL_VISION = "claude-haiku-4-5-20251001"      # Визуална верификация

STORES = {
    "eBag": {
        "url": "https://www.ebag.bg/search/?products%5BrefinementList%5D%5Bbrand_name_bg%5D%5B0%5D=%D0%A5%D0%B0%D1%80%D0%BC%D0%BE%D0%BD%D0%B8%D0%BA%D0%B0",
        "name_in_sheet": "eBag",
        "scroll_times": 15,
        "has_pagination": False,
        "has_load_more": True,
        "load_more_selector": 'button:has-text("покажи повече"), button:has-text("Покажи повече"), .load-more-button, [data-testid="load-more"]',
        "expected_currency": "BGN",  # Все още показват лева
        "currency_indicators": ["лв", "лева", "BGN"]
    },
    "Kashon": {
        "url": "https://kashonharmonica.bg/bg/products/field_producer/harmonica-144",
        "name_in_sheet": "Кашон",
        "scroll_times": 15,
        "has_pagination": True,
        "max_pages": 5,  # Увеличено от 3 за пълно покритие
        "has_load_more": False,
        "expected_currency": "BGN",
        "currency_indicators": ["лв", "лева", "BGN"]
    },
    "Balev": {
        "url": "https://balevbiomarket.com/productBrands/harmonica",
        "name_in_sheet": "Balev",
        "scroll_times": 12,
        "has_pagination": False,
        "has_load_more": False,
        "expected_currency": "BGN",
        "currency_indicators": ["лв", "лева", "BGN"]
    },
    "Metro": {
        "url": "https://shop.metro.bg/shop/search?q=%D1%85%D0%B0%D1%80%D0%BC%D0%BE%D0%BD%D0%B8%D0%BA%D0%B0",
        "name_in_sheet": "Metro",
        "scroll_times": 15,
        "has_pagination": False,
        "has_load_more": False,
        "expected_currency": "BGN",
        "currency_indicators": ["лв", "лева", "BGN"]
    },
    "Zelen": {
        "url": "https://zelen.bg/brand/94/harmonica",
        "name_in_sheet": "Zelen",
        "scroll_times": 10,
        "has_pagination": False,
        "has_load_more": False,
        "expected_currency": "BGN",  # Показва EUR и BGN, но взимаме BGN
        "currency_indicators": ["лв", "лева", "BGN", "€", "EUR"]
    },
    "Randi": {
        "url": "https://randi.bg/search?search=harmonica",
        "name_in_sheet": "Randi",
        "scroll_times": 10,
        "has_pagination": True,
        "max_pages": 3,
        "pagination_param": "page",  # URL формат: ?search=harmonica&page=2
        "has_load_more": False,
        "expected_currency": "BGN",
        "currency_indicators": ["лв", "лева", "BGN"]
    },
    "BioMarket": {
        "url": "https://bio-market.bg/brand/harmonica",
        "name_in_sheet": "Bio-Market",
        "scroll_times": 10,
        "has_pagination": False,
        "has_load_more": False,
        "expected_currency": "BGN",
        "currency_indicators": ["лв", "лева", "BGN"]
    },
    "BeFit": {
        "url": "https://befit.bg/brands/harmonica",
        "name_in_sheet": "BeFit",
        "scroll_times": 10,
        "has_pagination": False,
        "has_load_more": False,
        "expected_currency": "BGN",
        "currency_indicators": ["лв", "лева", "BGN"],
        # BeFit често показва по-ниски цени (промоции) - разширен толеранс
        "price_tolerance": 0.70,  # 70% вместо стандартните 50%
        "note": "BeFit е фитнес магазин с по-агресивни промоции"
    },
    "Laika": {
        "url": "https://laika.bg/harmonica-bio-bulgaria-proizvodstvo-magi-maleeva-shoko-ghi-kefir-boza-koze-sirene-ovche-izvara-bulgarska-tzena-kade-da-kupia-magazin-online",
        "name_in_sheet": "Laika",
        "scroll_times": 10,
        "has_pagination": False,
        "has_load_more": False,
        "expected_currency": "BGN",
        "currency_indicators": ["лв", "лева", "BGN"]
    }
}

# Продукти с референтни цени от Balev Bio Market (27 продукта)
# Zelen продуктите (локум, бисквити) са разпределени равномерно в списъка
PRODUCTS = [
    # Референтни цени в BGN (основни) и EUR (информативни)
    {"id": 1, "name": "Био вафла с лимонов крем", "weight": "30г", "ref_price_bgn": 1.39, "ref_price_eur": 0.71},
    {"id": 2, "name": "Био вафла без добавена захар", "weight": "30г", "ref_price_bgn": 1.49, "ref_price_eur": 0.76},
    {"id": 3, "name": "Био сирене козе", "weight": "200г", "ref_price_bgn": 10.99, "ref_price_eur": 5.62},
    {"id": 4, "name": "Био лютеница Илиеви", "weight": "260г", "ref_price_bgn": 8.99, "ref_price_eur": 4.60},
    {"id": 5, "name": "Био кисело мляко 3,6%", "weight": "400г", "ref_price_bgn": 2.79, "ref_price_eur": 1.43},
    {"id": 6, "name": "Био лютеница Хаджиеви", "weight": "260г", "ref_price_bgn": 8.99, "ref_price_eur": 4.60},
    {"id": 7, "name": "Био пълнозърнест сусамов тахан", "weight": "700г", "ref_price_bgn": 18.79, "ref_price_eur": 9.61},
    {"id": 8, "name": "Био локум натурален", "weight": "140г", "ref_price_bgn": 4.28, "ref_price_eur": 2.19},  # Zelen продукт
    {"id": 9, "name": "Био кашкавал от краве мляко", "weight": "300г", "ref_price_bgn": 13.49, "ref_price_eur": 6.90},
    {"id": 10, "name": "Био крема сирене", "weight": "125г", "ref_price_bgn": 5.69, "ref_price_eur": 2.91},
    {"id": 11, "name": "Био вафла с лимец и кокос", "weight": "30г", "ref_price_bgn": 1.39, "ref_price_eur": 0.71},
    {"id": 12, "name": "Био краве сирене", "weight": "400г", "ref_price_bgn": 12.59, "ref_price_eur": 6.44},
    {"id": 13, "name": "Био пълнозърнести кори за баница", "weight": "400г", "ref_price_bgn": 7.99, "ref_price_eur": 4.09},
    {"id": 14, "name": "Био фъстъчено масло", "weight": "250г", "ref_price_bgn": 9.39, "ref_price_eur": 4.80},
    {"id": 15, "name": "Био локум роза", "weight": "140г", "ref_price_bgn": 4.28, "ref_price_eur": 2.19},  # Zelen продукт
    {"id": 16, "name": "Био слънчогледово масло", "weight": "500мл", "ref_price_bgn": 8.29, "ref_price_eur": 4.24},
    {"id": 17, "name": "Био тунквана вафла Chocobiotic", "weight": "40г", "ref_price_bgn": 2.29, "ref_price_eur": 1.17},
    {"id": 18, "name": "Био сироп от бъз", "weight": "750мл", "ref_price_bgn": 15.49, "ref_price_eur": 7.92},
    {"id": 19, "name": "Био прясно мляко 3,6%", "weight": "1л", "ref_price_bgn": 5.39, "ref_price_eur": 2.76},
    {"id": 20, "name": "Био солети от лимец", "weight": "50г", "ref_price_bgn": 2.59, "ref_price_eur": 1.32},
    {"id": 21, "name": "Био бисквити с масло и какао", "weight": "150г", "ref_price_bgn": 4.49, "ref_price_eur": 2.30},  # Zelen продукт
    {"id": 22, "name": "Био пълнозърнести солети", "weight": "60г", "ref_price_bgn": 2.09, "ref_price_eur": 1.07},
    {"id": 23, "name": "Био кисело пълномаслено мляко", "weight": "400г", "ref_price_bgn": 2.79, "ref_price_eur": 1.43},
    {"id": 24, "name": "Био извара", "weight": "500г", "ref_price_bgn": 3.69, "ref_price_eur": 1.89},
    {"id": 25, "name": "Био студено пресовано слънчогледово масло", "weight": "500мл", "ref_price_bgn": 8.29, "ref_price_eur": 4.24},
    {"id": 26, "name": "Био кисело мляко 2%", "weight": "400г", "ref_price_bgn": 2.79, "ref_price_eur": 1.43},
    {"id": 27, "name": "Био кефир", "weight": "500мл", "ref_price_bgn": 3.89, "ref_price_eur": 1.99},
]

# Визуални описания на продуктите за по-точна идентификация
# Тези описания помагат на Claude да разпознае продуктите по опаковката
PRODUCT_VISUAL_DESCRIPTIONS = {
    1: "Жълта опаковка вафла с лимонов крем, 30г",
    2: "Зелена опаковка вафла, надпис 'Без захар' или 'Sugar free', 30г",
    3: "Бяла опаковка козе сирене, 200г",
    4: "Буркан лютеница Илиеви, червен цвят, 260г",
    5: "Бяла пластмасова кутия кисело мляко 3.6%, 400г",
    6: "Буркан лютеница Хаджиеви, червен цвят, 260г",
    7: "Буркан сусамов тахан, 700г",
    8: "Опаковка локум натурален, 140г",  # Zelen продукт
    9: "Жълта опаковка кашкавал от краве мляко, 300г",
    10: "Бяла пластмасова кутийка крема сирене, 125г",
    11: "Кафява/бежова опаковка вафла с лимец и кокос, 30г",
    12: "Бяла опаковка краве сирене, 400г",
    13: "Опаковка пълнозърнести кори за баница, 400г",
    14: "Буркан фъстъчено масло, 250г",
    15: "Опаковка локум роза, 140г",  # Zelen продукт
    16: "Бутилка слънчогледово масло, 500мл",
    17: "Тунквана вафла Chocobiotic с шоколад и пробиотик, 40г",
    18: "Висока стъклена бутилка сироп от бъз, 750мл",
    19: "Кутия прясно мляко 3.6%, 1л",
    20: "Опаковка солети от лимец, 50г",
    21: "Опаковка бисквити с масло и какао, 150г",  # Zelen продукт
    22: "Опаковка пълнозърнести солети, 60г",
    23: "Бяла пластмасова кутия кисело пълномаслено мляко, 400г",
    24: "Бяла кутия извара, 500г",
    25: "Бутилка студено пресовано слънчогледово масло, 500мл",
    26: "Бяла пластмасова кутия кисело мляко 2%, 400г",
    27: "Бяла бутилка кефир, 500мл",
}

# Алтернативни имена на продукти за по-добро съпоставяне
# Кашон и други магазини използват различни наименования
PRODUCT_ALIASES = {
    16: [  # Био сироп от бъз
        "сироп от плод на бъз",
        "сироп бъз",
        "elderflower syrup",
        "сироп от бъз harmonica"
    ],
    19: [  # Био пълнозърнести солети
        "солети пълнозърнести",
        "пълнозърнести солети harmonica",
        "whole grain pretzels"
    ],
    20: [  # Био кисело пълномаслено мляко
        "по-кисело кисело мляко",
        "по-кисело мляко хармоника",
        "кисело мляко пълномаслено",
        "по-киселото мляко"
    ],
    5: [  # Био кисело мляко 3,6%
        "кисело мляко 3,6%",
        "кисело мляко 3.6%",
        "кисело мляко harmonica 3,6"
    ],
    23: [  # Био кисело мляко 2%
        "кисело мляко 2%",
        "кисело мляко 2.0%",
        "кисело мляко harmonica 2"
    ],
    11: [  # Био краве сирене
        "сирене краве",
        "краве сирене harmonica",
        "cow cheese"
    ],
    7: [  # Био пълнозърнест сусамов тахан
        "сусамов тахан",
        "тахан сусамов",
        "tahini",
        "тахан harmonica"
    ],
    22: [  # Био студено пресовано слънчогледово масло
        "слънчогледово олио за готвене",
        "био слънчогледово олио",
        "sunflower oil",
        "олио за готвене"
    ],
    21: [  # Био извара - ВНИМАНИЕ: да не се бърка с крема сирене!
        "извара harmonica",
        "извара био",
        "cottage cheese"
        # НЕ включваме "сирене" защото се бърка с крема сирене
    ],
}

# Продукти, които не се продават в определени магазини (потвърдено ръчно)
PRODUCTS_NOT_AVAILABLE = {
    "Kashon": [8, 16],  # Био кашкавал, Био сироп от бъз - не се продават в Кашон
}

# Флаг за включване/изключване на визуална верификация
ENABLE_VISUAL_VERIFICATION = True
VISUAL_VERIFICATION_CONFIDENCE_THRESHOLD = 0.7  # Минимална увереност за приемане


# =============================================================================
# ВАЛУТНА ДЕТЕКЦИЯ И КОНВЕРСИЯ
# =============================================================================

def detect_currency_from_text(text):
    """
    Детектира валутата от текст, търсейки индикатори за EUR или BGN.
    
    Логика:
    - Ако намери €, EUR, eur → връща "EUR"
    - Ако намери лв, лева, BGN, bgn → връща "BGN"
    - Ако не намери нищо → връща None (неизвестно)
    
    Args:
        text: Текст за анализ (може да е цял HTML или само ценова секция)
    
    Returns:
        "EUR", "BGN" или None
    """
    if not text:
        return None
    
    text_lower = text.lower()
    
    # EUR индикатори (по-често срещани след 01.01.2026)
    eur_indicators = ['€', 'eur', ' е ', 'евро']
    for indicator in eur_indicators:
        if indicator in text_lower:
            return "EUR"
    
    # BGN индикатори (legacy, все още възможни)
    bgn_indicators = ['лв', 'лева', 'bgn', 'лв.']
    for indicator in bgn_indicators:
        if indicator in text_lower:
            return "BGN"
    
    return None


def detect_currency_from_price_pattern(price_str):
    """
    Детектира валутата от ценови стринг анализирайки числовата стойност.
    
    Хевристика: Ако цената е твърде ниска за BGN (< 0.5), вероятно е EUR.
    Ако цената е твърде висока за EUR за обичаен продукт (> 50), вероятно е BGN.
    
    Това е backup метод когато няма явни валутни индикатори.
    """
    try:
        # Извличаме числото
        price_match = re.search(r'(\d+[.,]\d{2})', str(price_str))
        if price_match:
            price = float(price_match.group(1).replace(',', '.'))
            # Много ниска цена (< 0.5) е почти сигурно EUR
            if price < 0.5:
                return "EUR"
            # Много висока цена (> 50) е вероятно BGN за тези продукти
            if price > 50:
                return "BGN"
    except:
        pass
    return None


def convert_to_eur(price, detected_currency):
    """
    Конвертира цена към EUR ако е необходимо.
    
    Args:
        price: Числова стойност на цената
        detected_currency: "EUR", "BGN" или None
    
    Returns:
        Цена в EUR
    """
    if price is None:
        return None
    
    if detected_currency == "BGN":
        # Конвертираме BGN към EUR
        return round(price / EUR_BGN_RATE, 2)
    else:
        # Вече е EUR или неизвестно (приемаме EUR по подразбиране след 01.01.2026)
        return round(price, 2)


def convert_to_bgn(price, detected_currency):
    """
    Конвертира цена към BGN ако е необходимо.
    
    Args:
        price: Числова стойност на цената
        detected_currency: "EUR", "BGN" или None
    
    Returns:
        Цена в BGN
    """
    if price is None:
        return None
    
    if detected_currency == "EUR" or detected_currency is None:
        # Конвертираме EUR към BGN
        return round(price * EUR_BGN_RATE, 2)
    else:
        # Вече е BGN
        return round(price, 2)


def detect_currency_by_reference(price_value, ref_price_bgn):
    """
    Детектира валутата чрез сравнение с референтната BGN цена.
    
    Логика:
    - Изчисляваме очакваната EUR цена: ref_price_bgn / 1.95583
    - Ако извлечената цена е по-близка до BGN референцията → BGN
    - Ако извлечената цена е по-близка до EUR референцията → EUR
    
    Това е най-надеждният метод, защото не зависи от валутни символи.
    
    Args:
        price_value: Извлечената цена (число)
        ref_price_bgn: Референтната цена в BGN
    
    Returns:
        "EUR" или "BGN"
    """
    if price_value is None or ref_price_bgn is None:
        return "BGN"  # По подразбиране
    
    ref_price_eur = ref_price_bgn / EUR_BGN_RATE
    
    # Изчисляваме процентните отклонения
    deviation_bgn = abs(price_value - ref_price_bgn) / ref_price_bgn
    deviation_eur = abs(price_value - ref_price_eur) / ref_price_eur
    
    # Цената е в тази валута, от която отклонението е по-малко
    if deviation_eur < deviation_bgn:
        return "EUR"
    else:
        return "BGN"


def normalize_price_to_bgn(price_value, ref_price_bgn):
    """
    Нормализира цена към BGN, автоматично детектирайки валутата.
    
    Args:
        price_value: Извлечената цена
        ref_price_bgn: Референтната BGN цена за сравнение
    
    Returns:
        tuple: (price_in_bgn, detected_currency)
    """
    if price_value is None:
        return None, None
    
    detected = detect_currency_by_reference(price_value, ref_price_bgn)
    
    if detected == "EUR":
        price_bgn = round(price_value * EUR_BGN_RATE, 2)
    else:
        price_bgn = round(price_value, 2)
    
    return price_bgn, detected


def smart_price_normalization(price_value, page_text, store_config):
    """
    Интелигентна нормализация на цена.
    
    За преходния период до юни 2026:
    - Повечето сайтове все още показват BGN
    - Само ако има explicit EUR индикатор (€), конвертираме
    - По подразбиране приемаме BGN
    
    Args:
        price_value: Числова стойност на извлечената цена
        page_text: Пълен текст на страницата за контекст
        store_config: Конфигурация на магазина с expected_currency
    
    Returns:
        tuple: (price_in_bgn, detected_currency)
    """
    if price_value is None:
        return None, None
    
    # Метод 1: Търсим explicit валутни индикатори в текста
    detected = detect_currency_from_text(page_text)
    
    # Метод 2: Ако не намерихме explicit индикатор, използваме конфигурацията
    if detected is None:
        detected = store_config.get('expected_currency', 'BGN')
    
    # За преходния период: ако цената е разумна за BGN, приемаме BGN
    # Типичен диапазон за Harmonica продукти в BGN: 1-20 лв
    if detected == "EUR" and 1.0 <= price_value <= 25.0:
        # Цената изглежда като BGN, не като EUR
        # 0.71 EUR за вафла би било валидно, но 1.39 е по-вероятно BGN
        detected = "BGN"
    
    # Конвертираме към BGN ако е необходимо
    if detected == "EUR":
        price_bgn = round(price_value * EUR_BGN_RATE, 2)
    else:
        price_bgn = round(price_value, 2)
    
    return price_bgn, detected
# ВИЗУАЛНА ВЕРИФИКАЦИЯ С CLAUDE VISION
# =============================================================================

def capture_product_screenshot(page, product_selector, index=0):
    """
    Заснема screenshot на продуктова карта от страницата.
    
    Args:
        page: Playwright page обект
        product_selector: CSS селектор за продуктовите карти
        index: Индекс на продукта (ако има множество елементи)
    
    Returns:
        base64 encoded string на изображението или None при грешка
    """
    try:
        # Намираме всички продуктови карти
        elements = page.query_selector_all(product_selector)
        
        if not elements or index >= len(elements):
            return None
        
        element = elements[index]
        
        # Скролираме до елемента за да е видим
        element.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        
        # Заснемаме screenshot само на този елемент
        screenshot_bytes = element.screenshot()
        
        # Конвертираме в base64
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
        
        return screenshot_base64
        
    except Exception as e:
        print(f"      [VISION] Грешка при screenshot: {str(e)[:50]}")
        return None


def verify_product_with_vision(client, screenshot_base64, text_name, text_price, store_name):
    """
    Използва Claude Vision за верификация на продукт по снимка.
    
    Args:
        client: Anthropic клиент
        screenshot_base64: base64 encoded изображение
        text_name: Името на продукта от текста на сайта
        text_price: Цената от текста на сайта
        store_name: Име на магазина
    
    Returns:
        dict с:
            - product_id: Номер на съпоставения продукт (1-14) или None
            - confidence: Увереност (high/medium/low)
            - reason: Обяснение
    """
    if not client or not screenshot_base64:
        return {"product_id": None, "confidence": "none", "reason": "Липсва изображение или клиент"}
    
    # Създаваме списък с продуктите и визуалните им описания
    products_list = []
    for p in PRODUCTS:
        visual_desc = PRODUCT_VISUAL_DESCRIPTIONS.get(p['id'], '')
        products_list.append(str(p['id']) + ". " + p['name'] + " (" + p['weight'] + ") - " + visual_desc)
    
    products_text = "\n".join(products_list)
    
    prompt = """Анализирай изображението на продукт от магазин и определи кой точно продукт от списъка е.

ПРОДУКТИ ЗА ИДЕНТИФИКАЦИЯ:
""" + products_text + """

ТЕКСТ ОТ САЙТА: """ + text_name + """ - """ + str(text_price) + """ лв

ИНСТРУКЦИИ:
1. Разгледай ВИЗУАЛНАТА информация: опаковка, цветове, надписи, лого Harmonica
2. Сравни с описанията на продуктите
3. ГРАМАЖЪТ е критичен - 40г е различно от 30г!
4. Ако не си сигурен - върни null

ФОРМАТ (само JSON, без обяснения):
{"product_id": NUMBER_OR_NULL, "confidence": "high/medium/low", "reason": "кратко обяснение"}

Пример: {"product_id": 8, "confidence": "high", "reason": "Синя опаковка вафла Класика 40г"}"""
    
    try:
        message = client.messages.create(
            model=CLAUDE_MODEL_VISION,  # Haiku за визуална верификация
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": screenshot_base64
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }]
        )
        
        response_text = message.content[0].text.strip()
        
        # Парсване на JSON отговора
        # Почистваме евентуални markdown маркери
        cleaned = response_text
        if "```" in cleaned:
            cleaned = re.sub(r'```(?:json)?\s*', '', cleaned)
            cleaned = cleaned.replace('```', '').strip()
        
        # Намираме JSON обекта
        json_match = re.search(r'\{[^{}]+\}', cleaned)
        if json_match:
            result = json.loads(json_match.group())
            return result
        
        return {"product_id": None, "confidence": "none", "reason": "Неуспешно парсване"}
        
    except Exception as e:
        print(f"      [VISION] API грешка: {str(e)[:50]}")
        return {"product_id": None, "confidence": "none", "reason": str(e)[:50]}


def get_product_card_selectors(store_name):
    """
    Връща CSS селектори за продуктови карти според магазина.
    Подредени по приоритет - първо специфични, после общи.
    """
    selectors = {
        "eBag": [
            # eBag използва Tailwind CSS - article елементите са продуктовите карти
            "article",
            # Algolia InstantSearch специфични селектори (backup)
            ".ais-InfiniteHits-item",
            ".ais-Hits-item",
            "[data-insights-object-id]",
        ],
        "Кашон": [
            ".views-row",
            ".product-teaser", 
            ".node--type-product",
            "article.product",
        ],
        "Balev": [
            # Изключваме header/basket елементи - търсим в main content area
            "main [class*='product']",
            ".content [class*='product']",
            "#content [class*='product']",
            # Catalog/grid селектори
            ".catalog-item",
            ".product-tile",
        ],
        "Metro": [
            # Metro shop.metro.bg - модерна e-commerce платформа
            "[class*='product-card']",
            "[class*='product-tile']",
            "[class*='product-item']",
            "[data-testid*='product']",
            # Grid/list items
            ".search-results [class*='item']",
            ".products-list [class*='product']",
            "[class*='search-result'] [class*='product']",
            # Общи backup селектори
            "article[class*='product']",
            ".catalog-product",
        ]
    }
    return selectors.get(store_name, [".product-card", ".product-item"])


def debug_page_elements(page, store_name):
    """
    Debug функция за идентифициране на HTML елементи на страницата.
    Помага при намиране на правилните CSS селектори.
    """
    try:
        # Опитваме различни общи селектори
        test_selectors = [
            "article",
            "[class*='product']",
            "[class*='item']",
            "[class*='card']",
            "[class*='hit']",
            "li",
            "div[class]"
        ]
        
        print("      [DEBUG] Търсене на елементи за " + store_name + ":")
        
        for sel in test_selectors:
            try:
                elements = page.query_selector_all(sel)
                if elements and len(elements) > 0 and len(elements) < 200:
                    # Вземаме класовете на първия елемент
                    first_class = page.evaluate(
                        "(sel) => document.querySelector(sel)?.className || 'no-class'",
                        sel
                    )
                    print("        " + sel + ": " + str(len(elements)) + " елемента, class='" + str(first_class)[:50] + "'")
            except:
                continue
                
    except Exception as e:
        print("      [DEBUG] Грешка: " + str(e)[:50])


def validate_visual_price(product_id, visual_price, tolerance_percent=50):
    """
    Валидира дали визуално намерената цена е в разумен диапазон
    спрямо референтната цена на продукта.
    
    Args:
        product_id: ID на продукта (1-14)
        visual_price: Цената намерена визуално
        tolerance_percent: Допустимо отклонение в проценти (default 50%)
    
    Returns:
        tuple: (is_valid, reason)
    """
    # Намираме референтната цена
    ref_price = None
    for p in PRODUCTS:
        if p['id'] == product_id:
            ref_price = p['ref_price_bgn']
            break
    
    if not ref_price:
        return False, "Непознат продукт"
    
    if visual_price <= 0:
        return False, "Невалидна цена"
    
    # Изчисляваме отклонението
    deviation = abs(visual_price - ref_price) / ref_price * 100
    
    if deviation > tolerance_percent:
        return False, "Цена извън диапазон ({:.1f}% отклонение, ref={:.2f}, visual={:.2f})".format(
            deviation, ref_price, visual_price)
    
    return True, "OK"


def get_product_keywords(product_id):
    """
    Връща ключови думи за търсене на продукт по ID.
    Използва се за валидация на визуална идентификация.
    Актуализирано за 24 продукта (v7.1).
    """
    keywords = {
        1: ["вафла", "лимон", "крем", "30"],
        2: ["вафла", "без", "захар", "30"],
        3: ["козе", "сирене", "goat", "200"],
        4: ["лютеница", "илиев", "260"],
        5: ["кисело", "мляко", "3.6", "3,6", "400"],
        6: ["лютеница", "хаджиев", "260"],
        7: ["тахан", "сусам", "700"],
        8: ["кашкавал", "краве", "300"],
        9: ["крема", "сирене", "cream", "125"],
        10: ["вафла", "лимец", "кокос", "30"],
        11: ["краве", "сирене", "400"],
        12: ["кори", "баница", "400"],
        13: ["фъстъчено", "масло", "250"],
        14: ["слънчогледово", "масло", "500"],
        15: ["тунквана", "вафла", "chocobiotic", "40"],
        16: ["сироп", "бъз", "750"],
        17: ["прясно", "мляко", "1л", "1l"],
        18: ["солети", "лимец", "50"],
        19: ["пълнозърнести", "солети", "60"],
        20: ["пълномаслено", "кисело", "400"],
        21: ["извара", "500"],
        22: ["студено", "пресовано", "слънчогледово", "500"],
        23: ["кисело", "мляко", "2%", "400"],
        24: ["кефир", "500"],
    }
    return keywords.get(product_id, [])


def text_contains_product_keywords(text, product_id, min_matches=1):
    """
    Проверява дали текстът съдържа достатъчно ключови думи за продукта.
    
    Args:
        text: Текст за проверка
        product_id: ID на продукта
        min_matches: Минимален брой съвпадения
    
    Returns:
        bool: True ако има достатъчно съвпадения
    """
    text_lower = text.lower()
    keywords = get_product_keywords(product_id)
    
    matches = sum(1 for kw in keywords if kw.lower() in text_lower)
    return matches >= min_matches


def visual_verify_products(page, client, store_name, text_products, max_verify=5):
    """
    Визуално верифицира продукти чрез screenshots.
    
    Включва валидация на цените, филтриране по ключови думи,
    и филтриране на елементи по размер за по-точна идентификация.
    """
    if not ENABLE_VISUAL_VERIFICATION:
        return {}
    
    if not client:
        print("      [VISION] Claude клиент не е наличен")
        return {}
    
    verified = {}
    selectors = get_product_card_selectors(store_name)
    
    # Опитваме различни селектори
    product_elements = []
    used_selector = None
    for selector in selectors:
        try:
            elements = page.query_selector_all(selector)
            if elements and len(elements) > 0:
                # Филтрираме елементите по размер - продуктова карта е поне 80x80 пиксела
                valid_elements = []
                for el in elements:
                    try:
                        box = el.bounding_box()
                        if box and box['width'] >= 80 and box['height'] >= 80:
                            # Проверяваме дали елементът съдържа цена
                            text = el.inner_text()
                            if re.search(r'\d+[,.]\d{2}', text):
                                valid_elements.append(el)
                    except:
                        continue
                
                if valid_elements:
                    product_elements = valid_elements
                    used_selector = selector
                    print("      [VISION] Намерени " + str(len(valid_elements)) + " валидни продуктови карти с '" + selector + "'")
                    break
        except:
            continue
    
    if not product_elements:
        print("      [VISION] Не са намерени продуктови карти за screenshot")
        debug_page_elements(page, store_name)
        return {}
    
    # Верифицираме до max_verify продукта
    verified_count = 0
    skipped_price = 0
    skipped_keywords = 0
    
    for i, element in enumerate(product_elements):
        if verified_count >= max_verify:
            break
        
        try:
            # Заснемаме screenshot
            element.scroll_into_view_if_needed()
            page.wait_for_timeout(200)
            screenshot_bytes = element.screenshot()
            screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
            
            # Опитваме се да извлечем текста от елемента
            element_text = element.inner_text()
            
            # Подобрено извличане на цена - търсим различни формати
            # Формати: "2.99", "2,99", "2.99 лв", "2,99лв", "BGN 2.99"
            price = 0
            price_patterns = [
                r'(\d+)[,.](\d{2})\s*(?:лв|BGN|EUR)?',  # Стандартен формат
                r'(?:лв|BGN|EUR)\s*(\d+)[,.](\d{2})',   # Валута отпред
            ]
            for pattern in price_patterns:
                price_match = re.search(pattern, element_text)
                if price_match:
                    price = float(price_match.group(1) + "." + price_match.group(2))
                    break
            
            # Пропускаме ако няма цена
            if price == 0:
                continue
            
            # Извличаме име (първия ред с текст, който не е цена)
            lines = [l.strip() for l in element_text.split('\n') if l.strip()]
            product_name = "Неизвестен"
            for line in lines:
                if not re.match(r'^[\d,.]+\s*(лв|BGN|EUR)?$', line):
                    product_name = line
                    break
            
            # Верифицираме с Claude Vision
            result = verify_product_with_vision(
                client, 
                screenshot_base64, 
                product_name[:100],
                price, 
                store_name
            )
            
            # Логваме резултата ако няма разпознат продукт (за debug)
            if not result.get('product_id'):
                # Показваме само първите няколко неразпознати за да не спамим лога
                if i < 3:
                    reason = result.get('reason', 'няма причина')
                    print("      [VISION] Неразпознат: " + product_name[:30] + " (" + str(price) + " лв) - " + reason[:40])
                continue
            
            if result.get('confidence') not in ['high', 'medium']:
                if i < 3:
                    print("      [VISION] Ниска увереност за #" + str(result.get('product_id')) + ": " + result.get('confidence', 'none'))
                continue
            
            product_id = result['product_id']
            
            # ВАЛИДАЦИЯ 1: Проверка на цената
            price_valid, price_reason = validate_visual_price(product_id, price)
            if not price_valid:
                skipped_price += 1
                print("      [VISION] Отхвърлен #" + str(product_id) + ": " + price_reason[:50])
                continue
            
            # ВАЛИДАЦИЯ 2: Проверка на ключови думи (поне 1 съвпадение)
            if not text_contains_product_keywords(element_text, product_id, min_matches=1):
                skipped_keywords += 1
                print("      [VISION] Отхвърлен #" + str(product_id) + ": липсват ключови думи в текста")
                continue
            
            # Всичко е OK - добавяме към верифицираните
            verified[product_id] = {
                'price': price,
                'confidence': result.get('confidence'),
                'reason': result.get('reason', ''),
                'text_name': product_name[:50]
            }
            verified_count += 1
            print("      [VISION] #" + str(product_id) + ": " + result.get('confidence', '') + " - " + result.get('reason', '')[:40])
        
        except Exception as e:
            continue
    
    print("      [VISION] Верифицирани: " + str(len(verified)) + ", Отхвърлени (цена): " + str(skipped_price) + ", Отхвърлени (ключови думи): " + str(skipped_keywords))
    
    # Освобождаваме паметта след визуалната верификация
    gc.collect()
    
    return verified


# =============================================================================
# CLAUDE API - ДВУФАЗЕН АНАЛИЗ
# =============================================================================

def get_claude_client():
    """Създава Claude API клиент."""
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print("    [CLAUDE] API ключ не е зададен")
        return None
    try:
        return anthropic.Anthropic(api_key=api_key)
    except Exception as e:
        print(f"    [CLAUDE] Грешка при създаване на клиент: {str(e)[:50]}")
        return None


def phase1_extract_all_products(client, page_text, store_name):
    """
    ФАЗА 1: Груба екстракция
    Намира ВСИЧКИ ХРАНИТЕЛНИ продукти на Harmonica от текста.
    Връща списък с продукти точно както са изписани в сайта.
    """
    
    # Ограничаваме текста
    if len(page_text) > 14000:
        page_text = page_text[:14000]
    
    prompt = f"""Анализирай текста от българския онлайн магазин "{store_name}" и извлечи САМО ХРАНИТЕЛНИТЕ продукти на марката Harmonica (Хармоника) с техните цени.

ТЕКСТ ОТ СТРАНИЦАТА:
{page_text}

ИЗВЛИЧАЙ САМО ХРАНИ:
- Млечни продукти (айран, кисело мляко, сирене, крема сирене)
- Сладкарски изделия (локум, бисквити, вафли, топчета)
- Напитки (лимонада, сиропи)
- Консерви (пасирани домати, passata)
- Снаксове (претцели, smiles, чипс)

НЕ ИЗВЛИЧАЙ: дрехи, аксесоари, козметика, нехранителни продукти.

ИНСТРУКЦИИ:
1. Намери ХРАНИТЕЛНИ продукти на Harmonica/Хармоника
2. Извлечи ТОЧНОТО име + цена в лева (BGN)
3. Включи грамажа/обема

КРИТИЧНО - ФОРМАТ НА ОТГОВОРА:
- Върни САМО JSON масив
- БЕЗ ```json``` маркери
- БЕЗ обяснения преди или след JSON
- БЕЗ коментари
- Само чист JSON!

Пример за правилен отговор:
[{{"name": "Био Айран 500мл", "price": 2.99}}, {{"name": "Вафла класик 40г", "price": 2.19}}]

Ако няма продукти: []"""

    try:
        message = client.messages.create(
            model=CLAUDE_MODEL_PHASE1,
            max_tokens=4000,  # Увеличено от 2000 за магазини с много продукти (eBag: 57, Кашон: 64)
            messages=[{"role": "user", "content": prompt}]
        )
        
        response_text = message.content[0].text.strip()
        print(f"    [ФАЗА 1] Отговор: {response_text[:200]}...")
        
        # Почистване
        cleaned = response_text
        if "```" in cleaned:
            cleaned = re.sub(r'```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```', '', cleaned)
        
        # Търсим JSON масив
        array_match = re.search(r'\[[\s\S]*\]', cleaned)
        if array_match:
            cleaned = array_match.group(0)
        
        # Поправяме често срещани JSON грешки
        # 1. Trailing commas преди ] или }
        cleaned = re.sub(r',\s*]', ']', cleaned)
        cleaned = re.sub(r',\s*}', '}', cleaned)
        # 2. Single quotes вместо double quotes
        # (по-сложно, правим го само ако има грешка)
        
        try:
            products = json.loads(cleaned)
        except json.JSONDecodeError as e:
            print(f"    [ФАЗА 1] JSON грешка, опитваме поправка: {str(e)[:50]}")
            # Опитваме да поправим single quotes
            try:
                # Заменяме single quotes с double quotes (внимателно)
                fixed = re.sub(r"'([^']*)':", r'"\1":', cleaned)
                fixed = re.sub(r":\s*'([^']*)'", r': "\1"', fixed)
                products = json.loads(fixed)
            except:
                # Последен опит - извличаме продукти с regex
                print(f"    [ФАЗА 1] Използваме regex екстракция")
                products = []
                # Pattern 1: "price": число (без кавички)
                pattern1 = r'"name"\s*:\s*"([^"]+)"\s*,\s*"price"\s*:\s*(\d+\.?\d*)'
                matches = re.findall(pattern1, cleaned)
                for name, price in matches:
                    try:
                        products.append({"name": name, "price": float(price)})
                    except:
                        pass
                
                # Pattern 2: "price": "X.XX лв." (string с валутен символ)
                if not products:
                    pattern2 = r'"name"\s*:\s*"([^"]+)"\s*,\s*"price"\s*:\s*"(\d+[.,]?\d*)\s*(?:лв\.?|BGN|EUR|€)?"'
                    matches = re.findall(pattern2, cleaned)
                    for name, price in matches:
                        try:
                            price_clean = price.replace(',', '.')
                            products.append({"name": name, "price": float(price_clean)})
                        except:
                            pass
        
        # Валидираме структурата
        valid_products = []
        for p in products:
            if isinstance(p, dict) and 'name' in p and 'price' in p:
                try:
                    # Обработваме цената - може да е число или string
                    price_raw = p['price']
                    if isinstance(price_raw, str):
                        # Извличаме числото от string-а (напр. "4.28 лв." -> 4.28)
                        # Търсим десетично число или цяло число
                        price_match = re.search(r'(\d+)[.,](\d+)', price_raw)
                        if price_match:
                            # Десетично число: "4.28" или "4,28"
                            price = float(f"{price_match.group(1)}.{price_match.group(2)}")
                        else:
                            # Цяло число: "4"
                            int_match = re.search(r'(\d+)', price_raw)
                            if int_match:
                                price = float(int_match.group(1))
                            else:
                                continue
                    else:
                        price = float(price_raw)
                    
                    if 0.5 < price < 200:
                        valid_products.append({
                            "name": str(p['name']),
                            "price": price
                        })
                except:
                    pass
        
        print(f"    [ФАЗА 1] Намерени: {len(valid_products)} продукта")
        return valid_products
        
    except Exception as e:
        print(f"    [ФАЗА 1] Грешка: {str(e)[:80]}")
        return []


def phase2_match_products(client, extracted_products, store_name):
    """
    ФАЗА 2: Интелигентно съпоставяне
    Съпоставя намерените продукти от Фаза 1 с нашия списък.
    Използва номера на продуктите за еднозначна идентификация.
    ВАЖНО: НЕ показваме референтните цени на Claude, за да избегнем халюцинации!
    Актуализирано за 24 продукта (v7.1).
    """
    
    if not extracted_products:
        print(f"    [ФАЗА 2] Няма продукти за съпоставяне")
        return {}
    
    # Подготвяме списъка с нашите продукти - БЕЗ РЕФЕРЕНТНИ ЦЕНИ!
    our_products_text = "\n".join([
        f"{p['id']}. {p['name']} ({p['weight']})"
        for p in PRODUCTS
    ])
    
    # Подготвяме списъка с намерените продукти
    found_products_text = "\n".join([
        f"- \"{p['name']}\" → {p['price']:.2f} лв"
        for p in extracted_products
    ])
    
    prompt = f"""Съпостави продуктите от магазин "{store_name}" с нашия списък от 27 продукта.

НАШИЯТ СПИСЪК:
{our_products_text}

ПРОДУКТИ ОТ САЙТА:
{found_products_text}

ПРАВИЛА:
1. ГРАМАЖЪТ Е ЗАДЪЛЖИТЕЛЕН - "750мл" ≠ "500мл", "40г" ≠ "30г"
2. ВНИМАВАЙ ЗА ПОДОБНИ: "3.6%" ≠ "2%", "Илиеви" ≠ "Хаджиеви"
3. ИЗПОЛЗВАЙ САМО цени от списъка "ПРОДУКТИ ОТ САЙТА"
4. Ако не си 100% сигурен - ПРОПУСНИ

АЛТЕРНАТИВНИ ИМЕНА (разпознай ги като същите продукти):
- #8 "Локум натурален" = "Био Локум натурален" (140г)
- #15 "Локум роза" = "Локум със сироп от роза" (140г)
- #18 "Сироп от плод на бъз" = "Био сироп от бъз" (750мл)
- #21 "Обикновени бисквити с масло и какао" = "Био бисквити с масло и какао" (150г)
- #22 "Солети пълнозърнести" = "Био пълнозърнести солети" (60г)
- #23 "По-кисело кисело мляко" = "Био кисело пълномаслено мляко" (400г)
- #12 "Сирене краве" = "Био краве сирене" (400г)
- #7 "Тахан сусамов" = "Био пълнозърнест сусамов тахан" (700г)
- #25 "Слънчогледово олио за готвене" = "Био студено пресовано слънчогледово масло" (500мл)

ВНИМАНИЕ - НЕ БЪРКАЙ ТЕЗИ ПРОДУКТИ:
- #24 "Био извара" (500г, ~3.69лв) ≠ #10 "Био крема сирене" (125г, ~5.69лв)
- Извара е 500г, крема сирене е 125г - ГРАМАЖЪТ е ключов!

ПРИМЕРИ ЗА СЪВПАДЕНИЯ (v8.6 номерация):
#1=вафла+лимонов крем+30г, #2=вафла+без захар+30г, #3=козе сирене+200г
#4=лютеница+Илиеви+260г, #5=кисело мляко+3.6%+400г, #6=лютеница+Хаджиеви+260г
#7=тахан+сусамов+700г, #8=локум+натурален+140г, #9=кашкавал+краве+300г
#10=крема сирене+125г, #11=вафла+лимец+кокос+30г, #12=краве сирене+400г
#13=кори баница+400г, #14=фъстъчено масло+250г, #15=локум+роза+140г
#16=слънчогледово масло+500мл, #17=Chocobiotic+40г, #18=сироп бъз+750мл
#19=прясно мляко+1л, #20=солети лимец+50г, #21=бисквити+масло+какао+150г
#22=пълнозърнести солети+60г, #23=пълномаслено мляко+400г, #24=извара+500г
#25=студено пресовано масло+500мл, #26=кисело мляко+2%+400г, #27=кефир+500мл

КРИТИЧНО - ФОРМАТ НА ОТГОВОРА:
- Върни САМО JSON обект
- БЕЗ ```json``` маркери
- БЕЗ обяснения преди или след JSON
- БЕЗ коментари или текст
- Само чист JSON!

Пример за правилен отговор: {{"3": 10.99, "5": 2.79, "10": 5.69}}
Ако няма съвпадения: {{}}"""

    # Опитваме първо с предпочитания модел (Sonnet), с fallback към Haiku ако не е наличен
    model_to_use = CLAUDE_MODEL_PHASE2
    try:
        message = client.messages.create(
            model=model_to_use,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
    except Exception as model_error:
        # Ако Sonnet не е наличен (404), използваме Haiku като резервен вариант
        if "404" in str(model_error) or "not_found" in str(model_error):
            print(f"    [ФАЗА 2] Моделът {model_to_use} не е наличен, използваме Haiku...")
            model_to_use = CLAUDE_MODEL_PHASE1  # Fallback към Haiku
            message = client.messages.create(
                model=model_to_use,
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )
        else:
            raise model_error
    
    try:
        response_text = message.content[0].text.strip()
        print(f"    [ФАЗА 2] Отговор: {response_text[:150]}...")
        
        # Почистване
        cleaned = response_text
        if "```" in cleaned:
            cleaned = re.sub(r'```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```', '', cleaned)
        
        # Търсим JSON обект
        obj_match = re.search(r'\{[^{}]*\}', cleaned)
        if obj_match:
            cleaned = obj_match.group(0)
        
        matches = json.loads(cleaned)
        
        # Конвертираме номера към имена на продукти
        result = {}
        for product_id_str, price in matches.items():
            try:
                product_id = int(product_id_str)
                
                # Почистваме цената ако е текст (напр. "1.49 лв." или "1,49")
                if isinstance(price, str):
                    # Извличаме само числото от текста
                    price_match = re.search(r'(\d+)[.,](\d{1,2})', price)
                    if price_match:
                        price = float(f"{price_match.group(1)}.{price_match.group(2)}")
                    else:
                        # Опитваме да намерим цяло число
                        int_match = re.search(r'(\d+)', price)
                        if int_match:
                            price = float(int_match.group(1))
                        else:
                            continue
                else:
                    price = float(price)
                
                # Намираме продукта по ID
                product = next((p for p in PRODUCTS if p['id'] == product_id), None)
                if product:
                    # Валидираме цената - използваме толеранс от store config ако има
                    ref_price = product['ref_price_bgn']
                    store_config = STORES.get(store_name, {})
                    tolerance = store_config.get('price_tolerance', 0.50)  # По подразбиране 50%
                    min_valid = (1 - tolerance) * ref_price
                    max_valid = (1 + tolerance) * ref_price
                    if min_valid <= price <= max_valid:
                        result[product['name']] = price
                    else:
                        print(f"    [ФАЗА 2] Отхвърлена: #{product_id} цена {price:.2f} (валидно: {min_valid:.2f}-{max_valid:.2f})")
            except (ValueError, TypeError):
                continue
        
        print(f"    [ФАЗА 2] Съпоставени: {len(result)} продукта")
        return result
        
    except Exception as e:
        print(f"    [ФАЗА 2] Грешка: {str(e)[:80]}")
        return {}


def extract_prices_with_claude_two_phase(page_text, store_name):
    """
    Главна функция за двуфазно извличане на цени с Claude.
    Фаза 1: Груба екстракция на всички Harmonica продукти
    Фаза 2: Интелигентно съпоставяне с нашия списък
    """
    if not CLAUDE_AVAILABLE:
        return {}
    
    client = get_claude_client()
    if not client:
        return {}
    
    print(f"    [CLAUDE] Стартиране на двуфазен анализ...")
    
    # Фаза 1: Груба екстракция
    extracted = phase1_extract_all_products(client, page_text, store_name)
    
    if not extracted:
        return {}
    
    # Фаза 2: Съпоставяне с retry логика
    matched = phase2_match_products(client, extracted, store_name)
    
    # Retry: Ако Sonnet върна празен резултат и имаме поне 5 извлечени продукта,
    # опитваме отново с Haiku като fallback
    if len(matched) == 0 and len(extracted) >= 5:
        print(f"    [ФАЗА 2] Retry: Sonnet върна 0 резултата, опитваме с Haiku...")
        # Временно сменяме модела на Haiku
        original_model = globals().get('CLAUDE_MODEL_PHASE2')
        try:
            # Използваме директно Haiku за retry
            globals()['CLAUDE_MODEL_PHASE2'] = CLAUDE_MODEL_PHASE1
            matched = phase2_match_products(client, extracted, store_name)
            if len(matched) > 0:
                print(f"    [ФАЗА 2] Retry успешен: {len(matched)} продукта с Haiku")
        finally:
            # Възстановяваме оригиналния модел
            globals()['CLAUDE_MODEL_PHASE2'] = original_model
    
    return matched


# =============================================================================
# FALLBACK ТЪРСЕНЕ (резервен метод)
# =============================================================================

def fuzzy_match(text, pattern, threshold=0.7):
    """
    Прост fuzzy matching - връща True ако pattern се съдържа в text
    с позволени дребни разлики (транслитерация, малки/големи букви).
    """
    text = text.lower()
    pattern = pattern.lower()
    
    # Директно съвпадение
    if pattern in text:
        return True
    
    # Транслитерация вариации
    transliterations = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l',
        'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's',
        'т': 't', 'у': 'u', 'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch',
        'ш': 'sh', 'щ': 'sht', 'ъ': 'a', 'ь': '', 'ю': 'yu', 'я': 'ya'
    }
    
    # Конвертираме pattern към латиница
    pattern_latin = ''
    for char in pattern:
        pattern_latin += transliterations.get(char, char)
    
    if pattern_latin in text:
        return True
    
    return False


def extract_prices_with_fallback(page_text):
    """
    Резервен метод с ключови думи и fuzzy matching.
    Използва се само ако Claude не намери нищо.
    По-стриктен - изисква съвпадение на грамаж.
    Актуализирано за 27 продукта (v8.8) с Zelen продуктите.
    """
    prices = {}
    page_lower = page_text.lower()
    
    # Специфични ключови думи с грамаж за 27 продукта
    # Включени са алтернативни имена от различни магазини
    keywords_map = {
        "Био вафла с лимонов крем": [("вафла", "лимон", "30"), ("вафла", "крем", "30")],
        "Био вафла без добавена захар": [("вафла", "без", "захар", "30")],
        "Био сирене козе": [("козе", "сирене", "200"), ("goat", "cheese", "200")],
        "Био лютеница Илиеви": [("лютеница", "илиев", "260")],
        "Био кисело мляко 3,6%": [("кисело", "мляко", "3.6", "400"), ("кисело", "мляко", "3,6", "400")],
        "Био лютеница Хаджиеви": [("лютеница", "хаджиев", "260")],
        "Био пълнозърнест сусамов тахан": [("тахан", "сусам", "700"), ("tahini", "700")],
        # Zelen продукт #8 - Био локум натурален
        "Био локум натурален": [("локум", "натурален", "140"), ("локум", "natural", "140")],
        "Био кашкавал от краве мляко": [("кашкавал", "краве", "300")],
        "Био крема сирене": [("крема", "сирене", "125"), ("cream", "cheese", "125")],
        "Био вафла с лимец и кокос": [("вафла", "лимец", "кокос", "30")],
        "Био краве сирене": [("краве", "сирене", "400"), ("сирене", "краве", "400")],
        "Био пълнозърнести кори за баница": [("кори", "баница", "400")],
        "Био фъстъчено масло": [("фъстъчено", "масло", "250"), ("peanut", "butter", "250")],
        # Zelen продукт #15 - Био локум роза
        "Био локум роза": [("локум", "роза", "140"), ("локум", "rose", "140")],
        "Био слънчогледово масло": [("слънчогледово", "масло", "500"), ("слънчогледово", "олио", "500"), ("олио", "готвене", "500")],
        "Био тунквана вафла Chocobiotic": [("chocobiotic", "40"), ("тунквана", "вафла", "40")],
        # Сироп от бъз - Кашон го нарича "Сироп от плод на бъз"
        "Био сироп от бъз": [("сироп", "бъз", "750"), ("сироп", "плод", "бъз", "750")],
        "Био прясно мляко 3,6%": [("прясно", "мляко", "1л"), ("прясно", "мляко", "1l")],
        "Био солети от лимец": [("солети", "лимец", "50")],
        # Zelen продукт #21 - Био бисквити с масло и какао
        "Био бисквити с масло и какао": [("бисквити", "масло", "какао", "150"), ("бисквити", "какао", "150"), ("обикновени", "бисквити", "150")],
        # Пълнозърнести солети - Кашон го нарича "Солети пълнозърнести"
        "Био пълнозърнести солети": [("пълнозърнести", "солети", "60"), ("солети", "пълнозърнести", "60")],
        # Пълномаслено мляко - Кашон го нарича "По-кисело кисело мляко"
        "Био кисело пълномаслено мляко": [("пълномаслено", "мляко", "400"), ("по-кисело", "мляко", "400"), ("по-кисело", "кисело", "400")],
        # Извара - ВАЖНО: търсим "извара" БЕЗ "сирене" за да не се бърка с крема сирене
        "Био извара": [("извара", "500"), ("извара", "harmonica")],
        # Студено пресовано масло - различно от обикновеното слънчогледово
        "Био студено пресовано слънчогледово масло": [("студено", "пресовано", "500"), ("студено", "пресовано", "слънчогледово")],
        "Био кисело мляко 2%": [("кисело", "мляко", "2%", "400"), ("кисело", "мляко", "2.0", "400")],
        "Био кефир": [("кефир", "500")],
    }
    
    for product in PRODUCTS:
        name = product['name']
        ref_price = product['ref_price_bgn']
        keywords_list = keywords_map.get(name, [])
        
        for keywords in keywords_list:
            # Проверяваме дали ВСИЧКИ ключови думи са в текста (с fuzzy matching)
            all_found = all(
                kw in page_lower or fuzzy_match(page_lower, kw) 
                for kw in keywords
            )
            
            if not all_found:
                continue
            
            # Намираме позицията на първата ключова дума
            idx = page_lower.find(keywords[0])
            if idx == -1:
                # Опитваме с fuzzy
                for i, char in enumerate(page_lower):
                    if page_lower[i:i+len(keywords[0])] == keywords[0]:
                        idx = i
                        break
                if idx == -1:
                    continue
            
            # Извличаме контекст (по-голям за по-добро намиране на цена)
            context = page_text[max(0, idx-100):idx+200]
            
            # Търсим цена - избираме НАЙ-БЛИЗКАТА до референцията
            price_matches = re.findall(r'(\d+)[,.](\d{2})', context)
            best_price = None
            best_deviation = float('inf')
            
            for m in price_matches:
                try:
                    price = float(f"{m[0]}.{m[1]}")
                    # Проверка: ±50% от референтната (стеснен диапазон)
                    if 0.5 * ref_price <= price <= 1.5 * ref_price:
                        # Избираме цената с най-малко отклонение
                        deviation = abs(price - ref_price) / ref_price
                        if deviation < best_deviation:
                            best_deviation = deviation
                            best_price = price
                except:
                    continue
            
            if best_price is not None:
                prices[name] = best_price
            
            if name in prices:
                break
    
    return prices


# =============================================================================
# SCRAPING С ПОДОБРЕНО СКРОЛИРАНЕ
# =============================================================================

def scroll_for_all_products(page, scroll_times):
    """
    Подобрено скролиране за зареждане на всички продукти.
    Следи дали се появяват нови продукти при скролиране.
    Адаптирано за работа с изображения (когато визуална верификация е активна).
    """
    previous_height = 0
    no_change_count = 0
    
    # По-дълго чакане когато изображенията се зареждат
    wait_time = 800 if ENABLE_VISUAL_VERIFICATION else 500
    
    for i in range(scroll_times):
        # Скролираме
        page.evaluate("window.scrollBy(0, 800)")
        page.wait_for_timeout(wait_time)
        
        # Проверяваме дали страницата се е удължила
        current_height = page.evaluate("document.body.scrollHeight")
        
        if current_height == previous_height:
            no_change_count += 1
            # Ако 4 пъти няма промяна, спираме (увеличено от 3)
            if no_change_count >= 4:
                print("    Скролиране: спряно след " + str(i+1) + " опита (няма нови продукти)")
                break
        else:
            no_change_count = 0
            previous_height = current_height
    
    # Връщаме се в началото
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(300)


def click_load_more_until_done(page, selector, max_clicks=20):
    """
    Кликва върху бутона "покажи повече" докато вече не е наличен.
    Връща броя на успешните кликвания.
    """
    clicks = 0
    
    for i in range(max_clicks):
        # Скролираме до долу, за да се покаже бутонът
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1000)
        
        # Търсим бутона с различни селектори
        button = None
        selectors_to_try = [
            'button:has-text("покажи повече")',
            'button:has-text("Покажи повече")',
            'button:has-text("Show more")',
            '.ais-InfiniteHits-loadMore',
            '[class*="load-more"]',
            '[class*="loadMore"]',
            'button[class*="more"]'
        ]
        
        for sel in selectors_to_try:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    button = btn
                    break
            except:
                continue
        
        if not button:
            # Няма повече бутон - готово!
            if clicks > 0:
                print(f"    ✓ Заредени всички продукти след {clicks} клика")
            else:
                print(f"    Бутон 'покажи повече' не е намерен")
            break
        
        try:
            button.click()
            clicks += 1
            print(f"    Клик #{clicks} на 'покажи повече'...")
            page.wait_for_timeout(2000)  # Изчакваме зареждане
        except Exception as e:
            print(f"    Грешка при клик: {str(e)[:50]}")
            break
    
    # Връщаме се в началото
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(500)
    
    return clicks


def scrape_store(page, store_key, store_config, vision_client=None):
    """Извлича цени от един магазин с двуфазен Claude анализ, pagination, load-more и визуална верификация."""
    prices = {}
    url = store_config['url']
    store_name = store_config['name_in_sheet']
    scroll_times = store_config.get('scroll_times', 10)
    has_pagination = store_config.get('has_pagination', False)
    has_load_more = store_config.get('has_load_more', False)
    max_pages = store_config.get('max_pages', 1)
    all_body_text = ""
    
    print(f"\n{'='*60}")
    print(f"{store_name}: Зареждане")
    print(f"{'='*60}")
    
    # Определяме колко страници да заредим
    pages_to_load = max_pages if has_pagination else 1
    
    for page_num in range(pages_to_load):
        # Формираме URL-а за съответната страница
        if page_num == 0:
            current_url = url
        else:
            # Проверяваме дали URL-ът вече има query параметри
            if '?' in url:
                # URL вече има параметри (напр. ?search=harmonica), добавяме &page=N
                current_url = f"{url}&page={page_num + 1}"
            else:
                # URL няма параметри, добавяме ?page=N
                current_url = f"{url}?page={page_num}"
        
        if pages_to_load > 1:
            print(f"  Страница {page_num + 1}/{pages_to_load}...")
        
        try:
            page.goto(current_url, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            
            # Приемане на бисквитки (само на първата страница)
            if page_num == 0:
                cookie_selectors = [
                    'button:has-text("Приемам")',
                    'button:has-text("Разбрах")',
                    'button:has-text("Съгласен")',
                    'button:has-text("Accept")',
                    'button:has-text("OK")',
                    '.cc-btn',
                    '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll'
                ]
                for sel in cookie_selectors:
                    try:
                        btn = page.query_selector(sel)
                        if btn and btn.is_visible():
                            btn.click()
                            page.wait_for_timeout(1500)
                            print(f"  ✓ Бисквитки приети")
                            break
                    except:
                        pass
            
            # Зареждане на всички продукти - зависи от типа на сайта
            if has_load_more and page_num == 0:
                # eBag: кликаме "покажи повече" докато бутонът изчезне
                print(f"  Кликане на 'покажи повече' за зареждане на всички продукти...")
                click_load_more_until_done(page, store_config.get('load_more_selector', ''))
            else:
                # Стандартно скролиране
                if page_num == 0:
                    print(f"  Скролиране за зареждане на всички продукти...")
                scroll_for_all_products(page, scroll_times)
            
            page_text = page.inner_text('body')
            
            # Проверяваме дали страницата съдържа продукти (за странициране)
            if page_num > 0 and len(page_text) < 1000:
                print(f"    Страница {page_num + 1} е празна или няма повече продукти")
                break
            
            all_body_text += "\n" + page_text
            
            if page_num == 0:
                print(f"  Заредени {len(page_text)} символа")
            else:
                print(f"    +{len(page_text)} символа от страница {page_num + 1}")
            
        except Exception as e:
            print(f"  ✗ Грешка при зареждане на страница {page_num + 1}: {str(e)[:60]}")
            if page_num == 0:
                return prices  # Ако първата страница не се зареди, спираме
            # Ако е следваща страница, просто продължаваме
    
    body_text = all_body_text.strip()
    
    if has_pagination and pages_to_load > 1:
        print(f"  Общо заредени: {len(body_text)} символа от {pages_to_load} страници")
    
    # Debug: показваме малко от текста ако е твърде кратък
    if len(body_text) < 2000:
        print(f"  [DEBUG] Малко текст! Първи 300 символа:")
        print(f"  {body_text[:300]}")
    
    # Двуфазен Claude анализ
    try:
        claude_prices = extract_prices_with_claude_two_phase(body_text, store_name)
        print(f"  Claude (двуфазен): {len(claude_prices)} продукта")
        prices.update(claude_prices)
    except Exception as e:
        print(f"  Claude грешка: {str(e)[:50]}")
    
    # Fallback само за липсващи продукти
    try:
        print(f"  Fallback търсене...")
        fallback_prices = extract_prices_with_fallback(body_text)
        added = 0
        for name, price in fallback_prices.items():
            if name not in prices:
                prices[name] = price
                added += 1
        print(f"    Fallback добави: {added} продукта")
    except Exception as e:
        print(f"  Fallback грешка: {str(e)[:50]}")
    
    # Визуална верификация (ако е активирана и има клиент)
    if ENABLE_VISUAL_VERIFICATION and vision_client:
        try:
            print(f"  [VISION] Стартиране на визуална верификация...")
            
            # Връщаме се на първата страница за screenshots
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            
            # Ако има load_more, трябва да заредим продуктите отново
            if has_load_more:
                click_load_more_until_done(page, store_config.get('load_more_selector', ''), max_clicks=5)
            else:
                scroll_for_all_products(page, 5)
            
            # Верифицираме до 5 продукта визуално
            visual_results = visual_verify_products(page, vision_client, store_name, prices, max_verify=5)
            
            # Интегрираме резултатите
            visual_confirmed = 0
            visual_corrected = 0
            for product_id, visual_data in visual_results.items():
                product_name = None
                for p in PRODUCTS:
                    if p['id'] == product_id:
                        product_name = p['name']
                        break
                
                if product_name:
                    visual_price = visual_data.get('price')
                    text_price = prices.get(product_name)
                    
                    if text_price and visual_price:
                        # Проверяваме дали цените съвпадат (с толеранс от 5%)
                        diff_pct = abs(visual_price - text_price) / text_price * 100 if text_price > 0 else 100
                        if diff_pct < 5:
                            visual_confirmed += 1
                        else:
                            # Визуалната цена е различна - логваме за внимание
                            print(f"      [VISION] Разлика за #{product_id}: текст={text_price:.2f}, визуално={visual_price:.2f}")
                    elif visual_price and not text_price:
                        # Намерихме цена визуално, която липсваше от текста
                        prices[product_name] = visual_price
                        visual_corrected += 1
                        print(f"      [VISION] Добавен #{product_id} {product_name}: {visual_price:.2f} лв")
            
            if visual_confirmed > 0 or visual_corrected > 0:
                print(f"      [VISION] Потвърдени: {visual_confirmed}, Коригирани: {visual_corrected}")
                
        except Exception as e:
            print(f"  [VISION] Грешка: {str(e)[:50]}")
    
    print(f"  Общо намерени: {len(prices)} продукта")
    return prices


def collect_prices():
    """
    Събира цени от всички магазини с интелигентна валутна детекция.
    
    Процес:
    1. Скрейпва всеки магазин и запазва суровите цени
    2. Детектира валутата на всеки магазин от текста
    3. Нормализира всички цени към BGN (за преходния период)
    4. Изчислява средни стойности и отклонения спрямо BGN референцията
    
    ВАЖНО: Браузърът се рестартира между магазините за да освобождава памет
    и да предотврати "Page crashed" грешки при дълги сесии.
    
    За магазини с Cloudflare защита се използва playwright-stealth.
    """
    all_prices = {}
    store_currencies = {}
    store_raw_texts = {}
    
    # Обработваме всеки магазин с отделен браузър
    for key, config in STORES.items():
        store_name = config['name_in_sheet']
        needs_stealth = config.get('needs_stealth', False)
        
        try:
            with sync_playwright() as p:
                # За Cloudflare сайтове използваме различни настройки
                if needs_stealth:
                    browser = p.chromium.launch(
                        headless=True,
                        args=[
                            '--disable-blink-features=AutomationControlled',
                            '--disable-dev-shm-usage',
                            '--no-sandbox'
                        ]
                    )
                else:
                    browser = p.chromium.launch(headless=True)
                
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                    locale="bg-BG",
                    viewport={"width": 1920, "height": 1080},
                    java_script_enabled=True
                )
                
                if not ENABLE_VISUAL_VERIFICATION:
                    context.route("**/*.{png,jpg,jpeg,gif,webp,svg}", lambda r: r.abort())
                
                page = context.new_page()
                
                # Прилагаме stealth ако е наличен и необходим
                if needs_stealth and STEALTH_AVAILABLE:
                    stealth_sync(page)
                    print(f"  [STEALTH] Активиран за {store_name}")
                
                vision_client = None
                if ENABLE_VISUAL_VERIFICATION and CLAUDE_AVAILABLE:
                    vision_client = get_claude_client()
                    if key == list(STORES.keys())[0]:  # Само за първия магазин
                        print("  [VISION] Claude Vision активиран")
                
                prices = scrape_store(page, key, config, vision_client)
                
                try:
                    page_text = page.content()
                    store_raw_texts[key] = page_text
                    
                    detected_currency = detect_currency_from_text(page_text)
                    if detected_currency:
                        store_currencies[key] = detected_currency
                        print(f"  [ВАЛУТА] {store_name}: Детектирана {detected_currency}")
                    else:
                        store_currencies[key] = config.get('expected_currency', 'BGN')
                        print(f"  [ВАЛУТА] {store_name}: Приета {store_currencies[key]} (по подразбиране)")
                except:
                    store_currencies[key] = config.get('expected_currency', 'BGN')
                
                all_prices[key] = prices
                
                # Затваряме браузъра след всеки магазин
                context.close()
                browser.close()
            
            # Принудително освобождаване на паметта и кратка пауза
            gc.collect()
            time.sleep(2)
                
        except Exception as e:
            print(f"\n{'='*60}")
            print(f"{store_name}: Зареждане")
            print(f"{'='*60}")
            print(f"  ✗ Критична грешка: {str(e)[:80]}")
            all_prices[key] = {}
            store_currencies[key] = config.get('expected_currency', 'BGN')
    
    print("\n  [ВАЛУТА] Обобщение:")
    for store_key, currency in store_currencies.items():
        store_name = STORES[store_key]['name_in_sheet']
        print(f"    • {store_name}: {currency}")
    print()
    
    # Обработка на резултатите - нормализация на ниво продукт
    # Използваме референтната BGN цена за всеки продукт за да определим валутата
    results = []
    currency_corrections = {"EUR->BGN": 0, "BGN": 0}
    
    for product in PRODUCTS:
        name = product['name']
        ref_bgn = product['ref_price_bgn']
        ref_eur = product['ref_price_eur']
        
        # Събираме и нормализираме цените за този продукт
        normalized_prices = {}
        for store_key in STORES:
            raw_price = all_prices.get(store_key, {}).get(name)
            if raw_price is not None:
                # Детектираме валутата чрез сравнение с референтната цена
                detected = detect_currency_by_reference(raw_price, ref_bgn)
                if detected == "EUR":
                    normalized_prices[store_key] = round(raw_price * EUR_BGN_RATE, 2)
                    currency_corrections["EUR->BGN"] += 1
                else:
                    normalized_prices[store_key] = round(raw_price, 2)
                    currency_corrections["BGN"] += 1
            else:
                normalized_prices[store_key] = None
        
        valid_prices = [p for p in normalized_prices.values() if p is not None]
        
        if valid_prices:
            avg_bgn = sum(valid_prices) / len(valid_prices)
            avg_eur = avg_bgn / EUR_BGN_RATE
            # Отклонението се изчислява спрямо BGN референцията
            deviation = ((avg_bgn - ref_bgn) / ref_bgn) * 100
            status = "ВНИМАНИЕ" if abs(deviation) > ALERT_THRESHOLD else "OK"
        else:
            avg_bgn = avg_eur = deviation = None
            status = "НЯМА ДАННИ"
        
        results.append({
            "name": name,
            "weight": product['weight'],
            "ref_bgn": ref_bgn,
            "ref_eur": ref_eur,
            "prices": normalized_prices,  # Вече са нормализирани към BGN
            "avg_bgn": round(avg_bgn, 2) if avg_bgn else None,
            "avg_eur": round(avg_eur, 2) if avg_eur else None,
            "deviation": round(deviation, 1) if deviation is not None else None,
            "status": status
        })
    
    # Показваме статистика за валутните корекции
    print(f"  [ВАЛУТА] Корекции: {currency_corrections['EUR->BGN']} EUR→BGN, {currency_corrections['BGN']} BGN (без промяна)")
    
    return results


# =============================================================================
# GOOGLE SHEETS
# =============================================================================

def get_sheets_client():
    creds_json = os.environ.get('GOOGLE_CREDENTIALS')
    if not creds_json:
        raise ValueError("GOOGLE_CREDENTIALS не е зададена")
    
    creds_dict = json.loads(creds_json)
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)


def update_google_sheets(results):
    """
    Актуализира Google Sheets с резултатите.
    
    Формат v7.7: Двойна валутна поддръжка (BGN + EUR) за преходния период
    Колони: №, Продукт, Грамаж, Реф.BGN, Реф.EUR, eBag, Кашон, Balev, Metro, Ср.BGN, Ср.EUR, Откл.%, Статус
    """
    spreadsheet_id = os.environ.get('SPREADSHEET_ID')
    if not spreadsheet_id:
        print("SPREADSHEET_ID не е зададен")
        return
    
    try:
        gc = get_sheets_client()
        spreadsheet = gc.open_by_key(spreadsheet_id)
        
        try:
            sheet = spreadsheet.worksheet("Ценови Тракер")
        except:
            sheet = spreadsheet.add_worksheet("Ценови Тракер", rows=30, cols=15)
        
        sheet.clear()
        print("  Лист изчистен")
        
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        store_names = [s['name_in_sheet'] for s in STORES.values()]
        
        all_data = []
        
        # Ред 1: Заглавие
        all_data.append(['HARMONICA - Ценови Тракер v8.9', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', ''])
        
        # Ред 2: Метаданни
        all_data.append([
            f'Актуализация: {now}', '', 
            f'Курс: 1 EUR = {EUR_BGN_RATE} BGN', '',
            f'Магазини: {", ".join(store_names)}', '', '', '', '', '', '', '', '', '', '', '', '', ''
        ])
        
        # Ред 3: Празен
        all_data.append([''] * 18)
        
        # Ред 4: Заглавия (18 колони) - BGN е основна, 9 магазина
        headers = ['№', 'Продукт', 'Грамаж', 'Реф.BGN', 'Реф.EUR', 'eBag', 'Кашон', 'Balev', 'Metro', 'Zelen', 'Randi', 'Bio-Market', 'BeFit', 'Laika', 'Ср.BGN', 'Ср.EUR', 'Откл.%', 'Статус']
        all_data.append(headers)
        
        # Ред 5+: Данни
        for i, r in enumerate(results, 1):
            row = [
                i,
                r['name'],
                r['weight'],
                r['ref_bgn'],
                r['ref_eur'],
                r['prices'].get('eBag', '') or '',
                r['prices'].get('Kashon', '') or '',
                r['prices'].get('Balev', '') or '',
                r['prices'].get('Metro', '') or '',
                r['prices'].get('Zelen', '') or '',
                r['prices'].get('Randi', '') or '',
                r['prices'].get('BioMarket', '') or '',
                r['prices'].get('BeFit', '') or '',
                r['prices'].get('Laika', '') or '',
                r['avg_bgn'] if r['avg_bgn'] else '',
                r['avg_eur'] if r['avg_eur'] else '',
                f"{r['deviation']}%" if r['deviation'] is not None else '',
                r['status']
            ]
            all_data.append(row)
        
        sheet.update(values=all_data, range_name='A1')
        print(f"  ✓ Записани {len(all_data)} реда")
        
        # Форматиране v8.7 - 18 колони с 9 магазина
        # A=№, B=Продукт, C=Грамаж, D=Реф.BGN, E=Реф.EUR, F=eBag, G=Кашон, H=Balev, I=Metro, J=Zelen, K=Randi, L=Bio-Market, M=BeFit, N=Laika, O=Ср.BGN, P=Ср.EUR, Q=Откл.%, R=Статус
        try:
            last_row = 4 + len(results)
            format_requests = []
            
            # 0. ИЗЧИСТВАНЕ на форматирането за data редовете (ред 5 до края)
            # Това гарантира, че старо форматиране от предишни изпълнения няма да остане
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id, "startRowIndex": 4, "endRowIndex": last_row, "startColumnIndex": 0, "endColumnIndex": 18},
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 1, "green": 1, "blue": 1},
                            "textFormat": {"bold": False, "italic": False, "fontSize": 10, "foregroundColor": {"red": 0, "green": 0, "blue": 0}}
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat)"
                }
            })
            
            # 1. Заглавен ред (A1:R1) - тъмно зелено
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 18},
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 0.13, "green": 0.35, "blue": 0.22},
                            "textFormat": {"bold": True, "fontSize": 14, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                            "horizontalAlignment": "CENTER"
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"
                }
            })
            
            # 2. Метаданни ред (A2:R2) - светло зелено
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id, "startRowIndex": 1, "endRowIndex": 2, "startColumnIndex": 0, "endColumnIndex": 18},
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 0.92, "green": 0.97, "blue": 0.92},
                            "textFormat": {"italic": True, "fontSize": 10}
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat)"
                }
            })
            
            # 3. Заглавия колони A-E (№, Продукт, Грамаж, Реф.BGN, Реф.EUR) - базово зелено
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id, "startRowIndex": 3, "endRowIndex": 4, "startColumnIndex": 0, "endColumnIndex": 5},
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 0.2, "green": 0.5, "blue": 0.3},
                            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                            "horizontalAlignment": "CENTER"
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"
                }
            })
            
            # 4. Магазини заглавия F-N (9 магазина) - различни нюанси зелено
            store_colors = [
                (5, {"red": 0.56, "green": 0.77, "blue": 0.49}),   # F: eBag
                (6, {"red": 0.42, "green": 0.68, "blue": 0.42}),   # G: Кашон
                (7, {"red": 0.30, "green": 0.58, "blue": 0.35}),   # H: Balev
                (8, {"red": 0.20, "green": 0.48, "blue": 0.28}),   # I: Metro
                (9, {"red": 0.45, "green": 0.70, "blue": 0.55}),   # J: Zelen
                (10, {"red": 0.35, "green": 0.62, "blue": 0.45}),  # K: Randi
                (11, {"red": 0.50, "green": 0.73, "blue": 0.52}),  # L: Bio-Market
                (12, {"red": 0.40, "green": 0.65, "blue": 0.48}),  # M: BeFit
                (13, {"red": 0.32, "green": 0.60, "blue": 0.40}),  # N: Laika
            ]
            for col_idx, bg_color in store_colors:
                format_requests.append({
                    "repeatCell": {
                        "range": {"sheetId": sheet.id, "startRowIndex": 3, "endRowIndex": 4, "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1},
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": bg_color,
                                "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                                "horizontalAlignment": "CENTER"
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"
                    }
                })
            
            # 5. Обобщение заглавия O-R (Ср.BGN, Ср.EUR, Откл.%, Статус) - базово зелено
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id, "startRowIndex": 3, "endRowIndex": 4, "startColumnIndex": 14, "endColumnIndex": 18},
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": 0.2, "green": 0.5, "blue": 0.3},
                            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                            "horizontalAlignment": "CENTER"
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"
                }
            })
            
            # 6. Фон на магазин колоните (F-N, 9 магазина) - леки нюанси зелено
            store_data_colors = [
                (5, {"red": 0.92, "green": 0.97, "blue": 0.90}),   # F: eBag
                (6, {"red": 0.88, "green": 0.95, "blue": 0.87}),   # G: Кашон
                (7, {"red": 0.84, "green": 0.93, "blue": 0.84}),   # H: Balev
                (8, {"red": 0.80, "green": 0.91, "blue": 0.81}),   # I: Metro
                (9, {"red": 0.90, "green": 0.96, "blue": 0.88}),   # J: Zelen
                (10, {"red": 0.86, "green": 0.94, "blue": 0.85}),  # K: Randi
                (11, {"red": 0.88, "green": 0.95, "blue": 0.86}),  # L: Bio-Market
                (12, {"red": 0.84, "green": 0.93, "blue": 0.83}),  # M: BeFit
                (13, {"red": 0.82, "green": 0.92, "blue": 0.82}),  # N: Laika
            ]
            for col_idx, bg_color in store_data_colors:
                format_requests.append({
                    "repeatCell": {
                        "range": {"sheetId": sheet.id, "startRowIndex": 4, "endRowIndex": last_row, "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1},
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": bg_color,
                                "horizontalAlignment": "RIGHT"
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,horizontalAlignment)"
                    }
                })
            
            # 7. Подравняване на данните
            # A (№) - център
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id, "startRowIndex": 4, "endRowIndex": last_row, "startColumnIndex": 0, "endColumnIndex": 1},
                    "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                    "fields": "userEnteredFormat(horizontalAlignment)"
                }
            })
            # B (Продукт) - ляво
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id, "startRowIndex": 4, "endRowIndex": last_row, "startColumnIndex": 1, "endColumnIndex": 2},
                    "cell": {"userEnteredFormat": {"horizontalAlignment": "LEFT"}},
                    "fields": "userEnteredFormat(horizontalAlignment)"
                }
            })
            # C (Грамаж) - център
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id, "startRowIndex": 4, "endRowIndex": last_row, "startColumnIndex": 2, "endColumnIndex": 3},
                    "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                    "fields": "userEnteredFormat(horizontalAlignment)"
                }
            })
            # D-E (Реф.BGN, Реф.EUR) - дясно
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id, "startRowIndex": 4, "endRowIndex": last_row, "startColumnIndex": 3, "endColumnIndex": 5},
                    "cell": {"userEnteredFormat": {"horizontalAlignment": "RIGHT"}},
                    "fields": "userEnteredFormat(horizontalAlignment)"
                }
            })
            # O-Q (Ср.BGN, Ср.EUR, Откл.%) - дясно
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id, "startRowIndex": 4, "endRowIndex": last_row, "startColumnIndex": 14, "endColumnIndex": 17},
                    "cell": {"userEnteredFormat": {"horizontalAlignment": "RIGHT"}},
                    "fields": "userEnteredFormat(horizontalAlignment)"
                }
            })
            # R (Статус) - център
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id, "startRowIndex": 4, "endRowIndex": last_row, "startColumnIndex": 17, "endColumnIndex": 18},
                    "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                    "fields": "userEnteredFormat(horizontalAlignment)"
                }
            })
            
            # 8. Conditional formatting за статус
            ok_rows = []
            warning_rows = []
            no_data_rows = []
            
            for i, r in enumerate(results):
                row_idx = 4 + i
                if r['status'] == 'OK':
                    ok_rows.append(row_idx)
                elif r['status'] == 'ВНИМАНИЕ':
                    warning_rows.append(row_idx)
                else:
                    no_data_rows.append(row_idx)
            
            # OK редове - зелен статус (колона R=17)
            for row_idx in ok_rows:
                format_requests.append({
                    "repeatCell": {
                        "range": {"sheetId": sheet.id, "startRowIndex": row_idx, "endRowIndex": row_idx + 1, "startColumnIndex": 17, "endColumnIndex": 18},
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {"red": 0.85, "green": 0.95, "blue": 0.85},
                                "textFormat": {"bold": True, "foregroundColor": {"red": 0, "green": 0.5, "blue": 0}}
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat)"
                    }
                })
                # Средни цени O-P - светло зелено
                format_requests.append({
                    "repeatCell": {
                        "range": {"sheetId": sheet.id, "startRowIndex": row_idx, "endRowIndex": row_idx + 1, "startColumnIndex": 14, "endColumnIndex": 16},
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {"red": 0.9, "green": 0.97, "blue": 0.9},
                                "textFormat": {"foregroundColor": {"red": 0.1, "green": 0.4, "blue": 0.1}}
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat)"
                    }
                })
            
            # ВНИМАНИЕ редове - червен статус и фон
            for row_idx in warning_rows:
                # Статус R - червено
                format_requests.append({
                    "repeatCell": {
                        "range": {"sheetId": sheet.id, "startRowIndex": row_idx, "endRowIndex": row_idx + 1, "startColumnIndex": 17, "endColumnIndex": 18},
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {"red": 1, "green": 0.85, "blue": 0.85},
                                "textFormat": {"bold": True, "foregroundColor": {"red": 0.8, "green": 0, "blue": 0}}
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat)"
                    }
                })
                # Средни цени O-P - светло червено
                format_requests.append({
                    "repeatCell": {
                        "range": {"sheetId": sheet.id, "startRowIndex": row_idx, "endRowIndex": row_idx + 1, "startColumnIndex": 14, "endColumnIndex": 16},
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {"red": 1, "green": 0.92, "blue": 0.92},
                                "textFormat": {"foregroundColor": {"red": 0.7, "green": 0.1, "blue": 0.1}}
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat)"
                    }
                })
                # Откл.% Q - червен фон
                format_requests.append({
                    "repeatCell": {
                        "range": {"sheetId": sheet.id, "startRowIndex": row_idx, "endRowIndex": row_idx + 1, "startColumnIndex": 16, "endColumnIndex": 17},
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {"red": 1, "green": 0.92, "blue": 0.92},
                                "textFormat": {"bold": True, "foregroundColor": {"red": 0.7, "green": 0, "blue": 0}}
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat)"
                    }
                })
                # Ред A-E - лек червен фон
                format_requests.append({
                    "repeatCell": {
                        "range": {"sheetId": sheet.id, "startRowIndex": row_idx, "endRowIndex": row_idx + 1, "startColumnIndex": 0, "endColumnIndex": 5},
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {"red": 1, "green": 0.95, "blue": 0.95}
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor)"
                    }
                })
            
            # НЯМА ДАННИ редове - сиво
            for row_idx in no_data_rows:
                format_requests.append({
                    "repeatCell": {
                        "range": {"sheetId": sheet.id, "startRowIndex": row_idx, "endRowIndex": row_idx + 1, "startColumnIndex": 0, "endColumnIndex": 18},
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {"red": 0.95, "green": 0.95, "blue": 0.95},
                                "textFormat": {"italic": True, "foregroundColor": {"red": 0.5, "green": 0.5, "blue": 0.5}}
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat)"
                    }
                })
            
            # 9. Ширини на колоните (18 колони за 9 магазина)
            column_widths = [
                (0, 35),    # A: №
                (1, 270),   # B: Продукт
                (2, 60),    # C: Грамаж
                (3, 65),    # D: Реф.BGN
                (4, 65),    # E: Реф.EUR
                (5, 50),    # F: eBag
                (6, 50),    # G: Кашон
                (7, 50),    # H: Balev
                (8, 50),    # I: Metro
                (9, 50),    # J: Zelen
                (10, 50),   # K: Randi
                (11, 55),   # L: Bio-Market
                (12, 50),   # M: BeFit
                (13, 50),   # N: Laika
                (14, 60),   # O: Ср.BGN
                (15, 60),   # P: Ср.EUR
                (16, 55),   # Q: Откл.%
                (17, 80),   # R: Статус
            ]
            for col_idx, width in column_widths:
                format_requests.append({
                    "updateDimensionProperties": {
                        "range": {"sheetId": sheet.id, "dimension": "COLUMNS", "startIndex": col_idx, "endIndex": col_idx + 1},
                        "properties": {"pixelSize": width},
                        "fields": "pixelSize"
                    }
                })
            
            spreadsheet.batch_update({"requests": format_requests})
            print(f"  ✓ Форматиране приложено ({len(format_requests)} операции в 1 batch)")
            
        except Exception as e:
            print(f"  Форматиране предупреждение: {str(e)[:80]}")
        
        # История - годишни табове
        try:
            current_year = datetime.now().year
            history_tab_name = f"История_{current_year}"
            
            try:
                hist = spreadsheet.worksheet(history_tab_name)
            except:
                hist = spreadsheet.add_worksheet(history_tab_name, rows=2000, cols=18)
                hist.update(values=[['Дата', 'Час', 'Продукт', 'Грамаж', 'eBag', 'Кашон', 'Balev', 'Metro', 'Zelen', 'Randi', 'Bio-Market', 'BeFit', 'Laika', 'Ср.BGN', 'Ср.EUR', 'Откл.%', 'Статус']], range_name='A1')
                hist.freeze(rows=1)
                print(f"  ✓ Създаден нов таб '{history_tab_name}'")
            
            date_str = datetime.now().strftime("%d.%m.%Y")
            time_str = datetime.now().strftime("%H:%M")
            
            hist_rows = []
            for r in results:
                hist_rows.append([
                    date_str, time_str, r['name'], r['weight'],
                    r['prices'].get('eBag', '') or '',
                    r['prices'].get('Kashon', '') or '',
                    r['prices'].get('Balev', '') or '',
                    r['prices'].get('Metro', '') or '',
                    r['prices'].get('Zelen', '') or '',
                    r['prices'].get('Randi', '') or '',
                    r['prices'].get('BioMarket', '') or '',
                    r['prices'].get('BeFit', '') or '',
                    r['prices'].get('Laika', '') or '',
                    r['avg_bgn'] if r['avg_bgn'] else '',
                    r['avg_eur'] if r['avg_eur'] else '',
                    f"{r['deviation']}%" if r['deviation'] is not None else '',
                    r['status']
                ])
            
            hist.append_rows(hist_rows, value_input_option='USER_ENTERED')
            print(f"  ✓ {history_tab_name}: {len(hist_rows)} записа")
        except Exception as e:
            print(f"  История грешка: {str(e)[:50]}")
        
        print("\n✓ Google Sheets актуализиран")
        
    except Exception as e:
        print(f"\n✗ Грешка: {str(e)}")


# =============================================================================
# ИМЕЙЛ
# =============================================================================

def send_email_report(results, alerts):
    """
    Изпраща седмичен имейл отчет - винаги, независимо от резултатите.
    Използва HTML форматиране за по-добра четимост.
    """
    gmail_user = os.environ.get('GMAIL_USER')
    gmail_pass = os.environ.get('GMAIL_APP_PASSWORD')
    recipients = os.environ.get('ALERT_EMAIL', gmail_user)
    spreadsheet_id = os.environ.get('SPREADSHEET_ID', '')
    
    if not gmail_user or not gmail_pass:
        print("Gmail credentials не са зададени")
        return
    
    sheets_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}" if spreadsheet_id else ""
    date_str = datetime.now().strftime("%d.%m.%Y")
    time_str = datetime.now().strftime("%H:%M")
    
    # Статистики
    total_products = len(results)
    ok_count = len([r for r in results if r['status'] == 'OK'])
    warning_count = len(alerts)
    
    # Покритие по магазини
    store_coverage = {}
    for store_key, store_config in STORES.items():
        count = len([r for r in results if r['prices'].get(store_key)])
        store_coverage[store_config['name_in_sheet']] = count
    
    # Определяме темата на имейла
    if warning_count > 0:
        subject = f"Harmonica Price Tracker: {warning_count} продукта с отклонение над {ALERT_THRESHOLD}%"
    else:
        subject = f"Harmonica Price Tracker: Седмичен отчет - всички цени в норма"
    
    # HTML съдържание
    html_parts = []
    
    # Хедър
    html_parts.append("""
    <html>
    <head>
        <style>
            body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
            .header { background-color: #2e7d32; color: white; padding: 20px; text-align: center; }
            .header h1 { margin: 0; font-size: 24px; }
            .header p { margin: 5px 0 0 0; font-size: 14px; opacity: 0.9; }
            .summary { background-color: #f5f5f5; padding: 15px; margin: 20px 0; border-radius: 5px; }
            .summary h2 { color: #2e7d32; margin-top: 0; font-size: 18px; }
            .stats { display: flex; justify-content: space-around; text-align: center; margin: 15px 0; }
            .stat-box { padding: 10px 20px; }
            .stat-number { font-size: 28px; font-weight: bold; }
            .stat-label { font-size: 12px; color: #666; }
            .ok { color: #2e7d32; }
            .warning { color: #d32f2f; }
            .alert-section { background-color: #ffebee; border-left: 4px solid #d32f2f; padding: 15px; margin: 20px 0; }
            .alert-section h2 { color: #d32f2f; margin-top: 0; font-size: 18px; }
            .product-alert { background-color: white; padding: 12px; margin: 10px 0; border-radius: 4px; }
            .product-name { font-weight: bold; color: #333; font-size: 15px; }
            .product-details { color: #666; font-size: 13px; margin-top: 5px; }
            .deviation { font-weight: bold; }
            .deviation.positive { color: #d32f2f; }
            .deviation.negative { color: #2e7d32; }
            .coverage { margin: 20px 0; }
            .coverage h2 { color: #2e7d32; font-size: 18px; }
            .coverage-bar { background-color: #e0e0e0; height: 20px; border-radius: 10px; margin: 5px 0; overflow: hidden; }
            .coverage-fill { background-color: #4caf50; height: 100%; }
            .coverage-label { font-size: 13px; color: #666; }
            .footer { background-color: #f5f5f5; padding: 15px; margin-top: 20px; text-align: center; font-size: 12px; color: #666; border-top: 1px solid #ddd; }
            .button { display: inline-block; background-color: #2e7d32; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; margin: 10px 0; }
        </style>
    </head>
    <body>
    """)
    
    # Хедър секция
    html_parts.append(f"""
        <div class="header">
            <h1>HARMONICA Price Tracker</h1>
            <p>Седмичен отчет за {date_str}</p>
        </div>
    """)
    
    # Обобщение
    html_parts.append(f"""
        <div class="summary">
            <h2>Обобщение</h2>
            <div class="stats">
                <div class="stat-box">
                    <div class="stat-number">{total_products}</div>
                    <div class="stat-label">Продукта</div>
                </div>
                <div class="stat-box">
                    <div class="stat-number ok">{ok_count}</div>
                    <div class="stat-label">В норма</div>
                </div>
                <div class="stat-box">
                    <div class="stat-number warning">{warning_count}</div>
                    <div class="stat-label">С отклонение</div>
                </div>
            </div>
        </div>
    """)
    
    # Секция с alerts (ако има)
    if alerts:
        html_parts.append(f"""
        <div class="alert-section">
            <h2>Открити ценови отклонения над {ALERT_THRESHOLD}%</h2>
        """)
        
        for a in alerts:
            dev_class = "positive" if a['deviation'] > 0 else "negative"
            dev_sign = "+" if a['deviation'] > 0 else ""
            
            prices_text = []
            if a['prices'].get('eBag'): prices_text.append(f"eBag: {a['prices']['eBag']:.2f}")
            if a['prices'].get('Kashon'): prices_text.append(f"Кашон: {a['prices']['Kashon']:.2f}")
            if a['prices'].get('Balev'): prices_text.append(f"Balev: {a['prices']['Balev']:.2f}")
            if a['prices'].get('Metro'): prices_text.append(f"Metro: {a['prices']['Metro']:.2f}")
            
            html_parts.append(f"""
            <div class="product-alert">
                <div class="product-name">{a['name']} ({a['weight']})</div>
                <div class="product-details">
                    Референтна цена: <strong>{a['ref_bgn']:.2f} лв</strong> | 
                    Средна цена: <strong>{a['avg_bgn']:.2f} лв</strong> | 
                    Отклонение: <span class="deviation {dev_class}">{dev_sign}{a['deviation']:.1f}%</span>
                </div>
                <div class="product-details">{' | '.join(prices_text)} лв</div>
            </div>
            """)
        
        html_parts.append("</div>")
    else:
        html_parts.append("""
        <div class="summary" style="background-color: #e8f5e9; border-left: 4px solid #2e7d32;">
            <h2 style="color: #2e7d32;">Всички цени са в норма</h2>
            <p>Не са открити ценови отклонения над прага от 10%. Всички проследявани продукти се продават на цени, близки до референтните.</p>
        </div>
        """)
    
    # Покритие по магазини
    html_parts.append("""
        <div class="coverage">
            <h2>Покритие по магазини</h2>
    """)
    
    for store_name, count in store_coverage.items():
        percentage = (count / total_products) * 100
        html_parts.append(f"""
            <div class="coverage-label"><strong>{store_name}</strong>: {count}/{total_products} продукта ({percentage:.0f}%)</div>
            <div class="coverage-bar"><div class="coverage-fill" style="width: {percentage}%"></div></div>
        """)
    
    html_parts.append("</div>")
    
    # Бутон към Google Sheets
    if sheets_url:
        html_parts.append(f"""
        <div style="text-align: center; margin: 20px 0;">
            <a href="{sheets_url}" class="button">Отвори пълния отчет в Google Sheets</a>
        </div>
        """)
    
    # Футър
    html_parts.append(f"""
        <div class="footer">
            <p><strong>Harmonica Price Tracker v8.9</strong></p>
            <p>Това съобщение е автоматично генерирано на {date_str} в {time_str} ч.</p>
        </div>
    </body>
    </html>
    """)
    
    html_content = "".join(html_parts)
    
    # Изпращане
    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = gmail_user
        msg['To'] = recipients
        msg['Subject'] = subject
        
        # Добавяме HTML версия
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))
        
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(gmail_user, gmail_pass)
            server.send_message(msg)
        
        print(f"Имейл изпратен до {recipients}")
    except Exception as e:
        print(f"Имейл грешка: {str(e)[:50]}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("HARMONICA PRICE TRACKER v8.9")
    print("27 продукта, 9 магазина")
    print("Време: " + datetime.now().strftime('%d.%m.%Y %H:%M'))
    print("Продукти: " + str(len(PRODUCTS)))
    print("Магазини: " + str(len(STORES)))
    print("Базова валута: BGN")
    print("Claude API: " + ("Наличен" if CLAUDE_AVAILABLE else "Не е наличен"))
    if CLAUDE_AVAILABLE:
        print(f"  Фаза 1: {CLAUDE_MODEL_PHASE1.split('-')[1].capitalize()}")
        print(f"  Фаза 2: {CLAUDE_MODEL_PHASE2.split('-')[1].capitalize()} (с Haiku fallback)")
    print("Vision: " + ("Активна" if ENABLE_VISUAL_VERIFICATION else "Изключена"))
    print("Stealth: " + ("Наличен" if STEALTH_AVAILABLE else "Не е наличен"))
    print("=" * 60)
    
    results = collect_prices()
    update_google_sheets(results)
    
    alerts = [r for r in results if r['deviation'] and abs(r['deviation']) > ALERT_THRESHOLD]
    
    # Винаги изпращаме имейл отчет
    send_email_report(results, alerts)
    
    # Обобщение
    print("\n" + "="*60)
    print("ОБОБЩЕНИЕ")
    print("="*60)
    
    for k, cfg in STORES.items():
        found_products = [r for r in results if r['prices'].get(k)]
        missing_products = [r for r in results if not r['prices'].get(k)]
        cnt = len(found_products)
        print("  " + cfg['name_in_sheet'] + ": " + str(cnt) + "/" + str(len(results)) + " продукта")
        
        # Показваме липсващите продукти ако има такива
        if missing_products and cnt < len(results):
            missing_names = [f"#{r['name'][:30]}" for r in missing_products[:5]]
            print("    Липсват: " + ", ".join(missing_names))
            if len(missing_products) > 5:
                print(f"    ... и още {len(missing_products) - 5}")
    
    total = len([r for r in results if any(r['prices'].values())])
    ok_count = len([r for r in results if r['status'] == 'OK'])
    warning_count = len([r for r in results if r['status'] == 'ВНИМАНИЕ'])
    no_data = len([r for r in results if r['status'] == 'НЯМА ДАННИ'])
    
    print("\nОбщо покритие: " + str(total) + "/" + str(len(results)) + " продукта")
    print("Статус: " + str(ok_count) + " OK, " + str(warning_count) + " ВНИМАНИЕ, " + str(no_data) + " НЯМА ДАННИ")
    print("\nГотово!")


if __name__ == "__main__":
    main()
