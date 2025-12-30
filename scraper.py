"""
Harmonica Price Tracker v2.0
Подобрена версия с по-точно извличане на цени.
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

# Продукти с директни URL адреси за по-точно извличане
PRODUCTS = [
    {
        "name": "Био Локум роза",
        "weight": "140г",
        "ref_price_bgn": 3.81,
        "ref_price_eur": 1.95,
        "ebag_search": "harmonica локум роза",
        "kashon_url": "https://kashonharmonica.bg/bg/products/sweets"
    },
    {
        "name": "Био Обикновени бисквити с краве масло",
        "weight": "150г",
        "ref_price_bgn": 4.18,
        "ref_price_eur": 2.14,
        "ebag_search": "harmonica бисквити краве масло",
        "kashon_url": "https://kashonharmonica.bg/bg/products/sweets"
    },
    {
        "name": "Айран harmonica",
        "weight": "500мл",
        "ref_price_bgn": 2.90,
        "ref_price_eur": 1.48,
        "ebag_search": "harmonica айран",
        "kashon_url": "https://kashonharmonica.bg/bg/products/dairy"
    },
    {
        "name": "Био Тунквана вафла без захар",
        "weight": "40г",
        "ref_price_bgn": 2.62,
        "ref_price_eur": 1.34,
        "ebag_search": "harmonica вафла без захар",
        "kashon_url": "https://kashonharmonica.bg/bg/products/sweets"
    },
    {
        "name": "Био Оризови топчета с черен шоколад",
        "weight": "50г",
        "ref_price_bgn": 4.99,
        "ref_price_eur": 2.55,
        "ebag_search": "harmonica оризови топчета",
        "kashon_url": "https://kashonharmonica.bg/bg/products/sweets"
    },
    {
        "name": "Био лимонада",
        "weight": "330мл",
        "ref_price_bgn": 3.48,
        "ref_price_eur": 1.78,
        "ebag_search": "harmonica лимонада био",
        "kashon_url": "https://kashonharmonica.bg/bg/products/drinks"
    },
    {
        "name": "Био тънки претцели с морска сол",
        "weight": "80г",
        "ref_price_bgn": 2.50,
        "ref_price_eur": 1.28,
        "ebag_search": "harmonica претцели",
        "kashon_url": "https://kashonharmonica.bg/bg/products/snacks"
    },
    {
        "name": "Био тунквана вафла Класика",
        "weight": "40г",
        "ref_price_bgn": 2.00,
        "ref_price_eur": 1.02,
        "ebag_search": "harmonica вафла класика",
        "kashon_url": "https://kashonharmonica.bg/bg/products/sweets"
    },
    {
        "name": "Био вафла без добавена захар",
        "weight": "30г",
        "ref_price_bgn": 1.44,
        "ref_price_eur": 0.74,
        "ebag_search": "harmonica вафла 30",
        "kashon_url": "https://kashonharmonica.bg/bg/products/sweets"
    },
    {
        "name": "Био сироп от липа",
        "weight": "750мл",
        "ref_price_bgn": 14.29,
        "ref_price_eur": 7.31,
        "ebag_search": "harmonica сироп липа",
        "kashon_url": "https://kashonharmonica.bg/bg/products/cordials"
    },
    {
        "name": "Био Пасирани домати",
        "weight": "680г",
        "ref_price_bgn": 5.90,
        "ref_price_eur": 3.02,
        "ebag_search": "harmonica пасирани домати",
        "kashon_url": "https://kashonharmonica.bg/bg/products/canned"
    },
    {
        "name": "Smiles с нахут и морска сол",
        "weight": "50г",
        "ref_price_bgn": 2.81,
        "ref_price_eur": 1.44,
        "ebag_search": "harmonica smiles нахут",
        "kashon_url": "https://kashonharmonica.bg/bg/products/snacks"
    },
    {
        "name": "Био Крема сирене",
        "weight": "125г",
        "ref_price_bgn": 5.46,
        "ref_price_eur": 2.79,
        "ebag_search": "harmonica крема сирене",
        "kashon_url": "https://kashonharmonica.bg/bg/products/dairy"
    },
    {
        "name": "Козе сирене harmonica",
        "weight": "200г",
        "ref_price_bgn": 10.70,
        "ref_price_eur": 5.47,
        "ebag_search": "harmonica козе сирене",
        "kashon_url": "https://kashonharmonica.bg/bg/products/dairy"
    },
]


# =============================================================================
# ПОМОЩНИ ФУНКЦИИ
# =============================================================================

def extract_price_from_text(text):
    """
    Извлича цена от текст. Търси формати като "3.81 лв", "3,81 лв", "3.81 BGN".
    Връща float или None.
    """
    if not text:
        return None
    
    # Премахваме излишни интервали
    text = ' '.join(text.split())
    
    # Търсим различни формати на цени
    patterns = [
        r'(\d+)[,.](\d{2})\s*(?:лв|лева|BGN)',  # 3.81 лв, 3,81 лева, 3.81 BGN
        r'(\d+)[,.](\d{2})\s*(?:€|EUR|eur)',     # 3.81 €, 3.81 EUR
        r'BGN\s*(\d+)[,.](\d{2})',               # BGN 3.81
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                price = float(f"{match.group(1)}.{match.group(2)}")
                if 0.5 < price < 200:  # Разумен диапазон
                    return price
            except:
                continue
    
    return None


def normalize_product_name(name):
    """
    Нормализира име на продукт за сравнение.
    Премахва специални символи, малки букви, премахва 'био', 'harmonica'.
    """
    name = name.lower()
    # Премахваме общи думи, които не помагат за идентификация
    for word in ['био', 'harmonica', 'хармоника', 'organic', 'bg', 'бг']:
        name = name.replace(word, '')
    # Премахваме специални символи
    name = re.sub(r'[^\w\s]', '', name)
    # Премахваме излишни интервали
    name = ' '.join(name.split())
    return name


# =============================================================================
# SCRAPING ФУНКЦИИ
# =============================================================================

def scrape_ebag(page, product):
    """
    Търси продукт в eBag.bg чрез търсачката и извлича цената.
    """
    try:
        search_query = product['ebag_search']
        search_url = f"https://www.ebag.bg/search?q={search_query.replace(' ', '+')}"
        
        print(f"  eBag: Търсене '{search_query}'")
        page.goto(search_url, timeout=30000)
        page.wait_for_timeout(3000)  # Изчакваме JavaScript
        
        # Проверяваме дали има резултати
        content = page.content()
        
        if "Няма намерени продукти" in content or "no results" in content.lower():
            print(f"    Няма резултати от търсенето")
            return None
        
        # Търсим продуктови карти
        product_cards = page.query_selector_all('[class*="product"], [class*="item"], [data-product]')
        
        if not product_cards:
            # Опитваме алтернативни селектори
            product_cards = page.query_selector_all('.products-list > div, .product-list > div, .search-results > div')
        
        print(f"    Намерени {len(product_cards)} продуктови карти")
        
        # Търсим в първите няколко резултата
        for i, card in enumerate(product_cards[:5]):
            try:
                card_text = card.inner_text()
                card_html = card.inner_html()
                
                # Проверяваме дали картата съдържа ключови думи от продукта
                product_keywords = normalize_product_name(product['name']).split()
                card_text_normalized = normalize_product_name(card_text)
                
                # Броим колко ключови думи съвпадат
                matches = sum(1 for kw in product_keywords if kw in card_text_normalized)
                
                if matches >= 2 or 'harmonica' in card_text.lower():
                    # Търсим цена в тази карта
                    price = extract_price_from_text(card_text)
                    if price:
                        print(f"    Намерена цена: {price:.2f} лв (карта {i+1})")
                        return price
            except Exception as e:
                continue
        
        # Ако не намерим в картите, търсим първата цена на страницата
        all_text = page.inner_text('body')
        price = extract_price_from_text(all_text)
        if price:
            print(f"    Намерена цена (fallback): {price:.2f} лв")
            return price
        
        print(f"    Цена не е намерена")
        return None
        
    except Exception as e:
        print(f"    Грешка: {str(e)[:100]}")
        return None


def scrape_kashon(page, product):
    """
    Търси продукт в kashonharmonica.bg и извлича цената.
    Използва категорийната страница и търси конкретния продукт.
    """
    try:
        url = product.get('kashon_url', 'https://kashonharmonica.bg/bg/products/field_producer/harmonica-144')
        
        print(f"  Кашон: {url}")
        page.goto(url, timeout=30000)
        page.wait_for_timeout(3000)
        
        # Вземаме ключови думи от името на продукта
        product_keywords = normalize_product_name(product['name']).split()
        
        # Търсим всички продуктови елементи на страницата
        # Опитваме различни селектори
        selectors_to_try = [
            '.views-row',
            '.product-item',
            '.product',
            '[class*="product"]',
            '.node--type-product',
            'article',
            '.field--name-title'
        ]
        
        product_elements = []
        for selector in selectors_to_try:
            elements = page.query_selector_all(selector)
            if elements:
                product_elements = elements
                print(f"    Намерени {len(elements)} елемента със селектор '{selector}'")
                break
        
        if not product_elements:
            print(f"    Не са намерени продуктови елементи")
            # Fallback: търсим в цялата страница
            full_text = page.inner_text('body')
            
            # Търсим името на продукта
            if any(kw in full_text.lower() for kw in product_keywords if len(kw) > 3):
                price = extract_price_from_text(full_text)
                if price:
                    print(f"    Намерена цена (fallback): {price:.2f} лв")
                    return price
            return None
        
        # Търсим продукта по име в елементите
        best_match = None
        best_match_score = 0
        
        for element in product_elements:
            try:
                element_text = element.inner_text().lower()
                
                # Изчисляваме score базиран на съвпадащи ключови думи
                score = sum(1 for kw in product_keywords if kw in element_text and len(kw) > 2)
                
                # Допълнителни точки за съвпадение на грамаж
                weight = product['weight'].lower().replace('г', '').replace('мл', '').strip()
                if weight in element_text:
                    score += 2
                
                if score > best_match_score:
                    best_match_score = score
                    best_match = element
                    
            except:
                continue
        
        if best_match and best_match_score >= 2:
            element_text = best_match.inner_text()
            price = extract_price_from_text(element_text)
            if price:
                print(f"    Намерена цена: {price:.2f} лв (score: {best_match_score})")
                return price
        
        print(f"    Продуктът не е намерен (best score: {best_match_score})")
        return None
        
    except Exception as e:
        print(f"    Грешка: {str(e)[:100]}")
        return None


def collect_prices():
    """
    Събира цени от всички магазини за всички продукти.
    """
    results = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="bg-BG",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()
        
        # Блокираме ненужни ресурси за по-бързо зареждане
        page.route("**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2}", lambda route: route.abort())
        
        for product in PRODUCTS:
            print(f"\n{'='*60}")
            print(f"Продукт: {product['name']} ({product['weight']})")
            print(f"{'='*60}")
            
            ebag_price = scrape_ebag(page, product)
            page.wait_for_timeout(1500)  # Пауза между заявките
            
            kashon_price = scrape_kashon(page, product)
            page.wait_for_timeout(1500)
            
            # Изчисляваме статистики
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
                "deviation": round(deviation, 1) if deviation is not None else None,
                "status": status
            })
        
        browser.close()
    
    return results


# =============================================================================
# GOOGLE SHEETS
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
        sheet.update('A1:L2', [
            ['HARMONICA - Ценови Тракер', '', '', '', '', '', '', '', '', '', '', ''],
            ['Последна актуализация:', now, '', '', 'Курс:', f'{EUR_RATE} лв/EUR', '', '', '', '', '', '']
        ])
        
        # Заглавия
        headers = ['№', 'Продукт', 'Грамаж', 'Реф. BGN', 'Реф. EUR', 
                   'eBag', 'Кашон', 'Ср. BGN', 'Ср. EUR', 'Откл. %', 'Статус']
        sheet.update('A4:K4', [headers])
        
        # Данни
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
        
        sheet.update(f'A5:K{4 + len(rows)}', rows)
        print(f"\n✓ Google Sheets актуализиран")
        
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
        print("Няма продукти с отклонения над прага")
        return
    
    subject = f"🚨 Harmonica: {len(alerts)} продукта с ценови промени над {ALERT_THRESHOLD}%"
    
    body = f"""Здравей,

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
        msg['To'] = recipients
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(gmail_user, gmail_password)
            # Поддръжка на множество получатели
            recipient_list = [r.strip() for r in recipients.split(',')]
            server.send_message(msg, to_addrs=recipient_list)
        
        print(f"\n✓ Имейл изпратен до {recipients}")
        
    except Exception as e:
        print(f"\n✗ Грешка при имейл: {str(e)}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("HARMONICA PRICE TRACKER v2.0")
    print(f"Време: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"Продукти: {len(PRODUCTS)}")
    print(f"Праг за известия: {ALERT_THRESHOLD}%")
    print("=" * 60)
    
    results = collect_prices()
    update_google_sheets(results)
    
    alerts = [r for r in results if r['deviation'] is not None and abs(r['deviation']) > ALERT_THRESHOLD]
    send_email_alert(alerts)
    
    # Обобщение
    print("\n" + "=" * 60)
    print("ОБОБЩЕНИЕ")
    print("=" * 60)
    
    products_with_prices = len([r for r in results if r['avg_price_bgn']])
    products_with_ebag = len([r for r in results if r['ebag_price']])
    products_with_kashon = len([r for r in results if r['kashon_price']])
    
    print(f"Продукти с цени: {products_with_prices}/{len(results)}")
    print(f"  - eBag: {products_with_ebag}")
    print(f"  - Кашон: {products_with_kashon}")
    print(f"Продукти с отклонения: {len(alerts)}")
    
    if alerts:
        print("\nПродукти с внимание:")
        for a in alerts:
            print(f"  • {a['name']}: {a['deviation']:+.1f}%")
    
    print("\n✓ Готово!")


if __name__ == "__main__":
    main()
