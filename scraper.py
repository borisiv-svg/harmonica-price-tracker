"""
Harmonica Price Tracker v5.5
3 магазина: eBag, Кашон, Balev Bio Market
Двуфазен Claude анализ за максимална точност.
Подобрено скролиране за pagination/infinite scroll.
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
        "name_in_sheet": "eBag",
        "scroll_times": 12  # Повече скролиране за infinite scroll
    },
    "Kashon": {
        "url": "https://kashonharmonica.bg/bg/products/field_producer/harmonica-144",
        "name_in_sheet": "Кашон",
        "scroll_times": 10
    },
    "Balev": {
        "url": "https://balevbiomarket.com/brands/harmonica",
        "name_in_sheet": "Balev",
        "scroll_times": 8
    }
}

# Продукти с референтни цени от Кашон и номера за двуфазен анализ
PRODUCTS = [
    {"id": 1, "name": "Био Локум роза", "weight": "140г", "ref_price_bgn": 3.81, "ref_price_eur": 1.95},
    {"id": 2, "name": "Био Обикновени бисквити с краве масло", "weight": "150г", "ref_price_bgn": 4.18, "ref_price_eur": 2.14},
    {"id": 3, "name": "Айран harmonica", "weight": "500мл", "ref_price_bgn": 2.90, "ref_price_eur": 1.48},
    {"id": 4, "name": "Био Тунквана вафла без захар", "weight": "40г", "ref_price_bgn": 2.62, "ref_price_eur": 1.34},
    {"id": 5, "name": "Био Оризови топчета с черен шоколад", "weight": "50г", "ref_price_bgn": 4.99, "ref_price_eur": 2.55},
    {"id": 6, "name": "Био лимонада", "weight": "330мл", "ref_price_bgn": 3.48, "ref_price_eur": 1.78},
    {"id": 7, "name": "Био тънки претцели с морска сол", "weight": "80г", "ref_price_bgn": 2.50, "ref_price_eur": 1.28},
    {"id": 8, "name": "Био тунквана вафла Класика", "weight": "40г", "ref_price_bgn": 2.00, "ref_price_eur": 1.02},
    {"id": 9, "name": "Био вафла без добавена захар", "weight": "30г", "ref_price_bgn": 1.44, "ref_price_eur": 0.74},
    {"id": 10, "name": "Био сироп от липа", "weight": "750мл", "ref_price_bgn": 14.29, "ref_price_eur": 7.31},
    {"id": 11, "name": "Био Пасирани домати", "weight": "680г", "ref_price_bgn": 5.90, "ref_price_eur": 3.02},
    {"id": 12, "name": "Smiles с нахут и морска сол", "weight": "50г", "ref_price_bgn": 2.81, "ref_price_eur": 1.44},
    {"id": 13, "name": "Био Крема сирене", "weight": "125г", "ref_price_bgn": 5.46, "ref_price_eur": 2.79},
    {"id": 14, "name": "Козе сирене harmonica", "weight": "200г", "ref_price_bgn": 10.70, "ref_price_eur": 5.47},
]


# =============================================================================
# CLAUDE API - ДВУФАЗЕН АНАЛИЗ
# =============================================================================

def get_claude_client():
    """Създава Claude API клиент."""
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print("    [CLAUDE] API ключ не е зададен")
        return None
    try:
        return anthropic.Anthropic(api_key=api_key)
    except Exception as e:
        print(f"    [CLAUDE] Грешка при създаване на клиент: {str(e)[:50]}")
        return None


def phase1_extract_all_products(client, page_text, store_name):
    """
    ФАЗА 1: Груба екстракция
    Намира ВСИЧКИ продукти на Harmonica от текста, без да се опитва да ги съпостави.
    Връща списък с продукти точно както са изписани в сайта.
    """
    
    # Ограничаваме текста
    if len(page_text) > 14000:
        page_text = page_text[:14000]
    
    prompt = f"""Анализирай текста от българския онлайн магазин "{store_name}" и извлечи ВСИЧКИ продукти на марката Harmonica (Хармоника) с техните цени.

ТЕКСТ ОТ СТРАНИЦАТА:
{page_text}

ИНСТРУКЦИИ:
1. Намери всички продукти, които са от марка Harmonica/Хармоника
2. За всеки продукт извлечи ТОЧНОТО име както е написано в сайта
3. Извлечи цената в лева (BGN)
4. Включи грамажа/обема ако е посочен
5. НЕ филтрирай и НЕ променяй имената - запиши ги точно както са в сайта

ФОРМАТ НА ОТГОВОРА:
Върни САМО валиден JSON масив. Без markdown, без обяснения.
Пример:
[
  {{"name": "Хармоника Био Айран 500мл", "price": 2.99}},
  {{"name": "Тунквана вафла класик 40г", "price": 2.19}}
]

Ако не намериш продукти на Harmonica: []"""

    try:
        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        response_text = message.content[0].text.strip()
        print(f"    [ФАЗА 1] Отговор: {response_text[:200]}...")
        
        # Почистване
        cleaned = response_text
        if "```" in cleaned:
            cleaned = re.sub(r'```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```', '', cleaned)
        
        # Търсим JSON масив
        array_match = re.search(r'\[[\s\S]*\]', cleaned)
        if array_match:
            cleaned = array_match.group(0)
        
        products = json.loads(cleaned)
        
        # Валидираме структурата
        valid_products = []
        for p in products:
            if isinstance(p, dict) and 'name' in p and 'price' in p:
                try:
                    price = float(p['price'])
                    if 0.5 < price < 200:
                        valid_products.append({
                            "name": str(p['name']),
                            "price": price
                        })
                except:
                    pass
        
        print(f"    [ФАЗА 1] Намерени: {len(valid_products)} продукта")
        return valid_products
        
    except Exception as e:
        print(f"    [ФАЗА 1] Грешка: {str(e)[:80]}")
        return []


def phase2_match_products(client, extracted_products, store_name):
    """
    ФАЗА 2: Интелигентно съпоставяне
    Съпоставя намерените продукти от Фаза 1 с нашия списък.
    Използва номера на продуктите за еднозначна идентификация.
    """
    
    if not extracted_products:
        print(f"    [ФАЗА 2] Няма продукти за съпоставяне")
        return {}
    
    # Подготвяме списъка с нашите продукти
    our_products_text = "\n".join([
        f"{p['id']}. {p['name']} ({p['weight']}) - реф. цена: {p['ref_price_bgn']:.2f} лв"
        for p in PRODUCTS
    ])
    
    # Подготвяме списъка с намерените продукти
    found_products_text = "\n".join([
        f"- \"{p['name']}\" → {p['price']:.2f} лв"
        for p in extracted_products
    ])
    
    prompt = f"""Съпостави продуктите, намерени в магазин "{store_name}", с нашия списък от 14 продукта.

НАШИЯТ СПИСЪК (с номера):
{our_products_text}

ПРОДУКТИ ОТ САЙТА:
{found_products_text}

ИНСТРУКЦИИ ЗА СЪПОСТАВЯНЕ:
1. Сравни имената - те може да са изписани по различен начин (с/без "Био", на английски, съкратено)
2. ГРАМАЖЪТ/ОБЕМЪТ Е КРИТИЧЕН - "вафла 40г" НЕ Е същото като "вафла 30г"
3. Ако продукт от сайта НЕ съвпада с нищо от нашия списък - пропусни го
4. Ако не си сигурен - по-добре пропусни, отколкото да сбъркаш
5. Провери дали цената е разумна спрямо референтната (±50%)

ПРИМЕРИ ЗА СЪВПАДЕНИЯ:
- "Хармоника Био Айран 500мл" → съвпада с #3 "Айран harmonica (500мл)"
- "Тунквана вафла класик 40г" → съвпада с #8 "Био тунквана вафла Класика (40г)"
- "Вафла без захар 40г" → съвпада с #4 "Био Тунквана вафла без захар (40г)"
- "Вафла 30г" → съвпада с #9 "Био вафла без добавена захар (30г)" (ВНИМАНИЕ: различен грамаж от 40г!)
- "Локум роза" → съвпада с #1 "Био Локум роза (140г)"
- "Оризови топчета шоколад 50г" → съвпада с #5

ФОРМАТ НА ОТГОВОРА:
Върни САМО JSON обект с номера като ключове (string) и цени като стойности.
Пример: {{"3": 2.99, "8": 2.19, "1": 3.81}}

Ако нищо не съвпада: {{}}"""

    try:
        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        response_text = message.content[0].text.strip()
        print(f"    [ФАЗА 2] Отговор: {response_text[:150]}...")
        
        # Почистване
        cleaned = response_text
        if "```" in cleaned:
            cleaned = re.sub(r'```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```', '', cleaned)
        
        # Търсим JSON обект
        obj_match = re.search(r'\{[^{}]*\}', cleaned)
        if obj_match:
            cleaned = obj_match.group(0)
        
        matches = json.loads(cleaned)
        
        # Конвертираме номера към имена на продукти
        result = {}
        for product_id_str, price in matches.items():
            try:
                product_id = int(product_id_str)
                price = float(price)
                
                # Намираме продукта по ID
                product = next((p for p in PRODUCTS if p['id'] == product_id), None)
                if product:
                    # Валидираме цената (±80% от референтната)
                    ref_price = product['ref_price_bgn']
                    if 0.2 * ref_price <= price <= 1.8 * ref_price:
                        result[product['name']] = price
                    else:
                        print(f"    [ФАЗА 2] Отхвърлена цена за #{product_id}: {price} (реф: {ref_price})")
            except (ValueError, TypeError):
                continue
        
        print(f"    [ФАЗА 2] Съпоставени: {len(result)} продукта")
        return result
        
    except Exception as e:
        print(f"    [ФАЗА 2] Грешка: {str(e)[:80]}")
        return {}


def extract_prices_with_claude_two_phase(page_text, store_name):
    """
    Главна функция за двуфазно извличане на цени с Claude.
    Фаза 1: Груба екстракция на всички Harmonica продукти
    Фаза 2: Интелигентно съпоставяне с нашия списък
    """
    if not CLAUDE_AVAILABLE:
        return {}
    
    client = get_claude_client()
    if not client:
        return {}
    
    print(f"    [CLAUDE] Стартиране на двуфазен анализ...")
    
    # Фаза 1: Груба екстракция
    extracted = phase1_extract_all_products(client, page_text, store_name)
    
    if not extracted:
        return {}
    
    # Фаза 2: Съпоставяне
    matched = phase2_match_products(client, extracted, store_name)
    
    return matched


# =============================================================================
# FALLBACK ТЪРСЕНЕ (резервен метод)
# =============================================================================

def extract_prices_with_fallback(page_text):
    """
    Резервен метод с ключови думи.
    Използва се само ако Claude не намери нищо.
    По-стриктен - изисква съвпадение на грамаж.
    """
    prices = {}
    page_lower = page_text.lower()
    
    # Специфични ключови думи с грамаж
    keywords_map = {
        "Био Локум роза": [("локум", "роза", "140")],
        "Био Обикновени бисквити с краве масло": [("бисквити", "масло", "150"), ("бисквити", "краве", "150")],
        "Айран harmonica": [("айран", "500")],
        "Био Тунквана вафла без захар": [("вафла", "без захар", "40"), ("тунквана", "без захар")],
        "Био Оризови топчета с черен шоколад": [("оризови", "топчета", "50"), ("топчета", "шоколад", "50")],
        "Био лимонада": [("лимонада", "330")],
        "Био тънки претцели с морска сол": [("претцели", "80"), ("претцели", "сол")],
        "Био тунквана вафла Класика": [("вафла", "класика", "40"), ("вафла", "класик", "40")],
        "Био вафла без добавена захар": [("вафла", "30")],
        "Био сироп от липа": [("сироп", "липа", "750")],
        "Био Пасирани домати": [("пасирани", "домати", "680"), ("passata", "680")],
        "Smiles с нахут и морска сол": [("smiles", "50"), ("смайлс", "нахут")],
        "Био Крема сирене": [("крема", "сирене", "125")],
        "Козе сирене harmonica": [("козе", "сирене", "200")],
    }
    
    for product in PRODUCTS:
        name = product['name']
        ref_price = product['ref_price_bgn']
        keywords_list = keywords_map.get(name, [])
        
        for keywords in keywords_list:
            # Проверяваме дали ВСИЧКИ ключови думи са в текста
            all_found = all(kw in page_lower for kw in keywords)
            
            if not all_found:
                continue
            
            # Намираме позицията на първата ключова дума
            idx = page_lower.find(keywords[0])
            if idx == -1:
                continue
            
            # Извличаме контекст
            context = page_text[max(0, idx-80):idx+150]
            
            # Търсим цена
            price_matches = re.findall(r'(\d+)[,.](\d{2})', context)
            for m in price_matches:
                try:
                    price = float(f"{m[0]}.{m[1]}")
                    # Стриктна проверка: ±60% от референтната
                    if 0.4 * ref_price <= price <= 1.6 * ref_price:
                        prices[name] = price
                        break
                except:
                    continue
            
            if name in prices:
                break
    
    return prices


# =============================================================================
# SCRAPING С ПОДОБРЕНО СКРОЛИРАНЕ
# =============================================================================

def scroll_for_all_products(page, scroll_times):
    """
    Подобрено скролиране за зареждане на всички продукти.
    Следи дали се появяват нови продукти при скролиране.
    """
    previous_height = 0
    no_change_count = 0
    
    for i in range(scroll_times):
        # Скролираме
        page.evaluate("window.scrollBy(0, 800)")
        page.wait_for_timeout(500)
        
        # Проверяваме дали страницата се е удължила
        current_height = page.evaluate("document.body.scrollHeight")
        
        if current_height == previous_height:
            no_change_count += 1
            # Ако 3 пъти няма промяна, спираме
            if no_change_count >= 3:
                print(f"    Скролиране: спряно след {i+1} опита (няма нови продукти)")
                break
        else:
            no_change_count = 0
            previous_height = current_height
    
    # Връщаме се в началото
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(300)


def scrape_store(page, store_key, store_config):
    """Извлича цени от един магазин с двуфазен Claude анализ."""
    prices = {}
    url = store_config['url']
    store_name = store_config['name_in_sheet']
    scroll_times = store_config.get('scroll_times', 10)
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
        
        # Подобрено скролиране
        print(f"  Скролиране за зареждане на всички продукти...")
        scroll_for_all_products(page, scroll_times)
        
        body_text = page.inner_text('body')
        print(f"  Заредени {len(body_text)} символа")
        
        # Debug: показваме малко от текста ако е твърде кратък
        if len(body_text) < 2000:
            print(f"  [DEBUG] Малко текст! Първи 300 символа:")
            print(f"  {body_text[:300]}")
        
    except Exception as e:
        print(f"  ✗ Грешка при зареждане: {str(e)[:80]}")
        return prices
    
    # Двуфазен Claude анализ
    try:
        claude_prices = extract_prices_with_claude_two_phase(body_text, store_name)
        print(f"  Claude (двуфазен): {len(claude_prices)} продукта")
        prices.update(claude_prices)
    except Exception as e:
        print(f"  Claude грешка: {str(e)[:50]}")
    
    # Fallback само за липсващи продукти
    try:
        print(f"  Fallback търсене...")
        fallback_prices = extract_prices_with_fallback(body_text)
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
        all_data.append(['HARMONICA - Ценови Тракер v5.5', '', '', '', '', '', '', '', '', '', '', ''])
        
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
    
    body += "\nПроверете Google Sheets за пълния отчет.\n\nПоздрави,\nHarmonica Price Tracker v5.5"
    
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
    print("HARMONICA PRICE TRACKER v5.5")
    print("Двуфазен Claude анализ")
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
