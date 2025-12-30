"""
Harmonica Price Tracker v5.2
3 магазина: eBag, Кашон, Balev Bio Market
Използва Claude AI за интелигентно съпоставяне на продукти.
"""

import os
import json
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from playwright.sync_api import sync_playwright
import gspread
from google.oauth2.service_account import Credentials

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

# Магазини с техните URL адреси
STORES = {
    "eBag": {
        "url": "https://www.ebag.bg/search/?products%5BrefinementList%5D%5Bbrand_name_bg%5D%5B0%5D=%D0%A5%D0%B0%D1%80%D0%BC%D0%BE%D0%BD%D0%B8%D0%BA%D0%B0",
        "name_in_sheet": "eBag"
    },
    "Kashon": {
        "url": "https://kashonharmonica.bg/bg/products/field_producer/harmonica-144",
        "name_in_sheet": "Кашон"
    },
    "Balev": {
        "url": "https://balevbiomarket.com/brands/harmonica",
        "name_in_sheet": "Balev"
    }
}

# Продукти за проследяване
PRODUCTS = [
    {"name": "Био Локум роза", "weight": "140г", "ref_price_bgn": 3.81, "ref_price_eur": 1.95},
    {"name": "Био Обикновени бисквити с краве масло", "weight": "150г", "ref_price_bgn": 4.18, "ref_price_eur": 2.14},
    {"name": "Айран harmonica", "weight": "500мл", "ref_price_bgn": 2.90, "ref_price_eur": 1.48},
    {"name": "Био Тунквана вафла без захар", "weight": "40г", "ref_price_bgn": 2.62, "ref_price_eur": 1.34},
    {"name": "Био Оризови топчета с черен шоколад", "weight": "50г", "ref_price_bgn": 4.99, "ref_price_eur": 2.55},
    {"name": "Био лимонада", "weight": "330мл", "ref_price_bgn": 3.48, "ref_price_eur": 1.78},
    {"name": "Био тънки претцели с морска сол", "weight": "80г", "ref_price_bgn": 2.50, "ref_price_eur": 1.28},
    {"name": "Био тунквана вафла Класика", "weight": "40г", "ref_price_bgn": 2.00, "ref_price_eur": 1.02},
    {"name": "Био вафла без добавена захар", "weight": "30г", "ref_price_bgn": 1.44, "ref_price_eur": 0.74},
    {"name": "Био сироп от липа", "weight": "750мл", "ref_price_bgn": 14.29, "ref_price_eur": 7.31},
    {"name": "Био Пасирани домати", "weight": "680г", "ref_price_bgn": 5.90, "ref_price_eur": 3.02},
    {"name": "Smiles с нахут и морска сол", "weight": "50г", "ref_price_bgn": 2.81, "ref_price_eur": 1.44},
    {"name": "Био Крема сирене", "weight": "125г", "ref_price_bgn": 5.46, "ref_price_eur": 2.79},
    {"name": "Козе сирене harmonica", "weight": "200г", "ref_price_bgn": 10.70, "ref_price_eur": 5.47},
]


# =============================================================================
# CLAUDE AI ФУНКЦИИ
# =============================================================================

def get_claude_client():
    """Създава клиент за Claude API."""
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print("    [DEBUG] ANTHROPIC_API_KEY не е зададен")
        return None
    return anthropic.Anthropic(api_key=api_key)


def extract_prices_with_claude(page_text, store_name):
    """
    Използва Claude AI за интелигентно извличане на цени.
    """
    if not CLAUDE_AVAILABLE:
        print("    [DEBUG] Anthropic не е наличен")
        return {}
    
    client = get_claude_client()
    if not client:
        return {}
    
    products_list = "\n".join([
        f"- {p['name']} ({p['weight']})" for p in PRODUCTS
    ])
    
    # Ограничаваме текста
    if len(page_text) > 15000:
        page_text = page_text[:15000]
    
    prompt = f"""Анализирай следния текст от българския онлайн магазин "{store_name}" и намери цените на продуктите от марката Harmonica (Хармоника).

ПРОДУКТИ ЗА ТЪРСЕНЕ:
{products_list}

ТЕКСТ ОТ СТРАНИЦАТА:
{page_text}

ИНСТРУКЦИИ:
1. Намери всеки продукт от списъка в текста на страницата
2. Продуктите може да са изписани по различен начин (на български, на английски, съкратено)
3. Обърни внимание на грамажа/обема - той трябва да съвпада приблизително
4. Извлечи цената в лева (може да е във формат: 3.81, 3,81, 3.81 лв, 3,81лв)
5. Ако продукт не е намерен или цената не е ясна, пропусни го

Примери за съвпадения:
- "Локум роза 140" = "Био Локум роза 140г"
- "Turkish Delight Rose" = "Био Локум роза"
- "вафла без захар 40г" = "Био Тунквана вафла без захар 40г"
- "оризови топчета шоколад" = "Био Оризови топчета с черен шоколад"
- "претцели сол 80" = "Био тънки претцели с морска сол 80г"
- "сироп липа" = "Био сироп от липа"
- "пасирани домати" = "Био Пасирани домати"

МНОГО ВАЖНО - ФОРМАТ НА ОТГОВОРА:
Върни САМО чист JSON обект. Без ```json```, без markdown, без обяснения.
Пример: {{"Био Локум роза": 3.81, "Айран harmonica": 2.90}}
Ако не намериш нищо: {{}}"""

    try:
        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        
        response_text = message.content[0].text.strip()
        print(f"    [DEBUG] Claude raw response: {response_text[:300]}...")
        
        # Почистваме markdown форматиране ако има
        cleaned = response_text
        if cleaned.startswith("```"):
            # Премахваме ```json или ``` от началото
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            # Премахваме ``` от края
            cleaned = re.sub(r'\s*```$', '', cleaned)
        
        # Опит да намерим JSON обект в текста
        json_match = re.search(r'\{[^{}]*\}', cleaned)
        if json_match:
            cleaned = json_match.group(0)
        
        print(f"    [DEBUG] Claude cleaned: {cleaned[:200]}")
        
        prices = json.loads(cleaned)
        
        # Валидираме цените
        validated_prices = {}
        for product_name, price in prices.items():
            if isinstance(price, (int, float)) and 0.5 < price < 200:
                validated_prices[product_name] = float(price)
        
        print(f"    [DEBUG] Claude validated: {len(validated_prices)} продукта")
        return validated_prices
        
    except json.JSONDecodeError as e:
        print(f"    [DEBUG] JSON parse error: {str(e)}")
        print(f"    [DEBUG] Attempted to parse: {cleaned[:100] if 'cleaned' in dir() else 'N/A'}")
        return {}
    except Exception as e:
        print(f"    [DEBUG] Claude error: {type(e).__name__}: {str(e)[:100]}")
        return {}


# =============================================================================
# FALLBACK ТЪРСЕНЕ С КЛЮЧОВИ ДУМИ
# =============================================================================

PRODUCT_KEYWORDS = {
    "Био Локум роза": ["локум роза", "локум 140", "turkish delight rose", "локум натурален роза"],
    "Био Обикновени бисквити с краве масло": ["бисквити краве масло", "обикновени бисквити", "butter biscuits", "бисквити 150"],
    "Айран harmonica": ["айран 500", "айран", "ayran", "айран хармоника"],
    "Био Тунквана вафла без захар": ["вафла без захар 40", "тунквана без захар", "wafer sugar free", "вафла без добавена захар 40"],
    "Био Оризови топчета с черен шоколад": ["оризови топчета", "rice balls", "топчета шоколад 50", "шоко топчета"],
    "Био лимонада": ["лимонада 330", "lemonade", "лимонада harmonica", "газирана лимонада"],
    "Био тънки претцели с морска сол": ["претцели 80", "претцели сол", "pretzels", "grizzeti", "гризети"],
    "Био тунквана вафла Класика": ["вафла класика 40", "classic wafer", "тунквана класика", "вафла класик"],
    "Био вафла без добавена захар": ["вафла 30г", "вафла 30", "crispy wafer 30", "хрупкава вафла 30"],
    "Био сироп от липа": ["сироп липа", "linden syrup", "липа 750", "липов сироп"],
    "Био Пасирани домати": ["пасирани домати", "passata", "домати 680", "доматено пюре"],
    "Smiles с нахут и морска сол": ["smiles", "смайлс", "нахут сол 50", "smiles нахут"],
    "Био Крема сирене": ["крема сирене 125", "cream cheese", "крема 125", "кремообразно сирене"],
    "Козе сирене harmonica": ["козе сирене 200", "goat cheese", "козе сирене harmonica", "козе 200"],
}


def extract_price_from_context(text, product_name=""):
    """Извлича цена от текст около намерена ключова дума."""
    if not text:
        return None
    
    # Търсим цени в различни формати
    patterns = [
        r'(\d+)[,.](\d{2})\s*(?:лв|лева|BGN)',  # 3.81 лв, 3,81 лева
        r'(\d+)[,.](\d{2})\s*€',                 # 1.95 €
        r'(?:цена|price)[:\s]*(\d+)[,.](\d{2})', # цена: 3.81
        r'(\d+)[,.](\d{2})\s*лв\./бр',           # 3.81 лв./бр
        r'>(\d+)[,.](\d{2})<',                   # HTML тагове >3.81<
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            try:
                price = float(f"{match[0]}.{match[1]}")
                if 0.50 < price < 200:
                    return price
            except:
                continue
    
    return None


def extract_prices_with_keywords(page_text):
    """Fallback метод за извличане на цени с ключови думи."""
    prices = {}
    page_text_lower = page_text.lower()
    
    for product in PRODUCTS:
        product_name = product['name']
        keywords = PRODUCT_KEYWORDS.get(product_name, [])
        
        best_price = None
        
        for keyword in keywords:
            keyword_lower = keyword.lower()
            idx = page_text_lower.find(keyword_lower)
            
            if idx != -1:
                # Взимаме контекст около ключовата дума
                start = max(0, idx - 100)
                end = min(len(page_text), idx + len(keyword) + 150)
                context = page_text[start:end]
                
                price = extract_price_from_context(context, product_name)
                if price:
                    # Проверка за разумна цена спрямо референтната
                    ref_price = product['ref_price_bgn']
                    if 0.3 * ref_price < price < 3 * ref_price:
                        best_price = price
                        break
        
        if best_price:
            prices[product_name] = best_price
    
    return prices


# =============================================================================
# SCRAPING ФУНКЦИИ
# =============================================================================

def scrape_store(page, store_key, store_config):
    """
    Универсална функция за извличане на цени от магазин.
    """
    prices = {}
    url = store_config['url']
    store_name = store_config['name_in_sheet']
    
    try:
        print(f"\n{'='*60}")
        print(f"{store_name}: Зареждане")
        print(f"{'='*60}")
        print(f"  URL: {url[:80]}...")
        
        # Навигация с по-дълъг timeout
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        
        # Приемане на бисквитки
        try:
            cookie_selectors = [
                'button:has-text("Приемам")',
                'button:has-text("Съгласен")',
                'button:has-text("Accept")',
                'button:has-text("Разбрах")',
                'button:has-text("OK")',
                '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',
                '[class*="cookie"] button',
                '[class*="consent"] button',
                '.cc-btn',
            ]
            for selector in cookie_selectors:
                try:
                    btn = page.query_selector(selector)
                    if btn and btn.is_visible():
                        btn.click()
                        page.wait_for_timeout(1500)
                        print(f"  ✓ Бисквитки приети")
                        break
                except:
                    continue
        except:
            pass
        
        # Изчакване за динамично съдържание
        page.wait_for_timeout(2000)
        
        # Скролване за lazy loading
        print(f"  Скролване за зареждане на продукти...")
        for i in range(7):
            page.evaluate("window.scrollBy(0, 800)")
            page.wait_for_timeout(600)
        
        # Връщане в началото
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)
        
        # Извличане на текст
        body_text = page.inner_text('body')
        print(f"  Заредени {len(body_text)} символа")
        
        # Показваме малко от текста за debug
        if len(body_text) < 2000:
            print(f"  [DEBUG] Малко текст! Първи 500 символа:")
            print(f"  {body_text[:500]}")
        
        # Claude AI извличане
        print(f"  Извличане с Claude AI...")
        claude_prices = extract_prices_with_claude(body_text, store_name)
        print(f"    Claude намери: {len(claude_prices)} продукта")
        
        # Добавяме Claude резултатите
        prices.update(claude_prices)
        
        # Fallback с ключови думи за допълване
        print(f"  Допълване с ключови думи...")
        fallback_prices = extract_prices_with_keywords(body_text)
        
        # Добавяме само липсващите от fallback
        added_from_fallback = 0
        for name, price in fallback_prices.items():
            if name not in prices:
                prices[name] = price
                added_from_fallback += 1
        
        print(f"    Добавени от fallback: {added_from_fallback}")
        print(f"  ✓ Общо намерени: {len(prices)} продукта")
        
        # Показваме какво сме намерили
        if prices:
            print(f"  Продукти: {list(prices.keys())[:5]}...")
        
    except Exception as e:
        print(f"  ✗ ГРЕШКА: {type(e).__name__}: {str(e)[:100]}")
    
    return prices


def collect_prices():
    """Събира цени от всички магазини."""
    all_store_prices = {}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="bg-BG",
            viewport={"width": 1920, "height": 1080}
        )
        
        # Блокираме изображения за по-бързо зареждане
        context.route("**/*.{png,jpg,jpeg,gif,webp,svg}", lambda route: route.abort())
        
        page = context.new_page()
        
        # Събираме от всички магазини
        for store_key, store_config in STORES.items():
            store_prices = scrape_store(page, store_key, store_config)
            all_store_prices[store_key] = store_prices
            page.wait_for_timeout(2000)
        
        browser.close()
    
    # Обработваме резултатите
    results = []
    for product in PRODUCTS:
        name = product['name']
        
        # Събираме цени от всички магазини
        product_prices = {}
        for store_key in STORES.keys():
            price = all_store_prices.get(store_key, {}).get(name)
            product_prices[store_key] = price
        
        # Изчисляваме статистики
        valid_prices = [p for p in product_prices.values() if p is not None]
        
        if valid_prices:
            avg_price = sum(valid_prices) / len(valid_prices)
            avg_price_eur = avg_price / EUR_RATE
            deviation = ((avg_price - product['ref_price_bgn']) / product['ref_price_bgn']) * 100
            status = "ВНИМАНИЕ" if abs(deviation) > ALERT_THRESHOLD else "OK"
        else:
            avg_price = None
            avg_price_eur = None
            deviation = None
            status = "НЯМА ДАННИ"
        
        results.append({
            "name": name,
            "weight": product['weight'],
            "ref_price_bgn": product['ref_price_bgn'],
            "ref_price_eur": product['ref_price_eur'],
            "prices": product_prices,
            "avg_price_bgn": round(avg_price, 2) if avg_price else None,
            "avg_price_eur": round(avg_price_eur, 2) if avg_price_eur else None,
            "deviation": round(deviation, 1) if deviation is not None else None,
            "status": status
        })
    
    return results


# =============================================================================
# GOOGLE SHEETS ФУНКЦИИ
# =============================================================================

def get_sheets_client():
    """Създава клиент за Google Sheets API."""
    credentials_json = os.environ.get('GOOGLE_CREDENTIALS')
    if not credentials_json:
        raise ValueError("GOOGLE_CREDENTIALS не е зададена")
    
    credentials_dict = json.loads(credentials_json)
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    credentials = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
    return gspread.authorize(credentials)


def format_worksheet(sheet, num_products, num_stores):
    """Прилага визуално форматиране."""
    try:
        # Заглавие
        sheet.format('A1:L1', {
            'backgroundColor': {'red': 0.2, 'green': 0.5, 'blue': 0.3},
            'textFormat': {'bold': True, 'fontSize': 14, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
            'horizontalAlignment': 'CENTER'
        })
        
        # Метаданни
        sheet.format('A2:L2', {
            'backgroundColor': {'red': 0.9, 'green': 0.95, 'blue': 0.9},
            'textFormat': {'italic': True, 'fontSize': 10}
        })
        
        # Заглавия на колони
        sheet.format('A4:L4', {
            'backgroundColor': {'red': 0.3, 'green': 0.6, 'blue': 0.4},
            'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
            'horizontalAlignment': 'CENTER'
        })
        
    except Exception as e:
        print(f"  Предупреждение за форматиране: {str(e)[:50]}")


def update_main_sheet(gc, spreadsheet_id, results):
    """Актуализира главния работен лист."""
    try:
        sheet = gc.open_by_key(spreadsheet_id).worksheet("Ценови Тракер")
        sheet.clear()
        
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        store_names = [s['name_in_sheet'] for s in STORES.values()]
        
        # Заглавие
        title = f'HARMONICA - Ценови Тракер ({len(STORES)} магазина)'
        sheet.update([[title]], 'A1')
        sheet.merge_cells('A1:L1')
        
        # Метаданни
        meta_row = ['Последна актуализация:', now, '', 'Курс:', f'{EUR_RATE} лв/EUR', '', 
                    'Магазини:', ', '.join(store_names), '', '', '', '']
        sheet.update([meta_row], 'A2')
        
        # Заглавия на колони
        headers = ['№', 'Продукт', 'Грамаж', 'Реф. BGN', 'Реф. EUR']
        headers.extend(store_names)
        headers.extend(['Ср. BGN', 'Ср. EUR', 'Откл. %', 'Статус'])
        sheet.update([headers], 'A4')
        
        # Данни
        rows = []
        for i, r in enumerate(results, 1):
            row = [
                i,
                r['name'],
                r['weight'],
                r['ref_price_bgn'],
                r['ref_price_eur'],
            ]
            # Добавяме цени от всички магазини
            for store_key in STORES.keys():
                price = r['prices'].get(store_key)
                row.append(price if price else '')
            
            row.extend([
                r['avg_price_bgn'] if r['avg_price_bgn'] else '',
                r['avg_price_eur'] if r['avg_price_eur'] else '',
                f"{r['deviation']}%" if r['deviation'] is not None else '',
                r['status']
            ])
            rows.append(row)
        
        # Записваме данните
        if rows:
            end_col = chr(ord('A') + len(headers) - 1)
            sheet.update(rows, f'A5:{end_col}{4 + len(rows)}')
        
        # Форматиране
        format_worksheet(sheet, len(rows), len(STORES))
        
        # Оцветяване на статус колоната
        status_col_idx = len(headers) - 1  # Последната колона
        status_col = chr(ord('A') + status_col_idx)
        
        for i, r in enumerate(results, 5):
            try:
                if r['status'] == 'OK':
                    sheet.format(f'{status_col}{i}', {
                        'backgroundColor': {'red': 0.85, 'green': 0.95, 'blue': 0.85},
                        'textFormat': {'bold': True, 'foregroundColor': {'red': 0, 'green': 0.5, 'blue': 0}}
                    })
                elif r['status'] == 'ВНИМАНИЕ':
                    sheet.format(f'{status_col}{i}', {
                        'backgroundColor': {'red': 1, 'green': 0.9, 'blue': 0.9},
                        'textFormat': {'bold': True, 'foregroundColor': {'red': 0.8, 'green': 0, 'blue': 0}}
                    })
                else:
                    sheet.format(f'{status_col}{i}', {
                        'backgroundColor': {'red': 0.95, 'green': 0.95, 'blue': 0.95},
                        'textFormat': {'italic': True, 'foregroundColor': {'red': 0.5, 'green': 0.5, 'blue': 0.5}}
                    })
            except:
                pass
        
        print(f"✓ Главният лист е актуализиран")
        
    except Exception as e:
        print(f"✗ Грешка при главния лист: {str(e)}")


def update_history_sheet(gc, spreadsheet_id, results):
    """Добавя нов запис в листа с история."""
    try:
        spreadsheet = gc.open_by_key(spreadsheet_id)
        store_names = [s['name_in_sheet'] for s in STORES.values()]
        
        try:
            history_sheet = spreadsheet.worksheet("История")
        except gspread.exceptions.WorksheetNotFound:
            history_sheet = spreadsheet.add_worksheet(title="История", rows=2000, cols=12)
            headers = ['Дата', 'Час', 'Продукт', 'Грамаж']
            headers.extend(store_names)
            headers.extend(['Средна', 'Откл. %', 'Статус'])
            history_sheet.update([headers], 'A1')
            history_sheet.format('A1:L1', {
                'backgroundColor': {'red': 0.2, 'green': 0.4, 'blue': 0.6},
                'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
                'horizontalAlignment': 'CENTER'
            })
            history_sheet.freeze(rows=1)
        
        now = datetime.now()
        date_str = now.strftime("%d.%m.%Y")
        time_str = now.strftime("%H:%M")
        
        new_rows = []
        for r in results:
            row = [date_str, time_str, r['name'], r['weight']]
            for store_key in STORES.keys():
                price = r['prices'].get(store_key)
                row.append(price if price else '')
            row.extend([
                r['avg_price_bgn'] if r['avg_price_bgn'] else '',
                f"{r['deviation']}%" if r['deviation'] is not None else '',
                r['status']
            ])
            new_rows.append(row)
        
        history_sheet.append_rows(new_rows, value_input_option='USER_ENTERED')
        print(f"✓ Добавени {len(new_rows)} записа в историята")
        
    except Exception as e:
        print(f"✗ Грешка при историята: {str(e)}")


def update_google_sheets(results):
    """Главна функция за актуализиране на Google Sheets."""
    spreadsheet_id = os.environ.get('SPREADSHEET_ID')
    if not spreadsheet_id:
        print("SPREADSHEET_ID не е зададен")
        return
    
    try:
        gc = get_sheets_client()
        
        print(f"\n{'='*60}")
        print("Google Sheets: Актуализиране")
        print(f"{'='*60}")
        
        update_main_sheet(gc, spreadsheet_id, results)
        update_history_sheet(gc, spreadsheet_id, results)
        
        print(f"\n✓ Google Sheets актуализиран успешно")
        
    except Exception as e:
        print(f"\n✗ Грешка при Google Sheets: {str(e)}")


# =============================================================================
# ИМЕЙЛ ИЗВЕСТИЯ
# =============================================================================

def send_email_alert(alerts):
    """Изпраща имейл известие."""
    gmail_user = os.environ.get('GMAIL_USER')
    gmail_password = os.environ.get('GMAIL_APP_PASSWORD')
    recipients = os.environ.get('ALERT_EMAIL', gmail_user)
    
    if not gmail_user or not gmail_password:
        print("Gmail credentials не са зададени")
        return
    
    if not alerts:
        print("Няма продукти с отклонения над прага - имейл не е изпратен")
        return
    
    store_names = [s['name_in_sheet'] for s in STORES.values()]
    subject = f"🚨 Harmonica: {len(alerts)} продукта с ценови промени над {ALERT_THRESHOLD}%"
    
    body = f"""Здравей,

Открити са {len(alerts)} продукта с ценови отклонения над {ALERT_THRESHOLD}%:
Проверени магазини: {', '.join(store_names)}

"""
    for alert in alerts:
        body += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📦 {alert['name']} ({alert['weight']})
   Референтна цена: {alert['ref_price_bgn']:.2f} лв / {alert['ref_price_eur']:.2f} €
   Средна цена: {alert['avg_price_bgn']:.2f} лв / {alert['avg_price_eur']:.2f} €
   Отклонение: {alert['deviation']:+.1f}%
"""
        for store_key, store_config in STORES.items():
            price = alert['prices'].get(store_key)
            price_str = f"{price:.2f} лв" if price else "N/A"
            body += f"   {store_config['name_in_sheet']}: {price_str}\n"
    
    body += """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Проверете Google Sheets за пълния отчет.

Поздрави,
Harmonica Price Tracker
"""
    
    try:
        msg = MIMEMultipart()
        msg['From'] = gmail_user
        msg['To'] = recipients
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(gmail_user, gmail_password)
            recipient_list = [r.strip() for r in recipients.split(',')]
            server.send_message(msg, to_addrs=recipient_list)
        
        print(f"\n✓ Имейл изпратен до {recipients}")
        
    except Exception as e:
        print(f"\n✗ Грешка при имейл: {str(e)}")


# =============================================================================
# ГЛАВНА ФУНКЦИЯ
# =============================================================================

def main():
    store_names = [s['name_in_sheet'] for s in STORES.values()]
    
    print("=" * 60)
    print("HARMONICA PRICE TRACKER v5.2")
    print(f"Време: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"Продукти: {len(PRODUCTS)}")
    print(f"Магазини: {len(STORES)} ({', '.join(store_names)})")
    print(f"Праг за известия: {ALERT_THRESHOLD}%")
    print(f"Claude API: {'✓ Наличен' if CLAUDE_AVAILABLE else '✗ Не е наличен'}")
    print("=" * 60)
    
    results = collect_prices()
    update_google_sheets(results)
    
    alerts = [r for r in results if r['deviation'] is not None and abs(r['deviation']) > ALERT_THRESHOLD]
    send_email_alert(alerts)
    
    print(f"\n{'='*60}")
    print("ОБОБЩЕНИЕ")
    print(f"{'='*60}")
    
    # Статистика по магазини
    for store_key, store_config in STORES.items():
        count = len([r for r in results if r['prices'].get(store_key)])
        print(f"  {store_config['name_in_sheet']}: {count}/{len(results)} продукта")
    
    products_with_any = len([r for r in results if any(r['prices'].values())])
    print(f"\nОбщо продукти с поне една цена: {products_with_any}/{len(results)}")
    print(f"Продукти с отклонения >10%: {len(alerts)}")
    
    print(f"\n{'='*60}")
    print("✓ Готово!")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
