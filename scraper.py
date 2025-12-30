"""
Harmonica Price Tracker v5.4
3 магазина: eBag, Кашон, Balev Bio Market
Оптимизиран Claude prompt с референтни цени.
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

# Продукти с референтни цени от Кашон (използват се за калибрация)
PRODUCTS = [
    {"name": "Био Локум роза", "weight": "140г", "ref_price_bgn": 3.81, "ref_price_eur": 1.95,
     "aliases": ["локум роза", "turkish delight rose", "локум с роза", "rose lokum"]},
    
    {"name": "Био Обикновени бисквити с краве масло", "weight": "150г", "ref_price_bgn": 4.18, "ref_price_eur": 2.14,
     "aliases": ["бисквити краве масло", "butter biscuits", "обикновени бисквити", "бисквити с масло"]},
    
    {"name": "Айран harmonica", "weight": "500мл", "ref_price_bgn": 2.90, "ref_price_eur": 1.48,
     "aliases": ["айран 500", "ayran", "айран хармоника"]},
    
    {"name": "Био Тунквана вафла без захар", "weight": "40г", "ref_price_bgn": 2.62, "ref_price_eur": 1.34,
     "aliases": ["тунквана вафла без захар", "вафла без захар 40", "wafer no sugar", "вафла тунквана без захар"]},
    
    {"name": "Био Оризови топчета с черен шоколад", "weight": "50г", "ref_price_bgn": 4.99, "ref_price_eur": 2.55,
     "aliases": ["оризови топчета шоколад", "rice balls chocolate", "оризови топчета", "топчета черен шоколад"]},
    
    {"name": "Био лимонада", "weight": "330мл", "ref_price_bgn": 3.48, "ref_price_eur": 1.78,
     "aliases": ["лимонада 330", "lemonade", "био лимонада harmonica", "газирана лимонада"]},
    
    {"name": "Био тънки претцели с морска сол", "weight": "80г", "ref_price_bgn": 2.50, "ref_price_eur": 1.28,
     "aliases": ["претцели морска сол", "thin pretzels", "претцели 80", "тънки претцели"]},
    
    {"name": "Био тунквана вафла Класика", "weight": "40г", "ref_price_bgn": 2.00, "ref_price_eur": 1.02,
     "aliases": ["тунквана вафла класика", "classic wafer", "вафла класика 40", "вафла класик"]},
    
    {"name": "Био вафла без добавена захар", "weight": "30г", "ref_price_bgn": 1.44, "ref_price_eur": 0.74,
     "aliases": ["вафла 30г без захар", "crispy wafer 30", "хрупкава вафла", "вафла без захар 30"]},
    
    {"name": "Био сироп от липа", "weight": "750мл", "ref_price_bgn": 14.29, "ref_price_eur": 7.31,
     "aliases": ["сироп липа", "linden syrup", "липов сироп", "сироп от липа 750"]},
    
    {"name": "Био Пасирани домати", "weight": "680г", "ref_price_bgn": 5.90, "ref_price_eur": 3.02,
     "aliases": ["пасирани домати", "passata", "домати пасирани", "томатно пюре"]},
    
    {"name": "Smiles с нахут и морска сол", "weight": "50г", "ref_price_bgn": 2.81, "ref_price_eur": 1.44,
     "aliases": ["smiles нахут", "smiles chickpea", "смайлс нахут", "smiles 50"]},
    
    {"name": "Био Крема сирене", "weight": "125г", "ref_price_bgn": 5.46, "ref_price_eur": 2.79,
     "aliases": ["крема сирене 125", "cream cheese", "кремообразно сирене", "крема сирене harmonica"]},
    
    {"name": "Козе сирене harmonica", "weight": "200г", "ref_price_bgn": 10.70, "ref_price_eur": 5.47,
     "aliases": ["козе сирене 200", "goat cheese", "козе сирене", "сирене от козе мляко"]},
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
    """
    Използва Claude AI за интелигентно извличане на цени.
    Подобрен prompt с референтни цени за по-точно съпоставяне.
    """
    if not CLAUDE_AVAILABLE:
        return {}
    
    client = get_claude_client()
    if not client:
        return {}
    
    # Създаваме детайлен списък с продукти, включително референтни цени и aliases
    products_details = []
    for p in PRODUCTS:
        aliases_str = ", ".join(p.get('aliases', [])[:3])
        products_details.append(
            f"- {p['name']} ({p['weight']}) - очаквана цена ~{p['ref_price_bgn']:.2f} лв | aliases: {aliases_str}"
        )
    products_list = "\n".join(products_details)
    
    # Ограничаваме текста до 12000 символа за по-бърза обработка
    if len(page_text) > 12000:
        page_text = page_text[:12000]
    
    prompt = f"""Ти си експерт по извличане на цени от български онлайн магазини. Анализирай текста от магазин "{store_name}" и намери цените на продуктите от марката Harmonica.

ВАЖНО: Грамажът/обемът ТРЯБВА да съвпада! Не бъркай продукти с различен грамаж.

ПРОДУКТИ ЗА ТЪРСЕНЕ (с очаквани цени от Кашон като ориентир):
{products_list}

ТЕКСТ ОТ СТРАНИЦАТА:
{page_text}

ИНСТРУКЦИИ:
1. Търси ТОЧНО тези продукти по име, грамаж или aliases
2. Грамажът е критичен - "вафла 40г" НЕ Е същото като "вафла 30г"
3. Цената трябва да е близка до очакваната (±50%), освен ако няма промоция
4. Игнорирай продукти, които не са в списъка
5. Ако не си сигурен, по-добре пропусни продукта

ФОРМАТ: Върни САМО валиден JSON обект. Без markdown, без обяснения, без ```
Пример: {{"Био Локум роза": 3.81, "Айран harmonica": 2.90}}
Ако не намериш нищо: {{}}"""

    try:
        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        
        response_text = message.content[0].text.strip()
        print(f"    [DEBUG] Claude отговор: {response_text[:250]}...")
        
        # Почистване на отговора
        cleaned = response_text
        
        # Премахваме markdown форматиране ако има
        if "```" in cleaned:
            cleaned = re.sub(r'```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```', '', cleaned)
        
        # Търсим JSON обект (може да е вложен)
        # Първо опитваме целия текст
        try:
            prices = json.loads(cleaned)
        except:
            # Ако не успее, търсим JSON pattern
            json_match = re.search(r'\{[^{}]*\}', cleaned)
            if json_match:
                cleaned = json_match.group(0)
                prices = json.loads(cleaned)
            else:
                print(f"    [DEBUG] Не може да се парсне JSON")
                return {}
        
        # Валидираме цените
        validated = {}
        for product_name, price in prices.items():
            if not isinstance(price, (int, float)):
                continue
            if price < 0.5 or price > 200:
                continue
            
            # Намираме референтната цена за този продукт
            ref_price = None
            for p in PRODUCTS:
                if p['name'] == product_name:
                    ref_price = p['ref_price_bgn']
                    break
            
            # Валидираме срещу референтната цена (±100% толеранс)
            if ref_price:
                if 0.5 * ref_price <= price <= 2.0 * ref_price:
                    validated[product_name] = float(price)
                else:
                    print(f"    [DEBUG] Отхвърлена цена за {product_name}: {price} (реф: {ref_price})")
            else:
                # Ако няма референтна цена, приемаме го с по-строга проверка
                validated[product_name] = float(price)
        
        print(f"    [DEBUG] Валидирани: {len(validated)} продукта")
        return validated
        
    except json.JSONDecodeError as e:
        print(f"    [DEBUG] JSON грешка: {str(e)[:50]}")
        return {}
    except Exception as e:
        print(f"    [DEBUG] Claude грешка: {str(e)[:80]}")
        return {}


# =============================================================================
# FALLBACK ТЪРСЕНЕ - ПО-СТРИКТНО
# =============================================================================

def extract_prices_with_keywords(page_text):
    """
    Fallback метод с по-стриктно съпоставяне.
    Изисква съвпадение на грамаж/обем.
    """
    prices = {}
    page_lower = page_text.lower()
    
    for product in PRODUCTS:
        name = product['name']
        weight = product['weight'].lower()
        ref_price = product['ref_price_bgn']
        aliases = product.get('aliases', [])
        
        # Търсим по aliases
        for alias in aliases:
            alias_lower = alias.lower()
            idx = page_lower.find(alias_lower)
            
            if idx == -1:
                continue
            
            # Взимаме контекст около намереното
            start = max(0, idx - 80)
            end = min(len(page_text), idx + len(alias) + 120)
            context = page_text[start:end]
            context_lower = context.lower()
            
            # КРИТИЧНО: Проверяваме дали грамажът е в контекста
            weight_number = re.search(r'(\d+)', weight)
            if weight_number:
                weight_num = weight_number.group(1)
                if weight_num not in context:
                    continue  # Грамажът не съвпада, пропускаме
            
            # Търсим цена в контекста
            price_patterns = [
                r'(\d+)[,.](\d{2})\s*(?:лв|лева|BGN)',
                r'(\d+)[,.](\d{2})\s*(?:€|EUR)',
                r'(?:цена|price)[:\s]*(\d+)[,.](\d{2})',
                r'>(\d+)[,.](\d{2})<',
                r'(\d+)[,.](\d{2})',
            ]
            
            for pattern in price_patterns:
                matches = re.findall(pattern, context, re.IGNORECASE)
                for m in matches:
                    try:
                        price = float(f"{m[0]}.{m[1]}")
                        # Проверяваме дали цената е в разумни граници (±70% от референтната)
                        if 0.3 * ref_price <= price <= 1.7 * ref_price:
                            prices[name] = price
                            break
                    except:
                        continue
                
                if name in prices:
                    break
            
            if name in prices:
                break
    
    return prices


# =============================================================================
# SCRAPING
# =============================================================================

def scrape_store(page, store_key, store_config):
    """Извлича цени от един магазин."""
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
        
        # Приемане на бисквитки
        cookie_selectors = [
            'button:has-text("Приемам")',
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
        
        # Скролване за lazy loading
        print(f"  Скролване...")
        for _ in range(8):
            page.evaluate("window.scrollBy(0, 700)")
            page.wait_for_timeout(400)
        
        # Връщане в началото
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(500)
        
        body_text = page.inner_text('body')
        print(f"  Заредени {len(body_text)} символа")
        
    except Exception as e:
        print(f"  ✗ Грешка при зареждане: {str(e)[:80]}")
        return prices
    
    # Claude AI извличане
    try:
        print(f"  Claude AI анализ...")
        claude_prices = extract_prices_with_claude(body_text, store_name)
        print(f"    Claude намери: {len(claude_prices)} продукта")
        if claude_prices:
            print(f"    Продукти: {list(claude_prices.keys())[:5]}")
        prices.update(claude_prices)
    except Exception as e:
        print(f"  Claude грешка: {str(e)[:50]}")
    
    # Fallback с ключови думи (само за липсващи продукти)
    try:
        print(f"  Fallback търсене...")
        fallback_prices = extract_prices_with_keywords(body_text)
        added = 0
        for name, price in fallback_prices.items():
            if name not in prices:
                prices[name] = price
                added += 1
        print(f"    Fallback добави: {added} продукта")
    except Exception as e:
        print(f"  Fallback грешка: {str(e)[:50]}")
    
    print(f"  ✓ Общо намерени: {len(prices)} продукта")
    return prices


def collect_prices():
    """Събира цени от всички магазини."""
    all_prices = {}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            locale="bg-BG",
            viewport={"width": 1920, "height": 1080}
        )
        
        # Блокираме изображения за по-бързо зареждане
        context.route("**/*.{png,jpg,jpeg,gif,webp,svg}", lambda r: r.abort())
        
        page = context.new_page()
        
        for key, config in STORES.items():
            all_prices[key] = scrape_store(page, key, config)
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
        all_data.append(['HARMONICA - Ценови Тракер v5.4', '', '', '', '', '', '', '', '', '', '', ''])
        
        # Ред 2: Метаданни
        all_data.append([f'Актуализация: {now}', '', f'Курс: {EUR_RATE}', '', f'Магазини: {", ".join(store_names)}', '', '', '', '', '', '', ''])
        
        # Ред 3: Празен
        all_data.append([''] * 12)
        
        # Ред 4: Заглавия
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
        
        # Записваме
        sheet.update(values=all_data, range_name='A1')
        print(f"  ✓ Записани {len(all_data)} реда")
        
        # Форматиране
        try:
            sheet.format('A1:L1', {
                'backgroundColor': {'red': 0.2, 'green': 0.5, 'blue': 0.3},
                'textFormat': {'bold': True, 'fontSize': 14, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}}
            })
            sheet.merge_cells('A1:L1')
            
            sheet.format('A2:L2', {
                'backgroundColor': {'red': 0.9, 'green': 0.95, 'blue': 0.9},
                'textFormat': {'italic': True}
            })
            
            sheet.format('A4:L4', {
                'backgroundColor': {'red': 0.3, 'green': 0.6, 'blue': 0.4},
                'textFormat': {'bold': True, 'foregroundColor': {'red': 1, 'green': 1, 'blue': 1}},
                'horizontalAlignment': 'CENTER'
            })
            
            # Цветово кодиране на статус
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
            print(f"  Форматиране предупреждение: {str(e)[:50]}")
        
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
                    date_str, time_str, r['name'], r['weight'],
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
    
    if not gmail_user or not gmail_pass:
        print("Gmail credentials не са зададени")
        return
    
    if not alerts:
        print("Няма отклонения над прага - имейл не е изпратен")
        return
    
    subject = f"🚨 Harmonica: {len(alerts)} продукта с ценови промени над {ALERT_THRESHOLD}%"
    
    body = f"""Здравей,

Открити са {len(alerts)} продукта с ценови отклонения над {ALERT_THRESHOLD}%:

"""
    for a in alerts:
        body += f"📦 {a['name']} ({a['weight']})\n"
        body += f"   Референтна: {a['ref_bgn']:.2f} лв\n"
        body += f"   Средна: {a['avg_bgn']:.2f} лв\n"
        body += f"   Отклонение: {a['deviation']:+.1f}%\n"
        body += f"   eBag: {a['prices'].get('eBag') or 'N/A'} | Кашон: {a['prices'].get('Kashon') or 'N/A'} | Balev: {a['prices'].get('Balev') or 'N/A'}\n\n"
    
    body += "\nПроверете Google Sheets за пълния отчет.\n\nПоздрави,\nHarmonica Price Tracker v5.4"
    
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
        
        print(f"✓ Имейл изпратен до {recipients}")
    except Exception as e:
        print(f"✗ Имейл грешка: {str(e)[:50]}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("HARMONICA PRICE TRACKER v5.4")
    print(f"Време: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"Продукти: {len(PRODUCTS)}")
    print(f"Магазини: {len(STORES)}")
    print(f"Claude API: {'✓ Наличен' if CLAUDE_AVAILABLE else '✗ Не е наличен'}")
    print("=" * 60)
    
    results = collect_prices()
    update_google_sheets(results)
    
    alerts = [r for r in results if r['deviation'] and abs(r['deviation']) > ALERT_THRESHOLD]
    send_email_alert(alerts)
    
    # Обобщение
    print(f"\n{'='*60}")
    print("ОБОБЩЕНИЕ")
    print(f"{'='*60}")
    
    for k, cfg in STORES.items():
        cnt = len([r for r in results if r['prices'].get(k)])
        print(f"  {cfg['name_in_sheet']}: {cnt}/{len(results)} продукта")
    
    total = len([r for r in results if any(r['prices'].values())])
    ok_count = len([r for r in results if r['status'] == 'OK'])
    warning_count = len([r for r in results if r['status'] == 'ВНИМАНИЕ'])
    no_data = len([r for r in results if r['status'] == 'НЯМА ДАННИ'])
    
    print(f"\nОбщо покритие: {total}/{len(results)} продукта")
    print(f"Статус: {ok_count} OK, {warning_count} ВНИМАНИЕ, {no_data} НЯМА ДАННИ")
    print("\n✓ Готово!")


if __name__ == "__main__":
    main()
