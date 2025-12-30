"""
Harmonica Price Tracker v5.0
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
    print("⚠ Anthropic библиотеката не е налична, използвам fallback метод")

# =============================================================================
# КОНФИГУРАЦИЯ
# =============================================================================

EUR_RATE = 1.95583
ALERT_THRESHOLD = 10

# URL адреси на магазините
EBAG_HARMONICA_URL = "https://www.ebag.bg/search/?products%5BrefinementList%5D%5Bbrand_name_bg%5D%5B0%5D=%D0%A5%D0%B0%D1%80%D0%BC%D0%BE%D0%BD%D0%B8%D0%BA%D0%B0"
KASHON_HARMONICA_URL = "https://kashonharmonica.bg/bg/products/field_producer/harmonica-144"

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
    Използва Claude AI за интелигентно извличане на цени от текста на страницата.
    
    Claude анализира текста и съпоставя продуктите от нашия списък с тези на страницата,
    дори когато имената са изписани различно или на различен език.
    """
    if not CLAUDE_AVAILABLE:
        print(f"    Claude API не е наличен")
        return {}
    
    client = get_claude_client()
    if not client:
        print(f"    ANTHROPIC_API_KEY не е зададен")
        return {}
    
    # Подготвяме списъка с продукти за търсене
    products_list = "\n".join([
        f"- {p['name']} ({p['weight']})" for p in PRODUCTS
    ])
    
    # Ограничаваме текста до разумен размер (около 15000 символа)
    # за да спестим токени и да останем в лимитите
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
        # Използваме Claude 3 Haiku - най-бързият и евтин модел
        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1024,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        # Извличаме отговора
        response_text = message.content[0].text.strip()
        
        # Почистваме отговора ако има markdown форматиране
        if response_text.startswith("```"):
            # Премахваме ```json и ```
            response_text = re.sub(r'^```(?:json)?\s*', '', response_text)
            response_text = re.sub(r'\s*```$', '', response_text)
        
        # Парсваме JSON
        prices = json.loads(response_text)
        
        # Валидираме резултата
        validated_prices = {}
        for product_name, price in prices.items():
            if isinstance(price, (int, float)) and 0.5 < price < 200:
                validated_prices[product_name] = float(price)
        
        print(f"    Claude намери {len(validated_prices)} продукта")
        return validated_prices
        
    except json.JSONDecodeError as e:
        print(f"    Грешка при парсване на Claude отговор: {e}")
        print(f"    Отговор: {response_text[:200]}...")
        return {}
    except anthropic.APIError as e:
        print(f"    Claude API грешка: {e}")
        return {}
    except Exception as e:
        print(f"    Неочаквана грешка: {e}")
        return {}


# =============================================================================
# FALLBACK: ТЪРСЕНЕ ПО КЛЮЧОВИ ДУМИ
# =============================================================================

# Ключови думи за fallback метода (ако Claude API не работи)
PRODUCT_KEYWORDS = {
    "Био Локум роза": ["локум роза", "локум", "роза 140"],
    "Био Обикновени бисквити с краве масло": ["бисквити с краве масло", "бисквити краве", "краве масло 150"],
    "Айран harmonica": ["айран 500", "айран хармоника", "айран"],
    "Био Тунквана вафла без захар": ["тунквана вафла без захар", "вафла без захар 40"],
    "Био Оризови топчета с черен шоколад": ["оризови топчета", "топчета шоколад", "топчета 50"],
    "Био лимонада": ["лимонада 330", "био лимонада", "лимонада"],
    "Био тънки претцели с морска сол": ["претцели", "претцели сол", "претцели 80"],
    "Био тунквана вафла Класика": ["вафла класика", "тунквана класика"],
    "Био вафла без добавена захар": ["вафла 30г", "вафла 30", "вафла без добавена захар"],
    "Био сироп от липа": ["сироп липа", "сироп от липа", "липа 750"],
    "Био Пасирани домати": ["пасирани домати", "домати пасирани", "домати 680"],
    "Smiles с нахут и морска сол": ["smiles нахут", "smiles", "смайлс", "нахут сол"],
    "Био Крема сирене": ["крема сирене", "cream cheese", "крема 125"],
    "Козе сирене harmonica": ["козе сирене", "goat cheese", "козе 200"],
}


def extract_price_from_context(text):
    """Извлича цена от текст."""
    if not text:
        return None
    
    matches = re.findall(r'(\d+)[,.](\d{2})\s*лв', text, re.IGNORECASE)
    for match in matches:
        try:
            price = float(f"{match[0]}.{match[1]}")
            if 0.50 < price < 200:
                return price
        except:
            continue
    return None


def extract_prices_with_keywords(page_text):
    """
    Fallback метод: извлича цени чрез търсене по ключови думи.
    Използва се ако Claude API не е наличен или върне грешка.
    """
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

def scrape_store(page, url, store_name):
    """
    Универсална функция за извличане на цени от магазин.
    Първо опитва с Claude AI, после с fallback метод.
    """
    prices = {}
    
    try:
        print(f"\n{'='*60}")
        print(f"{store_name}: Зареждане")
        print(f"{'='*60}")
        
        page.goto(url, timeout=60000)
        page.wait_for_timeout(5000)
        
        # Приемане на бисквитки (ако има)
        try:
            for selector in ['button:has-text("Приемам")', '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll']:
                btn = page.query_selector(selector)
                if btn:
                    btn.click()
                    page.wait_for_timeout(2000)
                    break
        except:
            pass
        
        # Скролване за зареждане на всички продукти
        for _ in range(5):
            page.evaluate("window.scrollBy(0, 1000)")
            page.wait_for_timeout(800)
        
        # Вземаме текста на страницата
        body_text = page.inner_text('body')
        print(f"  Заредени {len(body_text)} символа")
        
        # Опитваме с Claude AI
        print(f"\n  Извличане на цени с Claude AI...")
        prices = extract_prices_with_claude(body_text, store_name)
        
        # Ако Claude не намери достатъчно продукти, допълваме с fallback
        if len(prices) < len(PRODUCTS) * 0.5:  # По-малко от 50%
            print(f"\n  Допълване с fallback метод...")
            fallback_prices = extract_prices_with_keywords(body_text)
            
            # Добавяме само липсващите продукти
            for name, price in fallback_prices.items():
                if name not in prices:
                    prices[name] = price
                    print(f"    + {name}: {price:.2f} лв (fallback)")
        
        print(f"\n  Общо намерени: {len(prices)} продукта")
        
    except Exception as e:
        print(f"  ГРЕШКА: {str(e)}")
    
    return prices


def collect_prices():
    """Събира цени от всички магазини."""
    results = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            locale="bg-BG",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()
        
        # Събираме от eBag
        ebag_prices = scrape_store(page, EBAG_HARMONICA_URL, "eBag")
        page.wait_for_timeout(2000)
        
        # Събираме от Кашон
        kashon_prices = scrape_store(page, KASHON_HARMONICA_URL, "Кашон Harmonica")
        
        browser.close()
        
        # Обработваме резултатите
        for product in PRODUCTS:
            name = product['name']
            ebag_price = ebag_prices.get(name)
            kashon_price = kashon_prices.get(name)
            
            prices = [p for p in [ebag_price, kashon_price] if p is not None]
            
            if prices:
                avg_price = sum(prices) / len(prices)
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
                "ebag_price": ebag_price,
                "kashon_price": kashon_price,
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


def format_worksheet(sheet, num_products):
    """Прилага визуално форматиране към работния лист."""
    try:
        # Заглавие
        sheet.format('A1:K1', {
            'backgroundColor': {'red': 0.2, 'green': 0.5, 'blue': 0.3},
            'textFormat': {'bold': True, 'fontSize': 14, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
            'horizontalAlignment': 'CENTER'
        })
        
        # Метаданни
        sheet.format('A2:K2', {
            'backgroundColor': {'red': 0.9, 'green': 0.95, 'blue': 0.9},
            'textFormat': {'italic': True, 'fontSize': 10}
        })
        
        # Заглавия на колони
        sheet.format('A4:K4', {
            'backgroundColor': {'red': 0.3, 'green': 0.6, 'blue': 0.4},
            'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
            'horizontalAlignment': 'CENTER',
            'borders': {
                'top': {'style': 'SOLID'},
                'bottom': {'style': 'SOLID'},
                'left': {'style': 'SOLID'},
                'right': {'style': 'SOLID'}
            }
        })
        
        # Данни
        data_range = f'A5:K{4 + num_products}'
        sheet.format(data_range, {
            'borders': {
                'top': {'style': 'SOLID', 'color': {'red': 0.8, 'green': 0.8, 'blue': 0.8}},
                'bottom': {'style': 'SOLID', 'color': {'red': 0.8, 'green': 0.8, 'blue': 0.8}},
                'left': {'style': 'SOLID', 'color': {'red': 0.8, 'green': 0.8, 'blue': 0.8}},
                'right': {'style': 'SOLID', 'color': {'red': 0.8, 'green': 0.8, 'blue': 0.8}}
            }
        })
        
        sheet.format(f'A5:A{4 + num_products}', {'horizontalAlignment': 'CENTER'})
        sheet.format(f'D5:I{4 + num_products}', {'horizontalAlignment': 'RIGHT'})
        sheet.format(f'J5:K{4 + num_products}', {'horizontalAlignment': 'CENTER'})
        
    except Exception as e:
        print(f"  Предупреждение за форматиране: {str(e)[:50]}")


def update_main_sheet(gc, spreadsheet_id, results):
    """Актуализира главния работен лист."""
    try:
        sheet = gc.open_by_key(spreadsheet_id).worksheet("Ценови Тракер")
        sheet.clear()
        
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        
        sheet.update(range_name='A1:K1', values=[
            ['HARMONICA - Ценови Тракер (Claude AI)', '', '', '', '', '', '', '', '', '', '']
        ])
        
        sheet.update(range_name='A2:K2', values=[
            ['Последна актуализация:', now, '', '', 'Курс:', f'{EUR_RATE} лв/EUR', '', '', '', '', '']
        ])
        
        headers = ['№', 'Продукт', 'Грамаж', 'Реф. BGN', 'Реф. EUR', 
                   'eBag', 'Кашон', 'Ср. BGN', 'Ср. EUR', 'Откл. %', 'Статус']
        sheet.update(range_name='A4:K4', values=[headers])
        
        rows = []
        for i, r in enumerate(results, 1):
            rows.append([
                i, r['name'], r['weight'], r['ref_price_bgn'], r['ref_price_eur'],
                r['ebag_price'] if r['ebag_price'] else '',
                r['kashon_price'] if r['kashon_price'] else '',
                r['avg_price_bgn'] if r['avg_price_bgn'] else '',
                r['avg_price_eur'] if r['avg_price_eur'] else '',
                f"{r['deviation']}%" if r['deviation'] is not None else '',
                r['status']
            ])
        
        sheet.update(range_name=f'A5:K{4 + len(rows)}', values=rows)
        format_worksheet(sheet, len(rows))
        
        # Оцветяване на статус колоната
        for i, r in enumerate(results, 5):
            if r['status'] == 'OK':
                sheet.format(f'K{i}', {
                    'backgroundColor': {'red': 0.85, 'green': 0.95, 'blue': 0.85},
                    'textFormat': {'bold': True, 'foregroundColor': {'red': 0, 'green': 0.5, 'blue': 0}}
                })
            elif r['status'] == 'ВНИМАНИЕ':
                sheet.format(f'K{i}', {
                    'backgroundColor': {'red': 1, 'green': 0.9, 'blue': 0.9},
                    'textFormat': {'bold': True, 'foregroundColor': {'red': 0.8, 'green': 0, 'blue': 0}}
                })
            else:
                sheet.format(f'K{i}', {
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
        
        try:
            history_sheet = spreadsheet.worksheet("История")
        except gspread.exceptions.WorksheetNotFound:
            history_sheet = spreadsheet.add_worksheet(title="История", rows=1000, cols=10)
            headers = ['Дата', 'Час', 'Продукт', 'Грамаж', 'eBag', 'Кашон', 'Средна', 'Откл. %', 'Статус']
            history_sheet.update(range_name='A1:I1', values=[headers])
            history_sheet.format('A1:I1', {
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
            new_rows.append([
                date_str, time_str, r['name'], r['weight'],
                r['ebag_price'] if r['ebag_price'] else '',
                r['kashon_price'] if r['kashon_price'] else '',
                r['avg_price_bgn'] if r['avg_price_bgn'] else '',
                f"{r['deviation']}%" if r['deviation'] is not None else '',
                r['status']
            ])
        
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
    """Изпраща имейл известие за продукти с ценови отклонения."""
    gmail_user = os.environ.get('GMAIL_USER')
    gmail_password = os.environ.get('GMAIL_APP_PASSWORD')
    recipients = os.environ.get('ALERT_EMAIL', gmail_user)
    
    if not gmail_user or not gmail_password:
        print("Gmail credentials не са зададени")
        return
    
    if not alerts:
        print("Няма продукти с отклонения над прага - имейл не е изпратен")
        return
    
    subject = f"🚨 Harmonica: {len(alerts)} продукта с ценови промени над {ALERT_THRESHOLD}%"
    
    body = f"""Здравей,

Открити са {len(alerts)} продукта с ценови отклонения над {ALERT_THRESHOLD}%:

"""
    for alert in alerts:
        ebag_str = f"{alert['ebag_price']:.2f} лв" if alert['ebag_price'] else "N/A"
        kashon_str = f"{alert['kashon_price']:.2f} лв" if alert['kashon_price'] else "N/A"
        
        body += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📦 {alert['name']} ({alert['weight']})
   Референтна цена: {alert['ref_price_bgn']:.2f} лв / {alert['ref_price_eur']:.2f} €
   Средна цена: {alert['avg_price_bgn']:.2f} лв / {alert['avg_price_eur']:.2f} €
   Отклонение: {alert['deviation']:+.1f}%
   eBag: {ebag_str}
   Кашон: {kashon_str}
"""
    
    body += """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Проверете Google Sheets за пълния отчет.

Поздрави,
Harmonica Price Tracker (с Claude AI)
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
    print("=" * 60)
    print("HARMONICA PRICE TRACKER v5.0 (Claude AI)")
    print(f"Време: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"Продукти: {len(PRODUCTS)}")
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
    
    products_with_ebag = len([r for r in results if r['ebag_price']])
    products_with_kashon = len([r for r in results if r['kashon_price']])
    products_with_any = len([r for r in results if r['ebag_price'] or r['kashon_price']])
    
    print(f"Продукти с цени: {products_with_any}/{len(results)}")
    print(f"  - от eBag: {products_with_ebag}")
    print(f"  - от Кашон: {products_with_kashon}")
    print(f"Продукти с отклонения: {len(alerts)}")
    
    print(f"\n{'='*60}")
    print("✓ Готово!")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
