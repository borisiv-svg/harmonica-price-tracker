"""
Harmonica Price Tracker v5.3
3 магазина: eBag, Кашон, Balev Bio Market
Поправена Google Sheets интеграция.
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
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print("    [DEBUG] ANTHROPIC_API_KEY не е зададен")
        return None
    try:
        return anthropic.Anthropic(api_key=api_key)
    except Exception as e:
        print(f"    [DEBUG] Грешка при Claude клиент: {str(e)[:50]}")
        return None


def extract_prices_with_claude(page_text, store_name):
    if not CLAUDE_AVAILABLE:
        return {}
    
    client = get_claude_client()
    if not client:
        return {}
    
    products_list = "\n".join([f"- {p['name']} ({p['weight']})" for p in PRODUCTS])
    
    if len(page_text) > 15000:
        page_text = page_text[:15000]
    
    prompt = f"""Анализирай текста от магазин "{store_name}" и намери цените на Harmonica продукти.

ПРОДУКТИ:
{products_list}

ТЕКСТ:
{page_text}

Върни САМО JSON: {{"Био Локум роза": 3.81, "Айран harmonica": 2.90}}
Без markdown, без обяснения. Ако няма нищо: {{}}"""

    try:
        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        
        response_text = message.content[0].text.strip()
        print(f"    [DEBUG] Claude: {response_text[:200]}...")
        
        # Почистване
        cleaned = response_text
        if "```" in cleaned:
            cleaned = re.sub(r'```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```', '', cleaned)
        
        json_match = re.search(r'\{[^{}]*\}', cleaned)
        if json_match:
            cleaned = json_match.group(0)
        
        prices = json.loads(cleaned)
        
        validated = {}
        for name, price in prices.items():
            if isinstance(price, (int, float)) and 0.5 < price < 200:
                validated[name] = float(price)
        
        return validated
        
    except Exception as e:
        print(f"    [DEBUG] Claude error: {str(e)[:80]}")
        return {}


# =============================================================================
# FALLBACK ТЪРСЕНЕ
# =============================================================================

PRODUCT_KEYWORDS = {
    "Био Локум роза": ["локум роза", "локум 140"],
    "Био Обикновени бисквити с краве масло": ["бисквити краве масло", "обикновени бисквити"],
    "Айран harmonica": ["айран 500", "айран"],
    "Био Тунквана вафла без захар": ["вафла без захар 40", "тунквана без захар"],
    "Био Оризови топчета с черен шоколад": ["оризови топчета", "топчета шоколад"],
    "Био лимонада": ["лимонада 330", "лимонада"],
    "Био тънки претцели с морска сол": ["претцели 80", "претцели"],
    "Био тунквана вафла Класика": ["вафла класика", "тунквана класика"],
    "Био вафла без добавена захар": ["вафла 30г", "вафла 30"],
    "Био сироп от липа": ["сироп липа", "липа 750"],
    "Био Пасирани домати": ["пасирани домати", "passata"],
    "Smiles с нахут и морска сол": ["smiles", "нахут сол"],
    "Био Крема сирене": ["крема сирене", "cream cheese"],
    "Козе сирене harmonica": ["козе сирене", "goat cheese"],
}


def extract_prices_with_keywords(page_text):
    prices = {}
    page_lower = page_text.lower()
    
    for product in PRODUCTS:
        name = product['name']
        keywords = PRODUCT_KEYWORDS.get(name, [])
        ref_price = product['ref_price_bgn']
        
        for kw in keywords:
            idx = page_lower.find(kw.lower())
            if idx != -1:
                context = page_text[max(0, idx-100):idx+150]
                matches = re.findall(r'(\d+)[,.](\d{2})\s*(?:лв|€|BGN)?', context)
                for m in matches:
                    try:
                        price = float(f"{m[0]}.{m[1]}")
                        if 0.5 < price < 200 and 0.3 * ref_price < price < 3 * ref_price:
                            prices[name] = price
                            break
                    except:
                        continue
                if name in prices:
                    break
    
    return prices


# =============================================================================
# SCRAPING
# =============================================================================

def scrape_store(page, store_key, store_config):
    prices = {}
    url = store_config['url']
    store_name = store_config['name_in_sheet']
    body_text = ""
    
    print(f"\n{'='*60}")
    print(f"{store_name}: Зареждане")
    print(f"{'='*60}")
    
    try:
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        
        # Бисквитки
        for sel in ['button:has-text("Приемам")', 'button:has-text("Accept")', '.cc-btn']:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(1500)
                    break
            except:
                pass
        
        # Скролване
        for _ in range(7):
            page.evaluate("window.scrollBy(0, 800)")
            page.wait_for_timeout(500)
        
        body_text = page.inner_text('body')
        print(f"  Заредени {len(body_text)} символа")
        
    except Exception as e:
        print(f"  ✗ Грешка при зареждане: {str(e)[:80]}")
        return prices
    
    # Claude AI (с отделен try-catch)
    try:
        print(f"  Claude AI...")
        claude_prices = extract_prices_with_claude(body_text, store_name)
        print(f"    Намерени: {len(claude_prices)}")
        prices.update(claude_prices)
    except Exception as e:
        print(f"  Claude грешка: {str(e)[:50]}")
    
    # Fallback ВИНАГИ се изпълнява
    try:
        print(f"  Fallback...")
        fallback_prices = extract_prices_with_keywords(body_text)
        added = 0
        for name, price in fallback_prices.items():
            if name not in prices:
                prices[name] = price
                added += 1
        print(f"    Добавени: {added}")
    except Exception as e:
        print(f"  Fallback грешка: {str(e)[:50]}")
    
    print(f"  ✓ Общо: {len(prices)} продукта")
    return prices


def collect_prices():
    all_prices = {}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
            locale="bg-BG",
            viewport={"width": 1920, "height": 1080}
        )
        context.route("**/*.{png,jpg,jpeg,gif,webp,svg}", lambda r: r.abort())
        page = context.new_page()
        
        for key, config in STORES.items():
            all_prices[key] = scrape_store(page, key, config)
            page.wait_for_timeout(2000)
        
        browser.close()
    
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
# GOOGLE SHEETS - ПОПРАВЕНО
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
        
        # Подготвяме ВСИЧКИ данни наведнъж
        all_data = []
        
        # Ред 1: Заглавие
        all_data.append(['HARMONICA - Ценови Тракер', '', '', '', '', '', '', '', '', '', '', ''])
        
        # Ред 2: Метаданни
        all_data.append([f'Актуализация: {now}', '', f'Курс: {EUR_RATE}', '', f'Магазини: {", ".join(store_names)}', '', '', '', '', '', '', ''])
        
        # Ред 3: Празен
        all_data.append([''] * 12)
        
        # Ред 4: Заглавия на колони
        headers = ['№', 'Продукт', 'Грамаж', 'Реф.BGN', 'Реф.EUR', 'eBag', 'Кашон', 'Balev', 'Ср.BGN', 'Ср.EUR', 'Откл.%', 'Статус']
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
                r['avg_bgn'] if r['avg_bgn'] else '',
                r['avg_eur'] if r['avg_eur'] else '',
                f"{r['deviation']}%" if r['deviation'] is not None else '',
                r['status']
            ]
            all_data.append(row)
        
        # Записваме всичко наведнъж
        sheet.update(values=all_data, range_name='A1')
        print(f"  ✓ Записани {len(all_data)} реда")
        
        # Форматиране
        try:
            # Заглавие
            sheet.format('A1:L1', {
                'backgroundColor': {'red': 0.2, 'green': 0.5, 'blue': 0.3},
                'textFormat': {'bold': True, 'fontSize': 14, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}}
            })
            sheet.merge_cells('A1:L1')
            
            # Метаданни
            sheet.format('A2:L2', {
                'backgroundColor': {'red': 0.9, 'green': 0.95, 'blue': 0.9},
                'textFormat': {'italic': True}
            })
            
            # Заглавия колони
            sheet.format('A4:L4', {
                'backgroundColor': {'red': 0.3, 'green': 0.6, 'blue': 0.4},
                'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
                'horizontalAlignment': 'CENTER'
            })
            
            # Статус колона - цветово кодиране
            for i, r in enumerate(results, 5):
                cell = f'L{i}'
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
        except Exception as e:
            print(f"  Предупреждение за форматиране: {str(e)[:50]}")
        
        # История
        try:
            try:
                hist = spreadsheet.worksheet("История")
            except:
                hist = spreadsheet.add_worksheet("История", rows=2000, cols=12)
                hist.update(values=[['Дата', 'Час', 'Продукт', 'Грамаж', 'eBag', 'Кашон', 'Balev', 'Средна', 'Откл.%', 'Статус']], range_name='A1')
                hist.freeze(rows=1)
            
            date_str = datetime.now().strftime("%d.%m.%Y")
            time_str = datetime.now().strftime("%H:%M")
            
            hist_rows = []
            for r in results:
                hist_rows.append([
                    date_str,
                    time_str,
                    r['name'],
                    r['weight'],
                    r['prices'].get('eBag', '') or '',
                    r['prices'].get('Kashon', '') or '',
                    r['prices'].get('Balev', '') or '',
                    r['avg_bgn'] if r['avg_bgn'] else '',
                    f"{r['deviation']}%" if r['deviation'] is not None else '',
                    r['status']
                ])
            
            hist.append_rows(hist_rows, value_input_option='USER_ENTERED')
            print(f"  ✓ История: {len(hist_rows)} записа")
        except Exception as e:
            print(f"  Грешка при история: {str(e)[:50]}")
        
        print("\n✓ Google Sheets актуализиран")
        
    except Exception as e:
        print(f"\n✗ Грешка: {str(e)}")


# =============================================================================
# ИМЕЙЛ
# =============================================================================

def send_email_alert(alerts):
    gmail_user = os.environ.get('GMAIL_USER')
    gmail_pass = os.environ.get('GMAIL_APP_PASSWORD')
    recipients = os.environ.get('ALERT_EMAIL', gmail_user)
    
    if not gmail_user or not gmail_pass or not alerts:
        if not alerts:
            print("Няма отклонения - имейл не е изпратен")
        return
    
    subject = f"🚨 Harmonica: {len(alerts)} продукта с промени над {ALERT_THRESHOLD}%"
    
    body = f"Открити са {len(alerts)} продукта с отклонения над {ALERT_THRESHOLD}%:\n\n"
    for a in alerts:
        body += f"📦 {a['name']} ({a['weight']})\n"
        body += f"   Референтна: {a['ref_bgn']:.2f} лв\n"
        body += f"   Средна: {a['avg_bgn']:.2f} лв\n"
        body += f"   Отклонение: {a['deviation']:+.1f}%\n\n"
    
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
        
        print(f"✓ Имейл изпратен")
    except Exception as e:
        print(f"✗ Имейл грешка: {str(e)[:50]}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("HARMONICA PRICE TRACKER v5.3")
    print(f"Време: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"Магазини: {len(STORES)}")
    print(f"Claude: {'✓' if CLAUDE_AVAILABLE else '✗'}")
    print("=" * 60)
    
    results = collect_prices()
    update_google_sheets(results)
    
    alerts = [r for r in results if r['deviation'] and abs(r['deviation']) > ALERT_THRESHOLD]
    send_email_alert(alerts)
    
    print(f"\n{'='*60}")
    print("ОБОБЩЕНИЕ")
    print(f"{'='*60}")
    for k, cfg in STORES.items():
        cnt = len([r for r in results if r['prices'].get(k)])
        print(f"  {cfg['name_in_sheet']}: {cnt}/{len(results)}")
    
    total = len([r for r in results if any(r['prices'].values())])
    print(f"\nОбщо: {total}/{len(results)} продукта")
    print(f"Отклонения: {len(alerts)}")
    print("\n✓ Готово!")


if __name__ == "__main__":
    main()
