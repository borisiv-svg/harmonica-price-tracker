"""
Harmonica Price Tracker v2.1 - DEBUG VERSION
Добавена debug информация за диагностика.
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
DEBUG = True  # Включва подробни debug съобщения

PRODUCTS = [
    {
        "name": "Био Локум роза",
        "weight": "140г",
        "ref_price_bgn": 3.81,
        "ref_price_eur": 1.95,
        "ebag_search": "harmonica локум",
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
        "name": "Био сироп от липа",
        "weight": "750мл",
        "ref_price_bgn": 14.29,
        "ref_price_eur": 7.31,
        "ebag_search": "harmonica сироп",
        "kashon_url": "https://kashonharmonica.bg/bg/products/cordials"
    },
]


def extract_price_from_text(text):
    """Извлича цена от текст."""
    if not text:
        return None
    
    text = ' '.join(text.split())
    
    patterns = [
        r'(\d+)[,.](\d{2})\s*(?:лв|лева|BGN|bgn)',
        r'(\d+)[,.](\d{2})\s*(?:€|EUR|eur)',
        r'BGN\s*(\d+)[,.](\d{2})',
        r'(\d+)[,.](\d{2})\s*(?:лв\.)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                price = float(f"{match.group(1)}.{match.group(2)}")
                if 0.5 < price < 200:
                    return price
            except:
                continue
    
    return None


def scrape_ebag_debug(page, product):
    """Debug версия за eBag - показва какво вижда скриптът."""
    try:
        search_query = product['ebag_search']
        search_url = f"https://www.ebag.bg/search?q={search_query.replace(' ', '%20')}"
        
        print(f"\n  eBag DEBUG:")
        print(f"    URL: {search_url}")
        
        page.goto(search_url, timeout=30000)
        page.wait_for_timeout(5000)  # Повече време за зареждане
        
        # Проверяваме URL след зареждане (дали има redirect)
        current_url = page.url
        print(f"    Текущ URL след зареждане: {current_url}")
        
        # Вземаме заглавието на страницата
        title = page.title()
        print(f"    Заглавие на страницата: {title}")
        
        # Търсим конкретни селектори за продукти в eBag
        selectors_to_try = [
            'div.product-box',
            'div.product-item',
            'div.product-card',
            'article.product',
            '[data-product-id]',
            '.products-grid .item',
            '.search-results .product',
            '.listing-product',
        ]
        
        for selector in selectors_to_try:
            elements = page.query_selector_all(selector)
            if elements and len(elements) < 100:  # Разумен брой
                print(f"    Селектор '{selector}': {len(elements)} елемента")
                if elements and len(elements) > 0:
                    # Показваме текста на първите 2 елемента
                    for i, el in enumerate(elements[:2]):
                        text = el.inner_text()[:200].replace('\n', ' ')
                        print(f"      Елемент {i+1}: {text}...")
                        
                        # Опитваме да извлечем цена
                        price = extract_price_from_text(el.inner_text())
                        if price:
                            print(f"      >>> Намерена цена: {price} лв")
                            return price
        
        # Ако нищо не сработи, показваме част от HTML
        print(f"\n    Търсим цени в целия текст на страницата...")
        body_text = page.inner_text('body')
        
        # Показваме първите 500 символа
        print(f"    Първи 500 символа от body:")
        print(f"    {body_text[:500].replace(chr(10), ' ')}...")
        
        # Търсим всички цени в текста
        all_prices = re.findall(r'(\d+)[,.](\d{2})\s*лв', body_text)
        if all_prices:
            print(f"\n    Всички намерени цени: {all_prices[:10]}")
            # Вземаме първата разумна цена
            for p in all_prices:
                price = float(f"{p[0]}.{p[1]}")
                if 1 < price < 100:
                    print(f"    >>> Използваме цена: {price} лв")
                    return price
        
        print(f"    Цена не е намерена")
        return None
        
    except Exception as e:
        print(f"    ГРЕШКА: {str(e)}")
        return None


def scrape_kashon_debug(page, product):
    """Debug версия за Кашон - показва какво вижда скриптът."""
    try:
        url = product.get('kashon_url')
        
        print(f"\n  Кашон DEBUG:")
        print(f"    URL: {url}")
        
        page.goto(url, timeout=30000)
        page.wait_for_timeout(5000)
        
        # Проверяваме заглавието
        title = page.title()
        print(f"    Заглавие: {title}")
        
        # Търсим различни селектори
        selectors_to_try = [
            '.views-row',
            '.product-item',
            '.node--type-product',
            'article',
            '.field--name-title',
            '.product',
            'div.views-col',
        ]
        
        for selector in selectors_to_try:
            elements = page.query_selector_all(selector)
            if elements and 0 < len(elements) < 50:
                print(f"    Селектор '{selector}': {len(elements)} елемента")
                
                # Показваме текста на всички елементи (ако са малко)
                for i, el in enumerate(elements[:5]):
                    text = el.inner_text().replace('\n', ' ').strip()
                    print(f"      [{i+1}] {text[:150]}...")
                    
                    # Търсим цена
                    price = extract_price_from_text(text)
                    if price:
                        print(f"          >>> Цена: {price} лв")
        
        # Търсим директно за цени на страницата
        print(f"\n    Търсим цени в целия текст...")
        body_text = page.inner_text('body')
        
        all_prices = re.findall(r'(\d+)[,.](\d{2})\s*лв', body_text)
        if all_prices:
            print(f"    Намерени цени: {all_prices[:15]}")
        
        # Търсим продукта по име
        product_name_lower = product['name'].lower()
        keywords = ['локум', 'айран', 'сироп', 'липа', 'роза']
        
        for kw in keywords:
            if kw in product_name_lower and kw in body_text.lower():
                print(f"    Ключова дума '{kw}' намерена в страницата!")
                
                # Опитваме да намерим цена около тази дума
                idx = body_text.lower().find(kw)
                context = body_text[max(0, idx-50):idx+100]
                print(f"    Контекст: ...{context}...")
                
                price = extract_price_from_text(context)
                if price:
                    print(f"    >>> Намерена цена от контекст: {price} лв")
                    return price
        
        return None
        
    except Exception as e:
        print(f"    ГРЕШКА: {str(e)}")
        return None


def collect_prices_debug():
    """Debug версия - събира цени с подробна информация."""
    results = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="bg-BG",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()
        
        for product in PRODUCTS:
            print(f"\n{'='*70}")
            print(f"ПРОДУКТ: {product['name']} ({product['weight']})")
            print(f"{'='*70}")
            
            ebag_price = scrape_ebag_debug(page, product)
            page.wait_for_timeout(2000)
            
            kashon_price = scrape_kashon_debug(page, product)
            page.wait_for_timeout(2000)
            
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
        
        sheet.clear()
        
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        sheet.update(range_name='A1:L2', values=[
            ['HARMONICA - Ценови Тракер (DEBUG)', '', '', '', '', '', '', '', '', '', '', ''],
            ['Последна актуализация:', now, '', '', 'Курс:', f'{EUR_RATE} лв/EUR', '', '', '', '', '', '']
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
        print(f"\n✓ Google Sheets актуализиран")
        
    except Exception as e:
        print(f"\n✗ Грешка при Google Sheets: {str(e)}")


def main():
    print("=" * 70)
    print("HARMONICA PRICE TRACKER v2.1 - DEBUG MODE")
    print(f"Време: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"Тестови продукти: {len(PRODUCTS)}")
    print("=" * 70)
    
    results = collect_prices_debug()
    update_google_sheets(results)
    
    print("\n" + "=" * 70)
    print("DEBUG РЕЗУЛТАТИ")
    print("=" * 70)
    
    for r in results:
        print(f"\n{r['name']}:")
        print(f"  eBag: {r['ebag_price'] or 'None'}")
        print(f"  Кашон: {r['kashon_price'] or 'None'}")
        print(f"  Статус: {r['status']}")
    
    print("\n✓ Debug завърши!")


if __name__ == "__main__":
    main()
