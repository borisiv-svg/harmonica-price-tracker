"""
Harmonica Price Tracker v7.2
- 24 продукта от Balev като референция (разширен списък)
- 4 магазина: eBag, Кашон, Balev, T Market
- Stealth режим за T Market (Cloudflare bypass)
- Подобрено форматиране на Google Sheets
"""

import os
import json
import re
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
    print("⚠ playwright-stealth не е налична (pip install playwright-stealth)")

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

EUR_RATE = 1.95583
ALERT_THRESHOLD = 10

STORES = {
    "eBag": {
        "url": "https://www.ebag.bg/search/?products%5BrefinementList%5D%5Bbrand_name_bg%5D%5B0%5D=%D0%A5%D0%B0%D1%80%D0%BC%D0%BE%D0%BD%D0%B8%D0%BA%D0%B0",
        "name_in_sheet": "eBag",
        "scroll_times": 15,
        "has_pagination": False,
        "has_load_more": True,
        "load_more_selector": 'button:has-text("покажи повече"), button:has-text("Покажи повече"), .load-more-button, [data-testid="load-more"]'
    },
    "Kashon": {
        "url": "https://kashonharmonica.bg/bg/products/field_producer/harmonica-144",
        "name_in_sheet": "Кашон",
        "scroll_times": 15,
        "has_pagination": True,
        "max_pages": 3,
        "has_load_more": False
    },
    "Balev": {
        "url": "https://balevbiomarket.com/productBrands/harmonica",
        "name_in_sheet": "Balev",
        "scroll_times": 12,
        "has_pagination": False,
        "has_load_more": False
    },
    "TMarket": {
        "url": "https://tmarketonline.bg/vendor/harmonica-1881705916",
        "name_in_sheet": "T Market",
        "scroll_times": 10,
        "has_pagination": False,
        "has_load_more": False
    }
}

# Продукти с референтни цени от Balev Bio Market (24 продукта)
PRODUCTS = [
    {"id": 1, "name": "Био вафла с лимонов крем", "weight": "30г", "ref_price_bgn": 1.39, "ref_price_eur": 0.71},
    {"id": 2, "name": "Био вафла без добавена захар", "weight": "30г", "ref_price_bgn": 1.49, "ref_price_eur": 0.76},
    {"id": 3, "name": "Био сирене козе", "weight": "200г", "ref_price_bgn": 10.99, "ref_price_eur": 5.62},
    {"id": 4, "name": "Био лютеница Илиеви", "weight": "260г", "ref_price_bgn": 8.99, "ref_price_eur": 4.60},
    {"id": 5, "name": "Био кисело мляко 3,6%", "weight": "400г", "ref_price_bgn": 2.79, "ref_price_eur": 1.43},
    {"id": 6, "name": "Био лютеница Хаджиеви", "weight": "260г", "ref_price_bgn": 8.99, "ref_price_eur": 4.60},
    {"id": 7, "name": "Био пълнозърнест сусамов тахан", "weight": "700г", "ref_price_bgn": 18.79, "ref_price_eur": 9.61},
    {"id": 8, "name": "Био кашкавал от краве мляко", "weight": "300г", "ref_price_bgn": 13.49, "ref_price_eur": 6.90},
    {"id": 9, "name": "Био крема сирене", "weight": "125г", "ref_price_bgn": 5.69, "ref_price_eur": 2.91},
    {"id": 10, "name": "Био вафла с лимец и кокос", "weight": "30г", "ref_price_bgn": 1.39, "ref_price_eur": 0.71},
    {"id": 11, "name": "Био краве сирене", "weight": "400г", "ref_price_bgn": 12.59, "ref_price_eur": 6.44},
    {"id": 12, "name": "Био пълнозърнести кори за баница", "weight": "400г", "ref_price_bgn": 7.99, "ref_price_eur": 4.09},
    {"id": 13, "name": "Био фъстъчено масло", "weight": "250г", "ref_price_bgn": 9.39, "ref_price_eur": 4.80},
    {"id": 14, "name": "Био слънчогледово масло", "weight": "500мл", "ref_price_bgn": 8.29, "ref_price_eur": 4.24},
    {"id": 15, "name": "Био тунквана вафла Chocobiotic", "weight": "40г", "ref_price_bgn": 2.29, "ref_price_eur": 1.17},
    {"id": 16, "name": "Био сироп от бъз", "weight": "750мл", "ref_price_bgn": 15.49, "ref_price_eur": 7.92},
    {"id": 17, "name": "Био прясно мляко 3,6%", "weight": "1л", "ref_price_bgn": 5.39, "ref_price_eur": 2.76},
    {"id": 18, "name": "Био солети от лимец", "weight": "50г", "ref_price_bgn": 2.59, "ref_price_eur": 1.32},
    {"id": 19, "name": "Био пълнозърнести солети", "weight": "60г", "ref_price_bgn": 2.09, "ref_price_eur": 1.07},
    {"id": 20, "name": "Био кисело пълномаслено мляко", "weight": "400г", "ref_price_bgn": 2.79, "ref_price_eur": 1.43},
    {"id": 21, "name": "Био извара", "weight": "500г", "ref_price_bgn": 3.69, "ref_price_eur": 1.89},
    {"id": 22, "name": "Био студено пресовано слънчогледово масло", "weight": "500мл", "ref_price_bgn": 8.29, "ref_price_eur": 4.24},
    {"id": 23, "name": "Био кисело мляко 2%", "weight": "400г", "ref_price_bgn": 2.79, "ref_price_eur": 1.43},
    {"id": 24, "name": "Био кефир", "weight": "500мл", "ref_price_bgn": 3.89, "ref_price_eur": 1.99},
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
    8: "Жълта опаковка кашкавал от краве мляко, 300г",
    9: "Бяла пластмасова кутийка крема сирене, 125г",
    10: "Кафява/бежова опаковка вафла с лимец и кокос, 30г",
    11: "Бяла опаковка краве сирене, 400г",
    12: "Опаковка пълнозърнести кори за баница, 400г",
    13: "Буркан фъстъчено масло, 250г",
    14: "Бутилка слънчогледово масло, 500мл",
    15: "Тунквана вафла Chocobiotic с шоколад и пробиотик, 40г",
    16: "Висока стъклена бутилка сироп от бъз, 750мл",
    17: "Кутия прясно мляко 3.6%, 1л",
    18: "Опаковка солети от лимец, 50г",
    19: "Опаковка пълнозърнести солети, 60г",
    20: "Бяла пластмасова кутия кисело пълномаслено мляко, 400г",
    21: "Бяла кутия извара, 500г",
    22: "Бутилка студено пресовано слънчогледово масло, 500мл",
    23: "Бяла пластмасова кутия кисело мляко 2%, 400г",
    24: "Бяла бутилка кефир, 500мл",
}

# Флаг за включване/изключване на визуална верификация
ENABLE_VISUAL_VERIFICATION = True
VISUAL_VERIFICATION_CONFIDENCE_THRESHOLD = 0.7  # Минимална увереност за приемане


# =============================================================================
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
            model="claude-haiku-4-5-20251001",
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
        "T Market": [
            # CloudCart платформа - продуктови карти
            "[class*='product-card']",
            "[class*='product-item']",
            ".card.product",
            # Grid items
            "[class*='col-'] [class*='product']",
            ".products-grid .item",
            # Общи backup селектори
            "article.product",
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
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
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
                # Търсим pattern: "name": "...", "price": X.XX
                pattern = r'"name"\s*:\s*"([^"]+)"\s*,\s*"price"\s*:\s*(\d+\.?\d*)'
                matches = re.findall(pattern, cleaned)
                for name, price in matches:
                    try:
                        products.append({"name": name, "price": float(price)})
                    except:
                        pass
        
        # Валидираме структурата
        valid_products = []
        for p in products:
            if isinstance(p, dict) and 'name' in p and 'price' in p:
                try:
                    price = float(p['price'])
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
    
    prompt = f"""Съпостави продуктите от магазин "{store_name}" с нашия списък от 24 продукта.

НАШИЯТ СПИСЪК:
{our_products_text}

ПРОДУКТИ ОТ САЙТА:
{found_products_text}

ПРАВИЛА:
1. ГРАМАЖЪТ Е ЗАДЪЛЖИТЕЛЕН - "750мл" ≠ "500мл", "40г" ≠ "30г"
2. ВНИМАВАЙ ЗА ПОДОБНИ: "3.6%" ≠ "2%", "Илиеви" ≠ "Хаджиеви"
3. ИЗПОЛЗВАЙ САМО цени от списъка "ПРОДУКТИ ОТ САЙТА"
4. Ако не си 100% сигурен - ПРОПУСНИ

ПРИМЕРИ ЗА СЪВПАДЕНИЯ:
#1=вафла+лимонов крем+30г, #2=вафла+без захар+30г, #3=козе сирене+200г
#4=лютеница+Илиеви+260г, #5=кисело мляко+3.6%+400г, #6=лютеница+Хаджиеви+260г
#7=тахан+сусамов+700г, #8=кашкавал+краве+300г, #9=крема сирене+125г
#10=вафла+лимец+кокос+30г, #11=краве сирене+400г, #12=кори баница+400г
#13=фъстъчено масло+250г, #14=слънчогледово масло+500мл, #15=Chocobiotic+40г
#16=сироп бъз+750мл, #17=прясно мляко+1л, #18=солети лимец+50г
#19=пълнозърнести солети+60г, #20=пълномаслено мляко+400г, #21=извара+500г
#22=студено пресовано масло+500мл, #23=кисело мляко+2%+400г, #24=кефир+500мл

КРИТИЧНО - ФОРМАТ НА ОТГОВОРА:
- Върни САМО JSON обект
- БЕЗ ```json``` маркери
- БЕЗ обяснения преди или след JSON
- БЕЗ коментари или текст
- Само чист JSON!

Пример за правилен отговор: {{"3": 10.99, "5": 2.79, "9": 5.69}}
Ако няма съвпадения: {{}}"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        
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
                price = float(price)
                
                # Намираме продукта по ID
                product = next((p for p in PRODUCTS if p['id'] == product_id), None)
                if product:
                    # Валидираме цената (±50% от референтната - по-строго!)
                    ref_price = product['ref_price_bgn']
                    min_valid = 0.5 * ref_price
                    max_valid = 1.5 * ref_price
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
    
    # Фаза 2: Съпоставяне
    matched = phase2_match_products(client, extracted, store_name)
    
    return matched


# =============================================================================
# FALLBACK ТЪРСЕНЕ (резервен метод)
# =============================================================================

def extract_prices_with_fallback(page_text):
    """
    Резервен метод с ключови думи.
    Използва се само ако Claude не намери нищо.
    По-стриктен - изисква съвпадение на грамаж.
    Актуализирано за 24 продукта (v7.1).
    """
    prices = {}
    page_lower = page_text.lower()
    
    # Специфични ключови думи с грамаж за 24 продукта
    keywords_map = {
        "Био вафла с лимонов крем": [("вафла", "лимон", "30"), ("вафла", "крем", "30")],
        "Био вафла без добавена захар": [("вафла", "без", "захар", "30")],
        "Био сирене козе": [("козе", "сирене", "200"), ("goat", "cheese", "200")],
        "Био лютеница Илиеви": [("лютеница", "илиев", "260")],
        "Био кисело мляко 3,6%": [("кисело", "мляко", "3.6", "400"), ("кисело", "мляко", "3,6", "400")],
        "Био лютеница Хаджиеви": [("лютеница", "хаджиев", "260")],
        "Био пълнозърнест сусамов тахан": [("тахан", "сусам", "700"), ("tahini", "700")],
        "Био кашкавал от краве мляко": [("кашкавал", "краве", "300")],
        "Био крема сирене": [("крема", "сирене", "125"), ("cream", "cheese", "125")],
        "Био вафла с лимец и кокос": [("вафла", "лимец", "кокос", "30")],
        "Био краве сирене": [("краве", "сирене", "400")],
        "Био пълнозърнести кори за баница": [("кори", "баница", "400")],
        "Био фъстъчено масло": [("фъстъчено", "масло", "250"), ("peanut", "butter", "250")],
        "Био слънчогледово масло": [("слънчогледово", "масло", "500")],
        "Био тунквана вафла Chocobiotic": [("chocobiotic", "40"), ("тунквана", "вафла", "40")],
        "Био сироп от бъз": [("сироп", "бъз", "750")],
        "Био прясно мляко 3,6%": [("прясно", "мляко", "1л"), ("прясно", "мляко", "1l")],
        "Био солети от лимец": [("солети", "лимец", "50")],
        "Био пълнозърнести солети": [("пълнозърнести", "солети", "60")],
        "Био кисело пълномаслено мляко": [("пълномаслено", "мляко", "400")],
        "Био извара": [("извара", "500")],
        "Био студено пресовано слънчогледово масло": [("студено", "пресовано", "500")],
        "Био кисело мляко 2%": [("кисело", "мляко", "2%", "400")],
        "Био кефир": [("кефир", "500")],
    }
    
    for product in PRODUCTS:
        name = product['name']
        ref_price = product['ref_price_bgn']
        keywords_list = keywords_map.get(name, [])
        
        for keywords in keywords_list:
            # Проверяваме дали ВСИЧКИ ключови думи са в текста
            all_found = all(kw in page_lower for kw in keywords)
            
            if not all_found:
                continue
            
            # Намираме позицията на първата ключова дума
            idx = page_lower.find(keywords[0])
            if idx == -1:
                continue
            
            # Извличаме контекст
            context = page_text[max(0, idx-80):idx+150]
            
            # Търсим цена
            price_matches = re.findall(r'(\d+)[,.](\d{2})', context)
            for m in price_matches:
                try:
                    price = float(f"{m[0]}.{m[1]}")
                    # Стриктна проверка: ±60% от референтната
                    if 0.4 * ref_price <= price <= 1.6 * ref_price:
                        prices[name] = price
                        break
                except:
                    continue
            
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
            # Кашон използва ?page=N (0-indexed: page=0 е първа, page=1 е втора)
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
    """Събира цени от всички магазини. Използва stealth режим за T Market."""
    all_prices = {}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        # Стандартен контекст за повечето магазини
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            locale="bg-BG",
            viewport={"width": 1920, "height": 1080}
        )
        
        # Блокираме изображения САМО ако визуалната верификация е изключена
        if not ENABLE_VISUAL_VERIFICATION:
            context.route("**/*.{png,jpg,jpeg,gif,webp,svg}", lambda r: r.abort())
        
        page = context.new_page()
        
        # Създаваме Claude клиент за визуална верификация
        vision_client = None
        if ENABLE_VISUAL_VERIFICATION and CLAUDE_AVAILABLE:
            vision_client = get_claude_client()
            if vision_client:
                print("  [VISION] Claude Vision активиран")
        
        for key, config in STORES.items():
            # За T Market използваме stealth режим
            if key == "TMarket" and STEALTH_AVAILABLE:
                print("  [STEALTH] Активиране на stealth режим за T Market...")
                
                # Създаваме нов stealth контекст
                stealth_context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                    locale="bg-BG",
                    viewport={"width": 1920, "height": 1080},
                    java_script_enabled=True,
                    ignore_https_errors=True,
                    extra_http_headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                        "Accept-Language": "bg-BG,bg;q=0.9,en-US;q=0.8,en;q=0.7",
                        "Accept-Encoding": "gzip, deflate, br",
                        "Connection": "keep-alive",
                        "Upgrade-Insecure-Requests": "1",
                        "Sec-Fetch-Dest": "document",
                        "Sec-Fetch-Mode": "navigate",
                        "Sec-Fetch-Site": "none",
                        "Sec-Fetch-User": "?1",
                        "Cache-Control": "max-age=0",
                    }
                )
                stealth_page = stealth_context.new_page()
                
                # Прилагаме stealth
                stealth_sync(stealth_page)
                
                # Скрапваме с stealth страницата
                all_prices[key] = scrape_store(stealth_page, key, config, vision_client)
                
                stealth_context.close()
            else:
                all_prices[key] = scrape_store(page, key, config, vision_client)
            
            page.wait_for_timeout(2000)
        
        browser.close()
    
    # Обработка на резултатите
    results = []
    for product in PRODUCTS:
        name = product['name']
        product_prices = {k: all_prices.get(k, {}).get(name) for k in STORES}
        valid = [p for p in product_prices.values() if p]
        
        if valid:
            avg = sum(valid) / len(valid)
            avg_eur = avg / EUR_RATE
            dev = ((avg - product['ref_price_bgn']) / product['ref_price_bgn']) * 100
            status = "ВНИМАНИЕ" if abs(dev) > ALERT_THRESHOLD else "OK"
        else:
            avg = avg_eur = dev = None
            status = "НЯМА ДАННИ"
        
        results.append({
            "name": name,
            "weight": product['weight'],
            "ref_bgn": product['ref_price_bgn'],
            "ref_eur": product['ref_price_eur'],
            "prices": product_prices,
            "avg_bgn": round(avg, 2) if avg else None,
            "avg_eur": round(avg_eur, 2) if avg_eur else None,
            "deviation": round(dev, 1) if dev is not None else None,
            "status": status
        })
    
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
    """Актуализира Google Sheets с резултатите."""
    spreadsheet_id = os.environ.get('SPREADSHEET_ID')
    if not spreadsheet_id:
        print("SPREADSHEET_ID не е зададен")
        return
    
    try:
        gc = get_sheets_client()
        spreadsheet = gc.open_by_key(spreadsheet_id)
        
        # Главен лист
        try:
            sheet = spreadsheet.worksheet("Ценови Тракер")
        except:
            sheet = spreadsheet.add_worksheet("Ценови Тракер", rows=30, cols=15)
        
        sheet.clear()
        print("  Лист изчистен")
        
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        store_names = [s['name_in_sheet'] for s in STORES.values()]
        
        # Подготвяме всички данни
        all_data = []
        
        # Ред 1: Заглавие
        all_data.append(['HARMONICA - Ценови Тракер v7.2', '', '', '', '', '', '', '', '', '', '', '', ''])
        
        # Ред 2: Метаданни
        all_data.append([f'Актуализация: {now}', '', f'Курс: {EUR_RATE}', '', f'Магазини: {", ".join(store_names)}', '', '', '', '', '', '', '', ''])
        
        # Ред 3: Празен
        all_data.append([''] * 13)
        
        # Ред 4: Заглавия (с T Market)
        headers = ['№', 'Продукт', 'Грамаж', 'Реф.BGN', 'Реф.EUR', 'eBag', 'Кашон', 'Balev', 'T Market', 'Ср.BGN', 'Ср.EUR', 'Откл.%', 'Статус']
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
                r['prices'].get('TMarket', '') or '',
                r['avg_bgn'] if r['avg_bgn'] else '',
                r['avg_eur'] if r['avg_eur'] else '',
                f"{r['deviation']}%" if r['deviation'] is not None else '',
                r['status']
            ]
            all_data.append(row)
        
        # Записваме
        sheet.update(values=all_data, range_name='A1')
        print(f"  ✓ Записани {len(all_data)} реда")
        
        # Форматиране
        try:
            sheet.format('A1:M1', {
                'backgroundColor': {'red': 0.2, 'green': 0.5, 'blue': 0.3},
                'textFormat': {'bold': True, 'fontSize': 14, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}}
            })
            sheet.merge_cells('A1:M1')
            
            sheet.format('A2:M2', {
                'backgroundColor': {'red': 0.9, 'green': 0.95, 'blue': 0.9},
                'textFormat': {'italic': True}
            })
            
            sheet.format('A4:M4', {
                'backgroundColor': {'red': 0.3, 'green': 0.6, 'blue': 0.4},
                'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
                'horizontalAlignment': 'CENTER'
            })
            
            # Цветово кодиране на статус (колона M)
            for i, r in enumerate(results, 5):
                cell = f'M{i}'
                if r['status'] == 'OK':
                    sheet.format(cell, {
                        'backgroundColor': {'red': 0.85, 'green': 0.95, 'blue': 0.85},
                        'textFormat': {'bold': True, 'foregroundColor': {'red': 0, 'green': 0.5, 'blue': 0}}
                    })
                elif r['status'] == 'ВНИМАНИЕ':
                    sheet.format(cell, {
                        'backgroundColor': {'red': 1, 'green': 0.9, 'blue': 0.9},
                        'textFormat': {'bold': True, 'foregroundColor': {'red': 0.8, 'green': 0, 'blue': 0}}
                    })
                else:
                    sheet.format(cell, {
                        'backgroundColor': {'red': 0.95, 'green': 0.95, 'blue': 0.95},
                        'textFormat': {'italic': True, 'foregroundColor': {'red': 0.5, 'green': 0.5, 'blue': 0.5}}
                    })
            
            print("  ✓ Форматиране приложено")
            
            # Оразмеряване на колоните за по-добра четимост
            try:
                # Ширини на колоните в пиксели
                # A=№, B=Продукт, C=Грамаж, D=Реф.BGN, E=Реф.EUR, F=eBag, G=Кашон, H=Balev, I=T Market, J=Ср.BGN, K=Ср.EUR, L=Откл.%, M=Статус
                column_widths = [
                    (0, 35),    # A: №
                    (1, 280),   # B: Продукт (по-широка за дълги имена)
                    (2, 65),    # C: Грамаж
                    (3, 70),    # D: Реф.BGN
                    (4, 70),    # E: Реф.EUR
                    (5, 60),    # F: eBag
                    (6, 60),    # G: Кашон
                    (7, 60),    # H: Balev
                    (8, 70),    # I: T Market
                    (9, 65),    # J: Ср.BGN
                    (10, 65),   # K: Ср.EUR
                    (11, 65),   # L: Откл.%
                    (12, 90),   # M: Статус
                ]
                
                requests = []
                for col_idx, width in column_widths:
                    requests.append({
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": sheet.id,
                                "dimension": "COLUMNS",
                                "startIndex": col_idx,
                                "endIndex": col_idx + 1
                            },
                            "properties": {
                                "pixelSize": width
                            },
                            "fields": "pixelSize"
                        }
                    })
                
                # Изпълняваме batch update
                spreadsheet.batch_update({"requests": requests})
                print("  ✓ Колони оразмерени")
            except Exception as e:
                print(f"  Оразмеряване предупреждение: {str(e)[:50]}")
        except Exception as e:
            print(f"  Форматиране предупреждение: {str(e)[:50]}")
        
        # История - годишни табове
        try:
            current_year = datetime.now().year
            history_tab_name = f"История_{current_year}"
            
            # Проверяваме дали съществува таб за текущата година
            try:
                hist = spreadsheet.worksheet(history_tab_name)
            except:
                # Няма таб за тази година
                # Проверяваме дали има стар таб "История" (за миграция)
                try:
                    old_hist = spreadsheet.worksheet("История")
                    # Преименуваме го на История_2025
                    old_hist.update_title("История_2025")
                    print(f"  ✓ Преименуван таб 'История' → 'История_2025'")
                    
                    # Ако текущата година е 2025, използваме преименувания таб
                    if current_year == 2025:
                        hist = old_hist
                    else:
                        # Създаваме нов таб за текущата година (с T Market)
                        hist = spreadsheet.add_worksheet(history_tab_name, rows=2000, cols=13)
                        hist.update(values=[['Дата', 'Час', 'Продукт', 'Грамаж', 'eBag', 'Кашон', 'Balev', 'T Market', 'Средна', 'Откл.%', 'Статус']], range_name='A1')
                        hist.freeze(rows=1)
                        print(f"  ✓ Създаден нов таб '{history_tab_name}'")
                except:
                    # Няма стар таб "История", създаваме нов за текущата година (с T Market)
                    hist = spreadsheet.add_worksheet(history_tab_name, rows=2000, cols=13)
                    hist.update(values=[['Дата', 'Час', 'Продукт', 'Грамаж', 'eBag', 'Кашон', 'Balev', 'T Market', 'Средна', 'Откл.%', 'Статус']], range_name='A1')
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
                    r['prices'].get('TMarket', '') or '',
                    r['avg_bgn'] if r['avg_bgn'] else '',
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

def send_email_alert(alerts):
    """Изпраща имейл известие при отклонения."""
    gmail_user = os.environ.get('GMAIL_USER')
    gmail_pass = os.environ.get('GMAIL_APP_PASSWORD')
    recipients = os.environ.get('ALERT_EMAIL', gmail_user)
    spreadsheet_id = os.environ.get('SPREADSHEET_ID', '')
    
    if not gmail_user or not gmail_pass:
        print("Gmail credentials не са зададени")
        return
    
    if not alerts:
        print("Няма отклонения над прага - имейл не е изпратен")
        return
    
    subject = "[!] Harmonica: " + str(len(alerts)) + " продукта с ценови промени над " + str(ALERT_THRESHOLD) + "%"
    sheets_url = "https://docs.google.com/spreadsheets/d/" + spreadsheet_id if spreadsheet_id else ""
    
    # Plain text версия
    body_lines = []
    body_lines.append("Здравей,")
    body_lines.append("")
    body_lines.append("Открити са " + str(len(alerts)) + " продукта с ценови отклонения над " + str(ALERT_THRESHOLD) + "%:")
    body_lines.append("")
    
    for a in alerts:
        ref_price = "{:.2f}".format(a['ref_bgn'])
        avg_price = "{:.2f}".format(a['avg_bgn'])
        dev_pct = "{:+.1f}".format(a['deviation'])
        ebag_price = str(a['prices'].get('eBag') or 'N/A')
        kashon_price = str(a['prices'].get('Kashon') or 'N/A')
        balev_price = str(a['prices'].get('Balev') or 'N/A')
        tmarket_price = str(a['prices'].get('TMarket') or 'N/A')
        
        body_lines.append("--------------------------------------------")
        body_lines.append("* " + a['name'] + " (" + a['weight'] + ")")
        body_lines.append("  Референтна: " + ref_price + " лв")
        body_lines.append("  Средна: " + avg_price + " лв")
        body_lines.append("  Отклонение: " + dev_pct + "%")
        body_lines.append("  eBag: " + ebag_price + " | Кашон: " + kashon_price + " | Balev: " + balev_price + " | T Market: " + tmarket_price)
        body_lines.append("")
    
    body_lines.append("--------------------------------------------")
    body_lines.append("")
    body_lines.append("Пълен отчет в Google Sheets:")
    body_lines.append(sheets_url)
    body_lines.append("")
    body_lines.append("Poздрави,")
    body_lines.append("Harmonica Price Tracker v7.2")
    
    body = "\n".join(body_lines)
    
    try:
        msg = MIMEMultipart()
        msg['From'] = gmail_user
        msg['To'] = recipients
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(gmail_user, gmail_pass)
            server.send_message(msg)
        
        print("Имейл изпратен до " + recipients)
    except Exception as e:
        print("Имейл грешка: " + str(e)[:50])


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("HARMONICA PRICE TRACKER v7.2")
    print("Stealth режим за T Market + форматиране на колоните")
    print("Време: " + datetime.now().strftime('%d.%m.%Y %H:%M'))
    print("Продукти: " + str(len(PRODUCTS)))
    print("Магазини: " + str(len(STORES)))
    print("Claude API: " + ("Наличен" if CLAUDE_AVAILABLE else "Не е наличен"))
    print("Stealth: " + ("Наличен" if STEALTH_AVAILABLE else "Не е наличен"))
    print("Vision: " + ("Активна" if ENABLE_VISUAL_VERIFICATION else "Изключена"))
    print("=" * 60)
    
    results = collect_prices()
    update_google_sheets(results)
    
    alerts = [r for r in results if r['deviation'] and abs(r['deviation']) > ALERT_THRESHOLD]
    send_email_alert(alerts)
    
    # Обобщение
    print("\n" + "="*60)
    print("ОБОБЩЕНИЕ")
    print("="*60)
    
    for k, cfg in STORES.items():
        cnt = len([r for r in results if r['prices'].get(k)])
        print("  " + cfg['name_in_sheet'] + ": " + str(cnt) + "/" + str(len(results)) + " продукта")
    
    total = len([r for r in results if any(r['prices'].values())])
    ok_count = len([r for r in results if r['status'] == 'OK'])
    warning_count = len([r for r in results if r['status'] == 'ВНИМАНИЕ'])
    no_data = len([r for r in results if r['status'] == 'НЯМА ДАННИ'])
    
    print("\nОбщо покритие: " + str(total) + "/" + str(len(results)) + " продукта")
    print("Статус: " + str(ok_count) + " OK, " + str(warning_count) + " ВНИМАНИЕ, " + str(no_data) + " НЯМА ДАННИ")
    print("\nГотово!")


if __name__ == "__main__":
    main()
