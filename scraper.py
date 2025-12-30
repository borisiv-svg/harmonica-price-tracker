"""
Harmonica Price Tracker v3.1
Използва директни URL адреси за филтриране по марка.
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

# =============================================================================
# КОНФИГУРАЦИЯ
# =============================================================================

EUR_RATE = 1.95583
ALERT_THRESHOLD = 10

# Директни URL адреси към страниците с всички Harmonica продукти
EBAG_HARMONICA_URL = "https://www.ebag.bg/search/?products%5BrefinementList%5D%5Bbrand_name_bg%5D%5B0%5D=%D0%A5%D0%B0%D1%80%D0%BC%D0%BE%D0%BD%D0%B8%D0%BA%D0%B0"
KASHON_HARMONICA_URL = "https://kashonharmonica.bg/bg/products/field_producer/harmonica-144"

# Продукти с ключови думи за търсене в текста на страницата
# Ключовите думи са подредени по специфичност - първо по-уникалните
PRODUCTS = [
    {
        "name": "Био Локум роза",
        "weight": "140г",
        "ref_price_bgn": 3.81,
        "ref_price_eur": 1.95,
        "keywords": ["локум роза", "локум", "роза 140"]
    },
    {
        "name": "Био Обикновени бисквити с краве масло",
        "weight": "150г",
        "ref_price_bgn": 4.18,
        "ref_price_eur": 2.14,
        "keywords": ["бисквити с краве масло", "бисквити краве", "краве масло 150"]
    },
    {
        "name": "Айран harmonica",
        "weight": "500мл",
        "ref_price_bgn": 2.90,
        "ref_price_eur": 1.48,
        "keywords": ["айран 500", "айран"]
    },
    {
        "name": "Био Тунквана вафла без захар",
        "weight": "40г",
        "ref_price_bgn": 2.62,
        "ref_price_eur": 1.34,
        "keywords": ["тунквана вафла без захар", "вафла без захар 40"]
    },
    {
        "name": "Био Оризови топчета с черен шоколад",
        "weight": "50г",
        "ref_price_bgn": 4.99,
        "ref_price_eur": 2.55,
        "keywords": ["оризови топчета", "топчета шоколад", "топчета 50"]
    },
    {
        "name": "Био лимонада",
        "weight": "330мл",
        "ref_price_bgn": 3.48,
        "ref_price_eur": 1.78,
        "keywords": ["лимонада 330", "био лимонада"]
    },
    {
        "name": "Био тънки претцели с морска сол",
        "weight": "80г",
        "ref_price_bgn": 2.50,
        "ref_price_eur": 1.28,
        "keywords": ["претцели", "претцели сол", "претцели 80"]
    },
    {
        "name": "Био тунквана вафла Класика",
        "weight": "40г",
        "ref_price_bgn": 2.00,
        "ref_price_eur": 1.02,
        "keywords": ["тунквана вафла класика", "вафла класика 40"]
    },
    {
        "name": "Био вафла без добавена захар",
        "weight": "30г",
        "ref_price_bgn": 1.44,
        "ref_price_eur": 0.74,
        "keywords": ["вафла без добавена захар", "вафла 30г", "вафла 30"]
    },
    {
        "name": "Био сироп от липа",
        "weight": "750мл",
        "ref_price_bgn": 14.29,
        "ref_price_eur": 7.31,
        "keywords": ["сироп от липа", "сироп липа", "липа 750"]
    },
    {
        "name": "Био Пасирани домати",
        "weight": "680г",
        "ref_price_bgn": 5.90,
        "ref_price_eur": 3.02,
        "keywords": ["пасирани домати", "домати 680"]
    },
    {
        "name": "Smiles с нахут и морска сол",
        "weight": "50г",
        "ref_price_bgn": 2.81,
        "ref_price_eur": 1.44,
        "keywords": ["smiles нахут", "smiles", "нахут сол"]
    },
    {
        "name": "Био Крема сирене",
        "weight": "125г",
        "ref_price_bgn": 5.46,
        "ref_price_eur": 2.79,
        "keywords": ["крема сирене", "крема 125"]
    },
    {
        "name": "Козе сирене harmonica",
        "weight": "200г",
        "ref_price_bgn": 10.70,
        "ref_price_eur": 5.47,
        "keywords": ["козе сирене", "козе 200"]
    },
]


def extract_price_from_context(text):
    """
    Извлича цена от текст. Търси формат X.XX лв или X,XX лв.
    Връща първата валидна цена или None.
    """
    if not text:
        return None
    
    # Търсим всички цени във формат "XX.XX лв" или "XX,XX лв"
    matches = re.findall(r'(\d+)[,.](\d{2})\s*лв', text, re.IGNORECASE)
    
    for match in matches:
        try:
            price = float(f"{match[0]}.{match[1]}")
            # Филтрираме нереалистични цени
            if 0.50 < price < 200:
                return price
        except:
            continue
    
    return None


def find_product_in_page(page_text, product):
    """
    Търси продукт в текста на страницата по ключови думи.
    Връща цената ако намери продукта, иначе None.
    
    Алгоритъмът работи така:
    1. За всяка ключова дума търсим дали съществува в текста
    2. Ако намерим съвпадение, вземаме контекст около него (текст преди и след)
    3. В този контекст търсим цена във формат XX.XX лв
    """
    page_text_lower = page_text.lower()
    
    for keyword in product['keywords']:
        keyword_lower = keyword.lower()
        
        # Търсим ключовата дума в текста
        idx = page_text_lower.find(keyword_lower)
        
        if idx != -1:
            # Намерихме ключовата дума! Вземаме контекст около нея.
            # Контекстът е 50 символа преди и 100 след - достатъчно за да хванем цената
            start = max(0, idx - 50)
            end = min(len(page_text), idx + len(keyword) + 100)
            context = page_text[start:end]
            
            # Търсим цена в контекста
            price = extract_price_from_context(context)
            
            if price:
                print(f"    ✓ {product['name']}: {price:.2f} лв (ключ: '{keyword}')")
                return price
    
    return None


def scrape_ebag(page):
    """
    Зарежда страницата с всички Harmonica продукти в eBag
    и извлича цените за всеки продукт от списъка.
    
    Използваме директен URL с филтър по марка "Хармоника",
    което е по-надеждно от търсене.
    """
    ebag_prices = {}
    
    try:
        print(f"\n{'='*60}")
        print("eBag: Зареждане на продукти на Хармоника")
        print(f"{'='*60}")
        print(f"  URL: {EBAG_HARMONICA_URL[:80]}...")
        
        # Зареждаме страницата с филтрирани продукти
        page.goto(EBAG_HARMONICA_URL, timeout=60000)
        
        # Изчакваме страницата да се зареди напълно
        # eBag използва JavaScript за рендиране, затова даваме повече време
        page.wait_for_timeout(5000)
        
        # Опитваме да приемем бисквитките ако има такъв диалог
        try:
            cookie_selectors = [
                'button:has-text("Приемам")',
                'button:has-text("Съгласен")',
                'button:has-text("Accept")',
                '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',
                '[class*="cookie"] button',
            ]
            
            for selector in cookie_selectors:
                btn = page.query_selector(selector)
                if btn:
                    btn.click()
                    print(f"  Бисквитки приети")
                    page.wait_for_timeout(2000)
                    break
        except:
            pass  # Ако няма диалог за бисквитки, продължаваме
        
        # Скролваме надолу за да заредим повече продукти (lazy loading)
        for _ in range(3):
            page.evaluate("window.scrollBy(0, 1000)")
            page.wait_for_timeout(1000)
        
        # Вземаме целия текст на страницата
        body_text = page.inner_text('body')
        print(f"  Заредени {len(body_text)} символа текст")
        
        # Търсим цена за всеки продукт
        print(f"\n  Търсене на продукти:")
        for product in PRODUCTS:
            price = find_product_in_page(body_text, product)
            if price:
                ebag_prices[product['name']] = price
        
        found_count = len(ebag_prices)
        print(f"\n  Резултат: Намерени {found_count} от {len(PRODUCTS)} продукта")
        
    except Exception as e:
        print(f"  ГРЕШКА: {str(e)}")
    
    return ebag_prices


def scrape_kashon(page):
    """
    Зарежда страницата с всички Harmonica продукти в Кашон
    и извлича цените за всеки продукт от списъка.
    
    Кашон е официалният онлайн магазин на Harmonica,
    затова там трябва да има всички продукти.
    """
    kashon_prices = {}
    
    try:
        print(f"\n{'='*60}")
        print("Кашон: Зареждане на продукти на Harmonica")
        print(f"{'='*60}")
        print(f"  URL: {KASHON_HARMONICA_URL}")
        
        # Зареждаме страницата
        page.goto(KASHON_HARMONICA_URL, timeout=60000)
        page.wait_for_timeout(5000)
        
        # Скролваме за да заредим всички продукти
        for _ in range(5):
            page.evaluate("window.scrollBy(0, 1000)")
            page.wait_for_timeout(800)
        
        # Вземаме целия текст
        body_text = page.inner_text('body')
        print(f"  Заредени {len(body_text)} символа текст")
        
        # Търсим цена за всеки продукт
        print(f"\n  Търсене на продукти:")
        for product in PRODUCTS:
            price = find_product_in_page(body_text, product)
            if price:
                kashon_prices[product['name']] = price
        
        found_count = len(kashon_prices)
        print(f"\n  Резултат: Намерени {found_count} от {len(PRODUCTS)} продукта")
        
    except Exception as e:
        print(f"  ГРЕШКА: {str(e)}")
    
    return kashon_prices


def collect_prices():
    """
    Главна функция за събиране на цени.
    Отваря браузър, посещава двата магазина и събира цените.
    """
    results = []
    
    with sync_playwright() as p:
        # Стартираме браузър в headless режим (без видим прозорец)
        browser = p.chromium.launch(headless=True)
        
        # Създаваме контекст с реалистични настройки
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="bg-BG",
            viewport={"width": 1920, "height": 1080}
        )
        
        page = context.new_page()
        
        # Събираме цени от двата магазина
        ebag_prices = scrape_ebag(page)
        page.wait_for_timeout(2000)
        
        kashon_prices = scrape_kashon(page)
        
        browser.close()
        
        # Обработваме резултатите за всеки продукт
        print(f"\n{'='*60}")
        print("Обработка на резултатите")
        print(f"{'='*60}")
        
        for product in PRODUCTS:
            name = product['name']
            
            ebag_price = ebag_prices.get(name)
            kashon_price = kashon_prices.get(name)
            
            # Събираме валидните цени
            prices = [p for p in [ebag_price, kashon_price] if p is not None]
            
            if prices:
                # Изчисляваме средна цена
                avg_price = sum(prices) / len(prices)
                avg_price_eur = avg_price / EUR_RATE
                
                # Изчисляваме отклонение от референтната цена
                deviation = ((avg_price - product['ref_price_bgn']) / product['ref_price_bgn']) * 100
                
                # Определяме статус
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


def update_google_sheets(results):
    """Записва резултатите в Google Sheets."""
    spreadsheet_id = os.environ.get('SPREADSHEET_ID')
    if not spreadsheet_id:
        print("SPREADSHEET_ID не е зададен")
        return
    
    try:
        gc = get_sheets_client()
        sheet = gc.open_by_key(spreadsheet_id).worksheet("Ценови Тракер")
        
        # Изчистваме старите данни
        sheet.clear()
        
        # Заглавие и метаданни
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        sheet.update(range_name='A1:L2', values=[
            ['HARMONICA - Ценови Тракер', '', '', '', '', '', '', '', '', '', '', ''],
            ['Последна актуализация:', now, '', '', 'Курс:', f'{EUR_RATE} лв/EUR', '', '', '', '', '', '']
        ])
        
        # Заглавия на колоните
        headers = ['№', 'Продукт', 'Грамаж', 'Реф. BGN', 'Реф. EUR', 
                   'eBag', 'Кашон', 'Ср. BGN', 'Ср. EUR', 'Откл. %', 'Статус']
        sheet.update(range_name='A4:K4', values=[headers])
        
        # Данни за продуктите
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
    
    body += f"""
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
    """Главна функция - координира целия процес."""
    print("=" * 60)
    print("HARMONICA PRICE TRACKER v3.1")
    print(f"Време: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"Продукти: {len(PRODUCTS)}")
    print(f"Праг за известия: {ALERT_THRESHOLD}%")
    print("=" * 60)
    
    # Събираме цените
    results = collect_prices()
    
    # Записваме в Google Sheets
    update_google_sheets(results)
    
    # Намираме продукти с отклонения над прага
    alerts = [r for r in results if r['deviation'] is not None and abs(r['deviation']) > ALERT_THRESHOLD]
    
    # Изпращаме имейл ако има такива
    send_email_alert(alerts)
    
    # Отпечатваме обобщение
    print(f"\n{'='*60}")
    print("ОБОБЩЕНИЕ")
    print(f"{'='*60}")
    
    products_with_ebag = len([r for r in results if r['ebag_price']])
    products_with_kashon = len([r for r in results if r['kashon_price']])
    products_with_any = len([r for r in results if r['ebag_price'] or r['kashon_price']])
    
    print(f"Продукти с намерени цени: {products_with_any}/{len(results)}")
    print(f"  - от eBag: {products_with_ebag}")
    print(f"  - от Кашон: {products_with_kashon}")
    print(f"Продукти с отклонения над {ALERT_THRESHOLD}%: {len(alerts)}")
    
    if alerts:
        print(f"\nПродукти, изискващи внимание:")
        for a in alerts:
            print(f"  • {a['name']}: {a['deviation']:+.1f}%")
    
    print(f"\n{'='*60}")
    print("✓ Готово!")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
