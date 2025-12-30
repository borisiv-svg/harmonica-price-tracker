"""
Harmonica Price Tracker
Автоматизирано събиране на цени от български онлайн магазини.
"""

import os
import json
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

# Фиксиран курс за конвертиране BGN/EUR (официален курс за еврозоната)
EUR_RATE = 1.95583

# Праг за известия (в проценти)
ALERT_THRESHOLD = 10

# Продукти за проследяване с референтни цени от Кашон Harmonica
PRODUCTS = [
    {
        "name": "Био Локум роза",
        "weight": "140г",
        "ref_price_bgn": 3.81,
        "ref_price_eur": 1.95,
        "search_terms": ["локум роза", "lokum roza"],
    },
    {
        "name": "Био Обикновени бисквити с краве масло",
        "weight": "150г",
        "ref_price_bgn": 4.18,
        "ref_price_eur": 2.14,
        "search_terms": ["бисквити краве масло", "biskviti maslo"],
    },
    {
        "name": "Айран harmonica",
        "weight": "500мл",
        "ref_price_bgn": 2.90,
        "ref_price_eur": 1.48,
        "search_terms": ["айран", "ayran"],
    },
    {
        "name": "Био Тунквана вафла без захар",
        "weight": "40г",
        "ref_price_bgn": 2.62,
        "ref_price_eur": 1.34,
        "search_terms": ["вафла без захар", "vafla bez zahar"],
    },
    {
        "name": "Био Оризови топчета с черен шоколад",
        "weight": "50г",
        "ref_price_bgn": 4.99,
        "ref_price_eur": 2.55,
        "search_terms": ["оризови топчета шоколад", "orizovi topcheta"],
    },
    {
        "name": "Био лимонада",
        "weight": "330мл",
        "ref_price_bgn": 3.48,
        "ref_price_eur": 1.78,
        "search_terms": ["лимонада", "limonada"],
    },
    {
        "name": "Био тънки претцели с морска сол",
        "weight": "80г",
        "ref_price_bgn": 2.50,
        "ref_price_eur": 1.28,
        "search_terms": ["претцели сол", "pretzeli"],
    },
    {
        "name": "Био тунквана вафла Класика",
        "weight": "40г",
        "ref_price_bgn": 2.00,
        "ref_price_eur": 1.02,
        "search_terms": ["вафла класика", "vafla klasika"],
    },
    {
        "name": "Био вафла без добавена захар",
        "weight": "30г",
        "ref_price_bgn": 1.44,
        "ref_price_eur": 0.74,
        "search_terms": ["вафла 30g", "vafla 30"],
    },
    {
        "name": "Био сироп от липа",
        "weight": "750мл",
        "ref_price_bgn": 14.29,
        "ref_price_eur": 7.31,
        "search_terms": ["сироп липа", "sirop lipa"],
    },
    {
        "name": "Био Пасирани домати",
        "weight": "680г",
        "ref_price_bgn": 5.90,
        "ref_price_eur": 3.02,
        "search_terms": ["пасирани домати", "pasirani domati"],
    },
    {
        "name": "Smiles с нахут и морска сол",
        "weight": "50г",
        "ref_price_bgn": 2.81,
        "ref_price_eur": 1.44,
        "search_terms": ["smiles нахут", "smiles nahut"],
    },
    {
        "name": "Био Крема сирене",
        "weight": "125г",
        "ref_price_bgn": 5.46,
        "ref_price_eur": 2.79,
        "search_terms": ["крема сирене", "krema sirene"],
    },
    {
        "name": "Козе сирене harmonica",
        "weight": "200г",
        "ref_price_bgn": 10.70,
        "ref_price_eur": 5.47,
        "search_terms": ["козе сирене", "koze sirene"],
    },
]

# =============================================================================
# ФУНКЦИИ ЗА SCRAPING
# =============================================================================

def scrape_ebag(page, product_name, search_terms):
    """
    Търси продукт в eBag.bg и извлича цената.
    Връща цената в лева или None ако продуктът не е намерен.
    """
    try:
        # Формираме URL за търсене
        search_query = f"harmonica {search_terms[0]}"
        search_url = f"https://www.ebag.bg/search?q={search_query.replace(' ', '+')}"
        
        print(f"  eBag: Търсене на '{search_query}'...")
        page.goto(search_url, timeout=30000)
        page.wait_for_timeout(2000)  # Изчакваме JavaScript да зареди
        
        # Опитваме различни селектори за цена
        price_selectors = [
            ".product-price",
            ".price",
            "[data-price]",
            ".current-price",
            ".product-item .price"
        ]
        
        for selector in price_selectors:
            elements = page.query_selector_all(selector)
            for element in elements:
                text = element.inner_text()
                # Търсим цена във формат XX.XX или XX,XX
                import re
                match = re.search(r'(\d+)[,.](\d{2})', text)
                if match:
                    price = float(f"{match.group(1)}.{match.group(2)}")
                    if 0.5 < price < 100:  # Разумен диапазон за цени
                        print(f"    Намерена цена: {price:.2f} лв.")
                        return price
        
        print(f"    Цена не е намерена")
        return None
        
    except Exception as e:
        print(f"    Грешка: {str(e)}")
        return None


def scrape_kashon(page, product_name, search_terms):
    """
    Търси продукт в kashonharmonica.bg и извлича цената.
    Връща цената в лева или None ако продуктът не е намерен.
    """
    try:
        # Отиваме на страницата с продукти на Harmonica
        products_url = "https://kashonharmonica.bg/bg/products/field_producer/harmonica-144"
        
        print(f"  Кашон: Търсене на '{product_name}'...")
        page.goto(products_url, timeout=30000)
        page.wait_for_timeout(2000)
        
        # Търсим продукта по име в страницата
        content = page.content().lower()
        search_term = search_terms[0].lower()
        
        if search_term in content:
            # Опитваме да намерим цената близо до името на продукта
            import re
            # Търсим всички цени на страницата
            prices = re.findall(r'(\d+)[,.](\d{2})\s*(?:лв|bgn|€|eur)', content, re.IGNORECASE)
            
            if prices:
                # Вземаме първата намерена цена (може да се подобри с по-точно търсене)
                price = float(f"{prices[0][0]}.{prices[0][1]}")
                if 0.5 < price < 100:
                    print(f"    Намерена цена: {price:.2f} лв.")
                    return price
        
        print(f"    Цена не е намерена")
        return None
        
    except Exception as e:
        print(f"    Грешка: {str(e)}")
        return None


def collect_prices():
    """
    Събира цени от всички магазини за всички продукти.
    Връща списък с резултати.
    """
    results = []
    
    with sync_playwright() as p:
        # Стартираме браузър в headless режим
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="bg-BG"
        )
        page = context.new_page()
        
        for product in PRODUCTS:
            print(f"\n{'='*50}")
            print(f"Продукт: {product['name']} ({product['weight']})")
            print(f"{'='*50}")
            
            # Събираме цени от всеки магазин
            ebag_price = scrape_ebag(page, product['name'], product['search_terms'])
            kashon_price = scrape_kashon(page, product['name'], product['search_terms'])
            
            # Изчисляваме средна цена и отклонение
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
                "name": product['name'],
                "weight": product['weight'],
                "ref_price_bgn": product['ref_price_bgn'],
                "ref_price_eur": product['ref_price_eur'],
                "ebag_price": ebag_price,
                "kashon_price": kashon_price,
                "avg_price_bgn": round(avg_price, 2) if avg_price else None,
                "avg_price_eur": round(avg_price_eur, 2) if avg_price_eur else None,
                "deviation": round(deviation, 1) if deviation else None,
                "status": status
            })
            
            # Пауза между продуктите за да не натоварваме сайтовете
            page.wait_for_timeout(1000)
        
        browser.close()
    
    return results


# =============================================================================
# GOOGLE SHEETS ФУНКЦИИ
# =============================================================================

def get_sheets_client():
    """
    Създава клиент за Google Sheets API използвайки service account credentials.
    Credentials се взимат от environment variable GOOGLE_CREDENTIALS.
    """
    credentials_json = os.environ.get('GOOGLE_CREDENTIALS')
    if not credentials_json:
        raise ValueError("GOOGLE_CREDENTIALS environment variable не е зададена")
    
    credentials_dict = json.loads(credentials_json)
    
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    
    credentials = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
    return gspread.authorize(credentials)


def update_google_sheets(results):
    """
    Записва резултатите в Google Sheets.
    """
    spreadsheet_id = os.environ.get('SPREADSHEET_ID')
    if not spreadsheet_id:
        print("SPREADSHEET_ID не е зададен, пропускам записа в Google Sheets")
        return
    
    try:
        gc = get_sheets_client()
        sheet = gc.open_by_key(spreadsheet_id).worksheet("Ценови Тракер")
        
        # Изчистваме старите данни
        sheet.clear()
        
        # Заглавие и метаданни
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        sheet.update('A1:L2', [
            ['HARMONICA - Ценови Тракер', '', '', '', '', '', '', '', '', '', '', ''],
            ['Последна актуализация:', now, '', '', 'Курс:', f'{EUR_RATE} лв/EUR', '', '', '', '', '', '']
        ])
        
        # Заглавия на колоните
        headers = ['№', 'Продукт', 'Грамаж', 'Реф. BGN', 'Реф. EUR', 
                   'eBag', 'Кашон', 'Ср. BGN', 'Ср. EUR', 'Откл. %', 'Статус']
        sheet.update('A4:K4', [headers])
        
        # Данни за продуктите
        rows = []
        for i, r in enumerate(results, 1):
            rows.append([
                i,
                r['name'],
                r['weight'],
                r['ref_price_bgn'],
                r['ref_price_eur'],
                r['ebag_price'] or '',
                r['kashon_price'] or '',
                r['avg_price_bgn'] or '',
                r['avg_price_eur'] or '',
                f"{r['deviation']}%" if r['deviation'] else '',
                r['status']
            ])
        
        sheet.update(f'A5:K{4 + len(rows)}', rows)
        print(f"\n✓ Google Sheets актуализиран успешно")
        
    except Exception as e:
        print(f"\n✗ Грешка при запис в Google Sheets: {str(e)}")


# =============================================================================
# ИМЕЙЛ ИЗВЕСТИЯ
# =============================================================================

def send_email_alert(alerts):
    """
    Изпраща имейл известие за продукти с ценови отклонения над прага.
    """
    gmail_user = os.environ.get('GMAIL_USER')
    gmail_password = os.environ.get('GMAIL_APP_PASSWORD')
    recipient = os.environ.get('ALERT_EMAIL', gmail_user)
    
    if not gmail_user or not gmail_password:
        print("Gmail credentials не са зададени, пропускам имейл известията")
        return
    
    if not alerts:
        print("Няма продукти с отклонения над прага, не изпращам имейл")
        return
    
    # Създаваме съдържанието на имейла
    subject = f"🚨 Harmonica: {len(alerts)} продукта с ценови промени над {ALERT_THRESHOLD}%"
    
    body = f"""
Здравей,

Открити са {len(alerts)} продукта с ценови отклонения над {ALERT_THRESHOLD}%:

"""
    for alert in alerts:
        body += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📦 {alert['name']} ({alert['weight']})
   Референтна цена: {alert['ref_price_bgn']:.2f} лв / {alert['ref_price_eur']:.2f} €
   Средна цена: {alert['avg_price_bgn']:.2f} лв / {alert['avg_price_eur']:.2f} €
   Отклонение: {alert['deviation']:+.1f}%
   eBag: {alert['ebag_price'] or 'N/A'} лв
   Кашон: {alert['kashon_price'] or 'N/A'} лв
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
        msg['To'] = recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(gmail_user, gmail_password)
            server.send_message(msg)
        
        print(f"\n✓ Имейл известие изпратено до {recipient}")
        
    except Exception as e:
        print(f"\n✗ Грешка при изпращане на имейл: {str(e)}")


# =============================================================================
# ГЛАВНА ФУНКЦИЯ
# =============================================================================

def main():
    """
    Главна функция - събира цени, записва в Sheets и изпраща известия.
    """
    print("=" * 60)
    print("HARMONICA PRICE TRACKER")
    print(f"Време: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"Продукти: {len(PRODUCTS)}")
    print(f"Праг за известия: {ALERT_THRESHOLD}%")
    print("=" * 60)
    
    # Събираме цените
    results = collect_prices()
    
    # Записваме в Google Sheets
    update_google_sheets(results)
    
    # Намираме продукти с отклонения над прага
    alerts = [r for r in results if r['deviation'] and abs(r['deviation']) > ALERT_THRESHOLD]
    
    # Изпращаме имейл ако има такива
    send_email_alert(alerts)
    
    # Отпечатваме обобщение
    print("\n" + "=" * 60)
    print("ОБОБЩЕНИЕ")
    print("=" * 60)
    
    products_with_prices = len([r for r in results if r['avg_price_bgn']])
    print(f"Продукти с намерени цени: {products_with_prices}/{len(results)}")
    print(f"Продукти с отклонения: {len(alerts)}")
    
    if alerts:
        print("\nПродукти с внимание:")
        for a in alerts:
            print(f"  • {a['name']}: {a['deviation']:+.1f}%")
    
    print("\n✓ Готово!")


if __name__ == "__main__":
    main()
