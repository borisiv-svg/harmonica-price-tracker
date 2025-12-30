"""
Harmonica Price Tracker v5.1
Разширен с 4 магазина: eBag, Кашон, Zoya, Balev Bio Market
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
    "Zoya": {
        "url": "https://zoya.bg/shop/Zoya-BG-Organic-Natural-super-store.1/Harmonica-m238",
        "name_in_sheet": "Zoya"
    },
    "Balev": {
        "url": "https://balevbiomarket.com/search?q=harmonica",
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
        return None
    return anthropic.Anthropic(api_key=api_key)


def extract_prices_with_claude(page_text, store_name):
    """
    Използва Claude AI за интелигентно извличане на цени.
    """
    if not CLAUDE_AVAILABLE:
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
2. Продуктите може да са изписани по различен начин (на български, на английски, съкратено, с различен словоред)
3. Обърни внимание на грамажа/обема - той трябва да съвпада
4. Извлечи цената в лева (формат: XX.XX лв или XX,XX лв)
5. Ако продукт не е намерен или цената не е ясна, пропусни го

ФОРМАТ НА ОТГОВОРА:
Върни САМО JSON обект без допълнителен текст. Формат:
{{"Био Локум роза": 3.81, "Айран harmonica": 2.90}}

Ако не намериш никакви продукти, върни празен обект: {{}}"""

    try:
        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        
        response_text = message.content[0].text.strip()
        
        # Почистваме markdown форматиране
        if response_text.startswith("```"):
            response_text = re.sub(r'^```(?:json)?\s*', '', response_text)
            response_text = re.sub(r'\s*```$', '', response_text)
        
        prices = json.loads(response_text)
        
        validated_prices = {}
        for product_name, price in prices.items():
            if isinstance(price, (int, float)) and 0.5 < price < 200:
                validated_prices[product_name] = float(price)
        
        return validated_prices
        
    except Exception as e:
        print(f"    Claude грешка: {str(e)[:50]}")
        return {}


# =============================================================================
# FALLBACK ТЪРСЕНЕ
# =============================================================================

PRODUCT_KEYWORDS = {
    "Био Локум роза": ["локум роза", "локум", "роза 140", "turkish delight rose"],
    "Био Обикновени бисквити с краве масло": ["бисквити краве масло", "butter biscuits", "бисквити 150"],
    "Айран harmonica": ["айран 500", "айран", "ayran"],
    "Био Тунквана вафла без захар": ["вафла без захар", "wafer sugar free", "тунквана без захар"],
    "Био Оризови топчета с черен шоколад": ["оризови топчета", "rice balls", "топчета шоколад"],
    "Био лимонада": ["лимонада 330", "lemonade", "лимонада"],
    "Био тънки претцели с морска сол": ["претцели", "pretzels", "grizzeti"],
    "Био тунквана вафла Класика": ["вафла класика", "classic wafer", "тунквана класика"],
    "Био вафла без добавена захар": ["вафла 30г", "вафла 30", "crispy wafer 30"],
    "Био сироп от липа": ["сироп липа", "linden syrup", "липа 750"],
    "Био Пасирани домати": ["пасирани домати", "passata", "домати 680"],
    "Smiles с нахут и морска сол": ["smiles", "смайлс", "нахут сол"],
    "Био Крема сирене": ["крема сирене", "cream cheese", "крема 125"],
    "Козе сирене harmonica": ["козе сирене", "goat cheese", "козе 200"],
}


def extract_price_from_context(text):
    """Извлича цена от текст."""
    if not text:
        return None
    
    matches = re.findall(r'(\d+)[,.](\d{2})\s*(?:лв|€|EUR|BGN)', text, re.IGNORECASE)
    for match in matches:
        try:
            price = float(f"{match[0]}.{match[1]}")
            if 0.50 < price < 200:
                return price
        except:
            continue
    return None


def extract_prices_with_keywords(page_text):
    """Fallback метод за извличане на цени."""
    prices = {}
    page_text_lower = page_text.lower()
    
    for product in PRODUCTS:
        keywords = PRODUCT_KEYWORDS.get(product['name'], [])
        
        for keyword in keywords:
            keyword_lower = keyword.lower()
            idx = page_text_lower.find(keyword_lower)
            
            if idx != -1:
                start = max(0, idx - 50)
                end = min(len(page_text), idx + len(keyword) + 100)
                context = page_text[start:end]
                
                price = extract_price_from_context(context)
                if price:
                    prices[product['name']] = price
                    break
    
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
        print(f"  URL: {url[:70]}...")
        
        page.goto(url, timeout=60000)
        page.wait_for_timeout(5000)
        
        # Приемане на бисквитки
        try:
            cookie_selectors = [
                'button:has-text("Приемам")',
                'button:has-text("Съгласен")',
                'button:has-text("Accept")',
                'button:has-text("Разбрах")',
                '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',
                '[class*="cookie"] button',
                '[class*="consent"] button',
            ]
            for selector in cookie_selectors:
                btn = page.query_selector(selector)
                if btn:
                    btn.click()
                    page.wait_for_timeout(2000)
                    print(f"  Бисквитки приети")
                    break
        except:
            pass
        
        # Скролване за зареждане на продукти
        for _ in range(5):
            page.evaluate("window.scrollBy(0, 1000)")
            page.wait_for_timeout(800)
        
        body_text = page.inner_text('body')
        print(f"  Заредени {len(body_text)} символа")
        
        # Claude AI извличане
        print(f"  Извличане с Claude AI...")
        prices = extract_prices_with_claude(body_text, store_name)
        print(f"    Claude намери: {len(prices)} продукта")
        
        # Fallback ако Claude не намери достатъчно
        if len(prices) < len(PRODUCTS) * 0.3:
            print(f"  Допълване с fallback...")
            fallback_prices = extract_prices_with_keywords(body_text)
            for name, price in fallback_prices.items():
                if name not in prices:
                    prices[name] = price
            print(f"    След fallback: {len(prices)} продукта")
        
        print(f"  Резултат: {len(prices)} продукта")
        
    except Exception as e:
        print(f"  ГРЕШКА: {str(e)[:80]}")
    
    return prices


def collect_prices():
    """Събира цени от всички магазини."""
    all_store_prices = {}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            locale="bg-BG",
            viewport={"width": 1920, "height": 1080}
        )
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
        for store_key, store_config in STORES.items():
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
            "prices": product_prices,  # Dict с цени от всички магазини
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
        sheet.format('A1:O1', {
            'backgroundColor': {'red': 0.2, 'green': 0.5, 'blue': 0.3},
            'textFormat': {'bold': True, 'fontSize': 14, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
            'horizontalAlignment': 'CENTER'
        })
        
        # Метаданни
        sheet.format('A2:O2', {
            'backgroundColor': {'red': 0.9, 'green': 0.95, 'blue': 0.9},
            'textFormat': {'italic': True, 'fontSize': 10}
        })
        
        # Заглавия на колони
        last_col = chr(ord('A') + 4 + num_stores + 4)  # A + № + Продукт + Грамаж + Реф + Магазини + Статистики
        sheet.format(f'A4:{last_col}4', {
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
        sheet.update(range_name='A1:O1', values=[
            [f'HARMONICA - Ценови Тракер ({len(STORES)} магазина)', '', '', '', '', '', '', '', '', '', '', '', '', '', '']
        ])
        
        # Метаданни
        sheet.update(range_name='A2:O2', values=[
            ['Последна актуализация:', now, '', '', 'Курс:', f'{EUR_RATE} лв/EUR', '', 'Магазини:', ', '.join(store_names), '', '', '', '', '', '']
        ])
        
        # Заглавия на колони - динамично базирано на броя магазини
        headers = ['№', 'Продукт', 'Грамаж', 'Реф. BGN', 'Реф. EUR']
        headers.extend(store_names)
        headers.extend(['Ср. BGN', 'Ср. EUR', 'Откл. %', 'Статус'])
        
        # Определяме диапазона за заглавията
        end_col = chr(ord('A') + len(headers) - 1)
        sheet.update(range_name=f'A4:{end_col}4', values=[headers])
        
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
        
        sheet.update(range_name=f'A5:{end_col}{4 + len(rows)}', values=rows)
        
        # Форматиране
        format_worksheet(sheet, len(rows), len(STORES))
        
        # Оцветяване на статус колоната
        status_col = chr(ord('A') + len(headers) - 1)
        for i, r in enumerate(results, 5):
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
            history_sheet = spreadsheet.add_worksheet(title="История", rows=2000, cols=15)
            headers = ['Дата', 'Час', 'Продукт', 'Грамаж']
            headers.extend(store_names)
            headers.extend(['Средна', 'Откл. %', 'Статус'])
            history_sheet.update(range_name='A1:N1', values=[headers])
            history_sheet.format('A1:N1', {
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
    print("HARMONICA PRICE TRACKER v5.1")
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
    print(f"\nОбщо продукти с цени: {products_with_any}/{len(results)}")
    print(f"Продукти с отклонения: {len(alerts)}")
    
    print(f"\n{'='*60}")
    print("✓ Готово!")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
