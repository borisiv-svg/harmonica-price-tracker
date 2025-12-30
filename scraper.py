"""
Harmonica Price Tracker v4.0
Добавена история на цените и визуално форматиране.
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
from gspread.utils import rowcol_to_a1

# =============================================================================
# КОНФИГУРАЦИЯ
# =============================================================================

EUR_RATE = 1.95583
ALERT_THRESHOLD = 10

# Директни URL адреси към страниците с всички Harmonica продукти
EBAG_HARMONICA_URL = "https://www.ebag.bg/search/?products%5BrefinementList%5D%5Bbrand_name_bg%5D%5B0%5D=%D0%A5%D0%B0%D1%80%D0%BC%D0%BE%D0%BD%D0%B8%D0%BA%D0%B0"
KASHON_HARMONICA_URL = "https://kashonharmonica.bg/bg/products/field_producer/harmonica-144"

# Продукти с множество варианти на ключови думи за по-добро разпознаване
# Включваме различни изписвания, съкращения и варианти
PRODUCTS = [
    {
        "name": "Био Локум роза",
        "weight": "140г",
        "ref_price_bgn": 3.81,
        "ref_price_eur": 1.95,
        "keywords": ["локум роза", "локум с роза", "rose lokum", "локум 140"]
    },
    {
        "name": "Био Обикновени бисквити с краве масло",
        "weight": "150г",
        "ref_price_bgn": 4.18,
        "ref_price_eur": 2.14,
        "keywords": ["бисквити с краве масло", "бисквити краве масло", "butter biscuits", "бисквити 150"]
    },
    {
        "name": "Айран harmonica",
        "weight": "500мл",
        "ref_price_bgn": 2.90,
        "ref_price_eur": 1.48,
        "keywords": ["айран 500", "айран хармоника", "ayran"]
    },
    {
        "name": "Био Тунквана вафла без захар",
        "weight": "40г",
        "ref_price_bgn": 2.62,
        "ref_price_eur": 1.34,
        "keywords": ["тунквана вафла без захар", "вафла без захар 40", "wafer sugar free"]
    },
    {
        "name": "Био Оризови топчета с черен шоколад",
        "weight": "50г",
        "ref_price_bgn": 4.99,
        "ref_price_eur": 2.55,
        "keywords": ["оризови топчета", "топчета шоколад", "rice balls chocolate", "топчета 50"]
    },
    {
        "name": "Био лимонада",
        "weight": "330мл",
        "ref_price_bgn": 3.48,
        "ref_price_eur": 1.78,
        "keywords": ["лимонада 330", "био лимонада", "lemonade", "лимонада хармоника"]
    },
    {
        "name": "Био тънки претцели с морска сол",
        "weight": "80г",
        "ref_price_bgn": 2.50,
        "ref_price_eur": 1.28,
        "keywords": ["претцели", "претцели сол", "pretzels", "претцели 80"]
    },
    {
        "name": "Био тунквана вафла Класика",
        "weight": "40г",
        "ref_price_bgn": 2.00,
        "ref_price_eur": 1.02,
        "keywords": ["вафла класика", "тунквана класика", "classic wafer", "вафла 40г класика"]
    },
    {
        "name": "Био вафла без добавена захар",
        "weight": "30г",
        "ref_price_bgn": 1.44,
        "ref_price_eur": 0.74,
        "keywords": ["вафла 30г", "вафла 30", "вафла без добавена захар", "wafer 30g"]
    },
    {
        "name": "Био сироп от липа",
        "weight": "750мл",
        "ref_price_bgn": 14.29,
        "ref_price_eur": 7.31,
        "keywords": ["сироп липа", "сироп от липа", "linden syrup", "липа 750"]
    },
    {
        "name": "Био Пасирани домати",
        "weight": "680г",
        "ref_price_bgn": 5.90,
        "ref_price_eur": 3.02,
        "keywords": ["пасирани домати", "домати пасирани", "passata", "домати 680"]
    },
    {
        "name": "Smiles с нахут и морска сол",
        "weight": "50г",
        "ref_price_bgn": 2.81,
        "ref_price_eur": 1.44,
        "keywords": ["smiles нахут", "smiles", "смайлс", "нахут сол 50"]
    },
    {
        "name": "Био Крема сирене",
        "weight": "125г",
        "ref_price_bgn": 5.46,
        "ref_price_eur": 2.79,
        "keywords": ["крема сирене", "cream cheese", "крема 125", "сирене крема"]
    },
    {
        "name": "Козе сирене harmonica",
        "weight": "200г",
        "ref_price_bgn": 10.70,
        "ref_price_eur": 5.47,
        "keywords": ["козе сирене", "goat cheese", "козе 200", "сирене козе"]
    },
]


# =============================================================================
# ФУНКЦИИ ЗА ИЗВЛИЧАНЕ НА ЦЕНИ
# =============================================================================

def extract_price_from_context(text):
    """
    Извлича цена от текст. Търси формат X.XX лв или X,XX лв.
    Връща първата валидна цена или None.
    """
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


def find_product_in_page(page_text, product):
    """
    Търси продукт в текста на страницата по ключови думи.
    Използва всички варианти на ключови думи за по-добро съвпадение.
    """
    page_text_lower = page_text.lower()
    
    for keyword in product['keywords']:
        keyword_lower = keyword.lower()
        idx = page_text_lower.find(keyword_lower)
        
        if idx != -1:
            start = max(0, idx - 50)
            end = min(len(page_text), idx + len(keyword) + 100)
            context = page_text[start:end]
            
            price = extract_price_from_context(context)
            
            if price:
                print(f"    ✓ {product['name']}: {price:.2f} лв (ключ: '{keyword}')")
                return price
    
    return None


def scrape_ebag(page):
    """Извлича цени от eBag."""
    ebag_prices = {}
    
    try:
        print(f"\n{'='*60}")
        print("eBag: Зареждане на продукти на Хармоника")
        print(f"{'='*60}")
        
        page.goto(EBAG_HARMONICA_URL, timeout=60000)
        page.wait_for_timeout(5000)
        
        # Приемане на бисквитки
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
        for _ in range(3):
            page.evaluate("window.scrollBy(0, 1000)")
            page.wait_for_timeout(1000)
        
        body_text = page.inner_text('body')
        print(f"  Заредени {len(body_text)} символа")
        
        print(f"\n  Търсене на продукти:")
        for product in PRODUCTS:
            price = find_product_in_page(body_text, product)
            if price:
                ebag_prices[product['name']] = price
        
        print(f"\n  Резултат: {len(ebag_prices)} от {len(PRODUCTS)} продукта")
        
    except Exception as e:
        print(f"  ГРЕШКА: {str(e)}")
    
    return ebag_prices


def scrape_kashon(page):
    """Извлича цени от Кашон."""
    kashon_prices = {}
    
    try:
        print(f"\n{'='*60}")
        print("Кашон: Зареждане на продукти на Harmonica")
        print(f"{'='*60}")
        
        page.goto(KASHON_HARMONICA_URL, timeout=60000)
        page.wait_for_timeout(5000)
        
        for _ in range(5):
            page.evaluate("window.scrollBy(0, 1000)")
            page.wait_for_timeout(800)
        
        body_text = page.inner_text('body')
        print(f"  Заредени {len(body_text)} символа")
        
        print(f"\n  Търсене на продукти:")
        for product in PRODUCTS:
            price = find_product_in_page(body_text, product)
            if price:
                kashon_prices[product['name']] = price
        
        print(f"\n  Резултат: {len(kashon_prices)} от {len(PRODUCTS)} продукта")
        
    except Exception as e:
        print(f"  ГРЕШКА: {str(e)}")
    
    return kashon_prices


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
        
        ebag_prices = scrape_ebag(page)
        page.wait_for_timeout(2000)
        kashon_prices = scrape_kashon(page)
        
        browser.close()
        
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
    """
    Прилага визуално форматиране към работния лист.
    Добавя цветове, удебелен шрифт и рамки.
    """
    try:
        # Форматиране на заглавието (ред 1)
        sheet.format('A1:K1', {
            'backgroundColor': {'red': 0.2, 'green': 0.5, 'blue': 0.3},
            'textFormat': {'bold': True, 'fontSize': 14, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
            'horizontalAlignment': 'CENTER'
        })
        
        # Форматиране на метаданните (ред 2)
        sheet.format('A2:K2', {
            'backgroundColor': {'red': 0.9, 'green': 0.95, 'blue': 0.9},
            'textFormat': {'italic': True, 'fontSize': 10}
        })
        
        # Форматиране на заглавията на колоните (ред 4)
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
        
        # Форматиране на данните (редове 5+)
        data_range = f'A5:K{4 + num_products}'
        sheet.format(data_range, {
            'borders': {
                'top': {'style': 'SOLID', 'color': {'red': 0.8, 'green': 0.8, 'blue': 0.8}},
                'bottom': {'style': 'SOLID', 'color': {'red': 0.8, 'green': 0.8, 'blue': 0.8}},
                'left': {'style': 'SOLID', 'color': {'red': 0.8, 'green': 0.8, 'blue': 0.8}},
                'right': {'style': 'SOLID', 'color': {'red': 0.8, 'green': 0.8, 'blue': 0.8}}
            }
        })
        
        # Центриране на числовите колони
        sheet.format(f'A5:A{4 + num_products}', {'horizontalAlignment': 'CENTER'})  # №
        sheet.format(f'D5:I{4 + num_products}', {'horizontalAlignment': 'RIGHT'})   # Цени
        sheet.format(f'J5:K{4 + num_products}', {'horizontalAlignment': 'CENTER'})  # Откл. и Статус
        
        print("  Форматирането е приложено успешно")
        
    except Exception as e:
        print(f"  Предупреждение: Форматирането не можа да бъде приложено: {str(e)}")


def apply_conditional_formatting(sheet, spreadsheet_id, num_products):
    """
    Прилага условно форматиране за статус колоната.
    Зелено за OK, червено за ВНИМАНИЕ, сиво за НЯМА ДАННИ.
    """
    try:
        # За условно форматиране се нуждаем от Sheets API директно
        # Засега използваме ръчно форматиране след записа
        pass
    except Exception as e:
        print(f"  Условното форматиране не можа да бъде приложено: {str(e)}")


def update_main_sheet(gc, spreadsheet_id, results):
    """Актуализира главния работен лист с текущите цени."""
    try:
        sheet = gc.open_by_key(spreadsheet_id).worksheet("Ценови Тракер")
        sheet.clear()
        
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        
        # Записваме данните
        sheet.update(range_name='A1:K1', values=[
            ['HARMONICA - Ценови Тракер', '', '', '', '', '', '', '', '', '', '']
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
                i,
                r['name'],
                r['weight'],
                r['ref_price_bgn'],
                r['ref_price_eur'],
                r['ebag_price'] if r['ebag_price'] else '',
                r['kashon_price'] if r['kashon_price'] else '',
                r['avg_price_bgn'] if r['avg_price_bgn'] else '',
                r['avg_price_eur'] if r['avg_price_eur'] else '',
                f"{r['deviation']}%" if r['deviation'] is not None else '',
                r['status']
            ])
        
        sheet.update(range_name=f'A5:K{4 + len(rows)}', values=rows)
        
        # Прилагаме форматиране
        format_worksheet(sheet, len(rows))
        
        # Оцветяваме статус колоната ръчно
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
            else:  # НЯМА ДАННИ
                sheet.format(f'K{i}', {
                    'backgroundColor': {'red': 0.95, 'green': 0.95, 'blue': 0.95},
                    'textFormat': {'italic': True, 'foregroundColor': {'red': 0.5, 'green': 0.5, 'blue': 0.5}}
                })
        
        print(f"✓ Главният лист е актуализиран")
        
    except Exception as e:
        print(f"✗ Грешка при главния лист: {str(e)}")


def update_history_sheet(gc, spreadsheet_id, results):
    """
    Добавя нов запис в листа с история.
    Всяко изпълнение добавя един ред за всеки продукт.
    """
    try:
        spreadsheet = gc.open_by_key(spreadsheet_id)
        
        # Проверяваме дали листът "История" съществува
        try:
            history_sheet = spreadsheet.worksheet("История")
        except gspread.exceptions.WorksheetNotFound:
            # Създаваме листа ако не съществува
            history_sheet = spreadsheet.add_worksheet(title="История", rows=1000, cols=10)
            
            # Добавяме заглавия
            headers = ['Дата', 'Час', 'Продукт', 'Грамаж', 'eBag', 'Кашон', 'Средна', 'Откл. %', 'Статус']
            history_sheet.update(range_name='A1:I1', values=[headers])
            
            # Форматираме заглавията
            history_sheet.format('A1:I1', {
                'backgroundColor': {'red': 0.2, 'green': 0.4, 'blue': 0.6},
                'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
                'horizontalAlignment': 'CENTER'
            })
            
            # Замразяваме първия ред
            history_sheet.freeze(rows=1)
            
            print("  Създаден нов лист 'История'")
        
        # Подготвяме новите редове
        now = datetime.now()
        date_str = now.strftime("%d.%m.%Y")
        time_str = now.strftime("%H:%M")
        
        new_rows = []
        for r in results:
            new_rows.append([
                date_str,
                time_str,
                r['name'],
                r['weight'],
                r['ebag_price'] if r['ebag_price'] else '',
                r['kashon_price'] if r['kashon_price'] else '',
                r['avg_price_bgn'] if r['avg_price_bgn'] else '',
                f"{r['deviation']}%" if r['deviation'] is not None else '',
                r['status']
            ])
        
        # Добавяме редовете в края на листа
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
        
        # Актуализираме главния лист
        update_main_sheet(gc, spreadsheet_id, results)
        
        # Добавяме в историята
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
    print("=" * 60)
    print("HARMONICA PRICE TRACKER v4.0")
    print(f"Време: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"Продукти: {len(PRODUCTS)}")
    print(f"Праг за известия: {ALERT_THRESHOLD}%")
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
