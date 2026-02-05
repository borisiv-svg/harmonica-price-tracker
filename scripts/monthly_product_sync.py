"""
Harmonica Product Sync - Месечна синхронизация на продуктов списък
===================================================================

Този скрипт сканира Кашон Harmonica и синхронизира локалния списък с продукти.

Използване:
- Първоначално: Създава harmonica_products.json с всички продукти
- Месечно: Сравнява с текущия списък и добавя нови/маркира отпаднали

Изпълнява се автоматично на всеки 4 седмици чрез GitHub Actions.
"""

import asyncio
import json
import os
import re
import smtplib
from datetime import datetime
from email.mime.text import MIMEText

try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    CRAWL4AI_AVAILABLE = True
except ImportError:
    CRAWL4AI_AVAILABLE = False
    print("⚠️ Crawl4AI not installed. Run: pip install crawl4ai && crawl4ai-setup")


# =============================================================================
# CONFIGURATION
# =============================================================================

KASHON_URL = "https://kashonharmonica.bg/bg/products"
SCROLL_TIMES = 12  # Достатъчно за зареждане на всички продукти

PRODUCTS_FILE = "data/products/harmonica_products.json"
SYNC_LOG_FILE = "data/products/sync_log.json"

# Email configuration (от environment variables)
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "")


# =============================================================================
# FOOD FILTERING
# =============================================================================

FOOD_KEYWORDS = [
    "мляко", "айран", "кефир", "сирене", "кашкавал", "масло", "сметана",
    "извара", "йогурт", "крема", "сок", "лимонада", "боза", "сироп",
    "локум", "бисквит", "вафла", "шоколад", "бонбон", "сладко", "халва",
    "претцел", "солет", "крекер", "соленки", "лешник", "бадем", "орех",
    "домат", "кетчуп", "лютеница", "пюре", "паста", "хляб", "кори",
    "олио", "оцет", "зехтин", "мед", "чай", "smiles", "топчета",
    "нахут", "хумус", "яйца", "тахан", "фъстъчено", "ядки",
]

NON_FOOD_KEYWORDS = [
    "потник", "тениска", "блуза", "дреха", "шапка", "чанта", "раница",
    "козметика", "крем", "шампоан", "сапун", "гел", "лосион", "парфюм",
]


def is_food_product(name):
    """Проверява дали е хранителен продукт."""
    name_lower = name.lower()
    
    for kw in NON_FOOD_KEYWORDS:
        if kw in name_lower:
            return False
    
    for kw in FOOD_KEYWORDS:
        if kw in name_lower:
            return True
    
    # Ако има грамаж, вероятно е храна
    if re.search(r'\d+\s*(?:г|мл|ml|g|kg|л)\b', name_lower):
        return True
    
    return True  # По подразбиране приемаме


# =============================================================================
# PRICE EXTRACTION (IMPROVED)
# =============================================================================

def extract_eur_price(text):
    """Извлича EUR цена - търси в различни формати."""
    patterns = [
        r'(\d+)[,.](\d{2})\s*€',           # 2.38 € или 2,38 €
        r'€\s*(\d+)[,.](\d{2})',            # € 2.38
        r'(\d+)[,.](\d{2})\s*EUR',          # 2.38 EUR
        r'(\d+)[,.](\d{2})\s*евро',         # 2.38 евро
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                price = float(f"{match.group(1)}.{match.group(2)}")
                if 0.20 <= price <= 100:
                    return round(price, 2)
            except:
                pass
    return None


def extract_bgn_price(text):
    """Извлича BGN цена - търси в различни формати."""
    patterns = [
        r'(\d+)[,.](\d{2})\s*лв',           # 2.74 лв
        r'(\d+)[,.](\d{2})\s*лева',         # 2.74 лева
        r'(\d+)[,.](\d{2})\s*BGN',          # 2.74 BGN
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                price = float(f"{match.group(1)}.{match.group(2)}")
                if 0.50 <= price <= 200:
                    return round(price, 2)
            except:
                pass
    return None


def extract_prices_from_context(markdown, position, search_range=500):
    """
    Извлича EUR и BGN цени от контекста около позиция.
    Търси и преди, и след позицията.
    """
    start = max(0, position - search_range)
    end = min(len(markdown), position + search_range)
    context = markdown[start:end]
    
    eur = extract_eur_price(context)
    bgn = extract_bgn_price(context)
    
    return eur, bgn

def extract_keywords(name):
    """Извлича ключови думи за matching."""
    name_lower = name.lower()
    # Премахваме общи думи
    name_lower = re.sub(r'harmonica|хармоника|био\s*', '', name_lower)
    # Извличаме думи (мин 3 букви) и числа с мерни единици
    keywords = re.findall(r'[а-я]{3,}|\d+(?:\s*(?:г|мл|ml|g|%|л))?', name_lower)
    return [k.strip() for k in keywords if k.strip()]


# =============================================================================
# KASHON EXTRACTION
# =============================================================================

def extract_kashon_products(markdown):
    """
    Извлича всички Harmonica продукти от Кашон markdown.
    """
    products = []
    seen = set()
    
    # Pattern за markdown links към продукти
    pattern = r'\[([^\]]{5,80})\]\(https://kashonharmonica\.bg/bg/products/([^\)]+)\)'
    
    for match in re.finditer(pattern, markdown):
        name = match.group(1).strip()
        url_slug = match.group(2)
        
        # Пропускаме невалидни
        if name.startswith('!') or 'logo' in name.lower():
            continue
        if len(re.findall(r'[а-яА-Яa-zA-Z]', name)) < 3:
            continue
        
        # Проверяваме за дубликати
        name_key = name.lower()[:30]
        if name_key in seen:
            continue
        
        # Филтрираме само храни
        if not is_food_product(name):
            continue
        
        # Търсим цена в контекста
        idx = match.end()
        context = markdown[idx:idx+300]
        
        eur = extract_eur_price(context)
        bgn = extract_bgn_price(context)
        
        if eur or bgn:
            seen.add(name_key)
            products.append({
                "name": name,
                "url_slug": url_slug,
                "eur": eur,
                "bgn": bgn,
                "keywords": extract_keywords(name),
            })
    
    return products


# =============================================================================
# CRAWLING
# =============================================================================

async def crawl_kashon():
    """Сканира Кашон и връща markdown."""
    
    if not CRAWL4AI_AVAILABLE:
        print("❌ Crawl4AI не е инсталиран!")
        return None
    
    print(f"🔍 Сканиране на Кашон Harmonica...")
    print(f"   URL: {KASHON_URL}")
    
    scroll_js = f"""
    async function scrollPage() {{
        for (let i = 0; i < {SCROLL_TIMES}; i++) {{
            window.scrollTo(0, document.body.scrollHeight);
            await new Promise(r => setTimeout(r, 1500));
        }}
    }}
    await scrollPage();
    """
    
    browser_config = BrowserConfig(
        headless=True,
        viewport_width=1920,
        viewport_height=1080,
    )
    
    crawler_config = CrawlerRunConfig(
        page_timeout=120000,
        remove_overlay_elements=True,
        js_code=scroll_js,
    )
    
    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=KASHON_URL, config=crawler_config)
        
        if result.success:
            print(f"✅ Успешно: {len(result.markdown)} символа")
            return result.markdown
        else:
            print(f"❌ Грешка: {result.error_message}")
            return None


# =============================================================================
# FILE OPERATIONS
# =============================================================================

def load_current_products():
    """Зарежда текущия списък с продукти."""
    if not os.path.exists(PRODUCTS_FILE):
        return None
    
    try:
        with open(PRODUCTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Грешка при четене на {PRODUCTS_FILE}: {e}")
        return None


def save_products(data):
    """Записва списъка с продукти."""
    os.makedirs(os.path.dirname(PRODUCTS_FILE), exist_ok=True)
    
    with open(PRODUCTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Записано в {PRODUCTS_FILE}")


def save_sync_log(log_entry):
    """Добавя запис в sync log."""
    os.makedirs(os.path.dirname(SYNC_LOG_FILE), exist_ok=True)
    
    # Зареждаме съществуващия лог
    log = []
    if os.path.exists(SYNC_LOG_FILE):
        try:
            with open(SYNC_LOG_FILE, 'r', encoding='utf-8') as f:
                log = json.load(f)
        except:
            pass
    
    # Добавяме новия запис
    log.append(log_entry)
    
    # Запазваме последните 52 записа (1 година)
    log = log[-52:]
    
    with open(SYNC_LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


# =============================================================================
# SYNC LOGIC
# =============================================================================

def compare_products(old_products, new_products):
    """
    Сравнява стар и нов списък с продукти.
    Връща dict с промените.
    """
    old_names = {p["name"].lower()[:30]: p for p in old_products}
    new_names = {p["name"].lower()[:30]: p for p in new_products}
    
    old_keys = set(old_names.keys())
    new_keys = set(new_names.keys())
    
    added_keys = new_keys - old_keys
    removed_keys = old_keys - new_keys
    
    added = [new_names[k] for k in added_keys]
    removed = [old_names[k] for k in removed_keys]
    
    # Проверка за промени в цени (>10%)
    price_changes = []
    for key in old_keys & new_keys:
        old_p = old_names[key]
        new_p = new_names[key]
        
        old_eur = old_p.get("ref_eur") or old_p.get("eur")
        new_eur = new_p.get("eur")
        
        if old_eur and new_eur:
            change_pct = abs(new_eur - old_eur) / old_eur * 100
            if change_pct >= 10:
                price_changes.append({
                    "name": new_p["name"],
                    "old_eur": old_eur,
                    "new_eur": new_eur,
                    "change_pct": round(change_pct, 1),
                })
    
    return {
        "added": added,
        "removed": removed,
        "price_changes": price_changes,
    }


def send_notification(changes, total_products):
    """Изпраща имейл известие за промени."""
    
    if not SMTP_USER or not ALERT_EMAIL:
        print("⚠️ Email не е конфигуриран, пропускане на известие")
        return
    
    added = changes["added"]
    removed = changes["removed"]
    price_changes = changes["price_changes"]
    
    if not added and not removed and not price_changes:
        print("📧 Няма промени, няма да се изпраща известие")
        return
    
    # Съставяме съобщението
    subject = f"🔄 Harmonica Product Sync: {len(added)} нови, {len(removed)} премахнати"
    
    body = f"""
Harmonica Product Sync Report
=============================
Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}
Общо продукти: {total_products}

"""
    
    if added:
        body += f"✅ НОВИ ПРОДУКТИ ({len(added)}):\n"
        for p in added:
            eur = f"{p['eur']:.2f}€" if p.get('eur') else "N/A"
            body += f"  - {p['name']}: {eur}\n"
        body += "\n"
    
    if removed:
        body += f"❌ ПРЕМАХНАТИ ПРОДУКТИ ({len(removed)}):\n"
        for p in removed:
            body += f"  - {p['name']}\n"
        body += "\n"
    
    if price_changes:
        body += f"💰 ЦЕНОВИ ПРОМЕНИ >10% ({len(price_changes)}):\n"
        for p in price_changes:
            body += f"  - {p['name']}: {p['old_eur']:.2f}€ → {p['new_eur']:.2f}€ ({p['change_pct']:+.1f}%)\n"
        body += "\n"
    
    body += """
---
Автоматично генерирано от Harmonica Price Tracker
    """
    
    try:
        msg = MIMEText(body, 'plain', 'utf-8')
        msg['Subject'] = subject
        msg['From'] = SMTP_USER
        msg['To'] = ALERT_EMAIL
        
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        
        print(f"📧 Известие изпратено до {ALERT_EMAIL}")
    except Exception as e:
        print(f"⚠️ Грешка при изпращане на имейл: {e}")


# =============================================================================
# MAIN
# =============================================================================

async def main():
    print("\n" + "="*60)
    print("🔄 HARMONICA PRODUCT SYNC")
    print("="*60)
    print(f"📅 Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 1. Сканираме Кашон
    markdown = await crawl_kashon()
    
    if not markdown:
        print("❌ Не можа да се сканира Кашон, прекратяване.")
        return
    
    # 2. Извличаме продукти
    print("\n📦 Извличане на продукти...")
    new_products = extract_kashon_products(markdown)
    print(f"   Намерени: {len(new_products)} продукта")
    
    if len(new_products) < 10:
        print("⚠️ Твърде малко продукти, възможна грешка. Прекратяване.")
        return
    
    # 3. Зареждаме текущия списък
    current_data = load_current_products()
    
    if current_data is None:
        # Първоначално създаване
        print("\n🆕 Първоначално създаване на продуктов списък...")
        
        products_data = {
            "version": "1.0",
            "last_sync": datetime.now().strftime('%Y-%m-%d'),
            "source": "kashonharmonica.bg",
            "total_products": len(new_products),
            "products": []
        }
        
        for i, p in enumerate(new_products, 1):
            products_data["products"].append({
                "id": i,
                "name": p["name"],
                "keywords": p["keywords"],
                "ref_eur": p["eur"],
                "ref_bgn": p["bgn"],
                "url_slug": p["url_slug"],
                "active": True,
                "added_date": datetime.now().strftime('%Y-%m-%d'),
            })
        
        save_products(products_data)
        
        log_entry = {
            "date": datetime.now().strftime('%Y-%m-%d %H:%M'),
            "action": "initial_create",
            "total_products": len(new_products),
            "added": len(new_products),
            "removed": 0,
        }
        save_sync_log(log_entry)
        
        print(f"\n✅ Създадени {len(new_products)} продукта")
        
    else:
        # Синхронизация с текущ списък
        print(f"\n🔄 Синхронизация с текущ списък ({current_data['total_products']} продукта)...")
        
        old_products = current_data["products"]
        changes = compare_products(old_products, new_products)
        
        print(f"   Нови: {len(changes['added'])}")
        print(f"   Премахнати: {len(changes['removed'])}")
        print(f"   Ценови промени: {len(changes['price_changes'])}")
        
        # Обновяваме списъка
        # Маркираме премахнатите като неактивни
        old_names_lower = {p["name"].lower()[:30]: p for p in old_products}
        new_names_lower = {p["name"].lower()[:30] for p in new_products}
        
        for p in old_products:
            key = p["name"].lower()[:30]
            if key not in new_names_lower:
                p["active"] = False
                p["removed_date"] = datetime.now().strftime('%Y-%m-%d')
        
        # Добавяме новите
        max_id = max(p["id"] for p in old_products) if old_products else 0
        for p in changes["added"]:
            max_id += 1
            old_products.append({
                "id": max_id,
                "name": p["name"],
                "keywords": p["keywords"],
                "ref_eur": p["eur"],
                "ref_bgn": p["bgn"],
                "url_slug": p["url_slug"],
                "active": True,
                "added_date": datetime.now().strftime('%Y-%m-%d'),
            })
        
        # Обновяваме референтните цени за активните
        for p in old_products:
            if not p.get("active", True):
                continue
            key = p["name"].lower()[:30]
            for new_p in new_products:
                if new_p["name"].lower()[:30] == key:
                    if new_p["eur"]:
                        p["ref_eur"] = new_p["eur"]
                    if new_p["bgn"]:
                        p["ref_bgn"] = new_p["bgn"]
                    break
        
        # Обновяваме метаданните
        current_data["last_sync"] = datetime.now().strftime('%Y-%m-%d')
        current_data["total_products"] = len([p for p in old_products if p.get("active", True)])
        current_data["products"] = old_products
        
        save_products(current_data)
        
        # Записваме в лога
        log_entry = {
            "date": datetime.now().strftime('%Y-%m-%d %H:%M'),
            "action": "sync",
            "total_products": current_data["total_products"],
            "added": len(changes["added"]),
            "removed": len(changes["removed"]),
            "price_changes": len(changes["price_changes"]),
        }
        save_sync_log(log_entry)
        
        # Изпращаме известие
        send_notification(changes, current_data["total_products"])
        
        # Показваме промените
        if changes["added"]:
            print("\n✅ Нови продукти:")
            for p in changes["added"][:10]:
                eur = f"{p['eur']:.2f}€" if p.get('eur') else "N/A"
                print(f"   + {p['name']}: {eur}")
            if len(changes["added"]) > 10:
                print(f"   ... и още {len(changes['added']) - 10}")
        
        if changes["removed"]:
            print("\n❌ Премахнати продукти:")
            for p in changes["removed"][:10]:
                print(f"   - {p['name']}")
            if len(changes["removed"]) > 10:
                print(f"   ... и още {len(changes['removed']) - 10}")
    
    print("\n" + "="*60)
    print("✅ SYNC ЗАВЪРШЕН")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
