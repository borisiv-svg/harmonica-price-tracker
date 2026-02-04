"""
EXP-001: Crawl4AI Pilot Test
============================
Пилотен скрипт за тестване на Crawl4AI с Balev Bio Market.

Цели:
1. Да проверим дали Crawl4AI може да извлече продуктите от Balev
2. Да сравним с текущия Playwright подход
3. Да измерим времето за изпълнение

Изпълнение:
    python experimental/crawl4ai_pilot.py
"""

import asyncio
import time
import json
import os
import re

# Опитваме да импортираме Crawl4AI
try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    CRAWL4AI_AVAILABLE = True
except ImportError:
    CRAWL4AI_AVAILABLE = False
    print("⚠️  Crawl4AI не е инсталиран. Инсталирай с: pip install crawl4ai")


# =============================================================================
# КОНФИГУРАЦИЯ
# =============================================================================

# URL на Balev Bio Market страницата с Harmonica продукти
BALEV_URL = "https://balevbiomarket.com/productBrands/harmonica"

# Референтни продукти за проверка (subset от пълния списък)
REFERENCE_PRODUCTS = [
    {"name": "Био Локум роза", "weight": "140г", "ref_price": 3.81},
    {"name": "Био тънки претцели с морска сол", "weight": "80г", "ref_price": 2.50},
    {"name": "Био лимонада", "weight": "330мл", "ref_price": 3.48},
    {"name": "Айран harmonica", "weight": "500мл", "ref_price": 2.90},
    {"name": "Био сироп от липа", "weight": "750мл", "ref_price": 14.29},
]


# =============================================================================
# CSS СЕЛЕКТОРИ ЗА BALEV
# =============================================================================

# Тези селектори са базирани на HTML структурата на Balev Bio Market
# Може да се наложи да ги коригираме след първия тест

BALEV_SELECTORS = {
    # Контейнер за всички продукти
    "product_container": ".product-item, .product-card, .product",
    
    # Име на продукта
    "product_name": ".product-name, .product-title, h2, h3",
    
    # Цена
    "product_price": ".price, .product-price, .price-value",
    
    # Грамаж/тегло (ако е отделно поле)
    "product_weight": ".weight, .product-weight, .volume",
}


# =============================================================================
# ОСНОВНИ ФУНКЦИИ
# =============================================================================

async def crawl_balev_with_crawl4ai():
    """
    Извлича продукти от Balev използвайки Crawl4AI.
    
    Crawl4AI предлага два основни подхода:
    1. CSS Extraction - бързо, без LLM разходи, но изисква познаване на HTML структурата
    2. LLM Extraction - по-гъвкаво, разбира контекста, но има API разходи
    
    В този пилот тестваме CSS подхода първо.
    """
    
    print("\n" + "=" * 60)
    print("🔬 CRAWL4AI PILOT TEST - Balev Bio Market")
    print("=" * 60)
    
    if not CRAWL4AI_AVAILABLE:
        print("❌ Crawl4AI не е наличен. Прескачаме теста.")
        return None
    
    # Конфигурация на браузъра
    browser_config = BrowserConfig(
        headless=True,  # Без видим прозорец
        verbose=False,
    )
    
    # Конфигурация на crawler-а
    crawler_config = CrawlerRunConfig(
        wait_until="networkidle",  # Изчакай всички заявки да приключат
        page_timeout=30000,  # 30 секунди timeout
    )
    
    start_time = time.time()
    
    try:
        async with AsyncWebCrawler(config=browser_config) as crawler:
            print(f"\n📡 Зареждане на {BALEV_URL}")
            
            # Изпълняваме crawl
            result = await crawler.arun(
                url=BALEV_URL,
                config=crawler_config,
            )
            
            elapsed_time = time.time() - start_time
            
            if result.success:
                print(f"✅ Страницата е заредена успешно за {elapsed_time:.2f} секунди")
                print(f"📄 Получен HTML: {len(result.html)} символа")
                
                # Извличаме продуктите от HTML-а
                products = extract_products_from_html(result.html)
                
                return {
                    "success": True,
                    "products": products,
                    "html_length": len(result.html),
                    "elapsed_time": elapsed_time,
                }
            else:
                print(f"❌ Грешка при зареждане: {result.error_message}")
                return {
                    "success": False,
                    "error": result.error_message,
                    "elapsed_time": elapsed_time,
                }
                
    except Exception as e:
        elapsed_time = time.time() - start_time
        print(f"❌ Изключение: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "elapsed_time": elapsed_time,
        }


def extract_products_from_html(html: str) -> list:
    """
    Извлича продукти от HTML използвайки регулярни изрази.
    
    Това е опростен подход за пилотния тест. В production версията
    бихме използвали BeautifulSoup или вградените CSS екстрактори на Crawl4AI.
    """
    
    products = []
    
    # Търсим patterns за цени (напр. "3.81 лв", "14,29 лв", "2.50 €")
    price_pattern = r'(\d+[.,]\d{2})\s*(?:лв|BGN|€|EUR)'
    
    # Търсим грамажи (напр. "140г", "750мл", "500 мл")
    weight_pattern = r'(\d+)\s*(г|мл|ml|g|кг|kg|л|l)'
    
    # Търсим имена на Harmonica продукти
    harmonica_keywords = [
        "локум", "бисквити", "айран", "вафла", "претцели",
        "лимонада", "сироп", "домати", "сирене", "кисело мляко",
        "оризови топчета", "smiles", "крема"
    ]
    
    # Извличаме всички цени
    prices = re.findall(price_pattern, html, re.IGNORECASE)
    print(f"\n🔍 Намерени цени в HTML: {len(prices)}")
    if prices[:10]:
        print(f"   Първи 10: {prices[:10]}")
    
    # Извличаме всички грамажи
    weights = re.findall(weight_pattern, html, re.IGNORECASE)
    print(f"🔍 Намерени грамажи: {len(weights)}")
    
    # Проверяваме за Harmonica ключови думи
    found_keywords = []
    html_lower = html.lower()
    for keyword in harmonica_keywords:
        if keyword in html_lower:
            count = html_lower.count(keyword)
            found_keywords.append(f"{keyword} ({count}x)")
    
    print(f"🔍 Намерени ключови думи: {', '.join(found_keywords)}")
    
    # За пилотния тест връщаме обобщена информация
    # В production версията ще парсваме структурирано
    return {
        "prices_found": len(prices),
        "unique_prices": list(set(prices))[:20],
        "weights_found": len(weights),
        "keywords_found": found_keywords,
        "html_sample": html[:2000] if len(html) > 2000 else html,
    }


def compare_with_reference(crawl_result: dict) -> dict:
    """
    Сравнява резултатите от Crawl4AI с референтните продукти.
    """
    
    print("\n" + "=" * 60)
    print("📊 СРАВНЕНИЕ С РЕФЕРЕНТНИ ПРОДУКТИ")
    print("=" * 60)
    
    if not crawl_result or not crawl_result.get("success"):
        print("❌ Няма данни за сравнение")
        return {"matches": 0, "total": len(REFERENCE_PRODUCTS)}
    
    products_data = crawl_result.get("products", {})
    unique_prices = products_data.get("unique_prices", [])
    
    # Конвертираме цените към float за сравнение
    found_prices = []
    for p in unique_prices:
        try:
            # Заменяме запетая с точка и конвертираме
            price = float(p.replace(",", "."))
            found_prices.append(price)
        except:
            pass
    
    print(f"\n📋 Референтни продукти: {len(REFERENCE_PRODUCTS)}")
    print(f"💰 Намерени уникални цени: {len(found_prices)}")
    
    matches = 0
    for ref_product in REFERENCE_PRODUCTS:
        ref_price = ref_product["ref_price"]
        # Проверяваме дали референтната цена е сред намерените (с толеранс от 5%)
        found = any(abs(p - ref_price) / ref_price < 0.05 for p in found_prices)
        
        status = "✅" if found else "❌"
        print(f"  {status} {ref_product['name']} ({ref_product['weight']}) - {ref_price} лв")
        
        if found:
            matches += 1
    
    match_rate = (matches / len(REFERENCE_PRODUCTS)) * 100
    print(f"\n📈 Съвпадение: {matches}/{len(REFERENCE_PRODUCTS)} ({match_rate:.0f}%)")
    
    return {
        "matches": matches,
        "total": len(REFERENCE_PRODUCTS),
        "match_rate": match_rate,
    }


async def main():
    """
    Главна функция на пилотния тест.
    """
    
    print("\n" + "=" * 60)
    print("🧪 EXP-001: CRAWL4AI PILOT TEST")
    print("=" * 60)
    print(f"📅 Дата: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🏪 Магазин: Balev Bio Market")
    print(f"🔗 URL: {BALEV_URL}")
    
    # Стъпка 1: Crawl с Crawl4AI
    crawl_result = await crawl_balev_with_crawl4ai()
    
    # Стъпка 2: Сравнение с референции
    comparison = compare_with_reference(crawl_result)
    
    # Стъпка 3: Обобщение
    print("\n" + "=" * 60)
    print("📋 ОБОБЩЕНИЕ НА ЕКСПЕРИМЕНТА")
    print("=" * 60)
    
    if crawl_result and crawl_result.get("success"):
        print(f"✅ Статус: УСПЕШЕН")
        print(f"⏱️  Време за изпълнение: {crawl_result['elapsed_time']:.2f} секунди")
        print(f"📄 HTML размер: {crawl_result['html_length']:,} символа")
        print(f"📊 Съвпадение на цени: {comparison['match_rate']:.0f}%")
    else:
        print(f"❌ Статус: НЕУСПЕШЕН")
        if crawl_result:
            print(f"🔴 Грешка: {crawl_result.get('error', 'Неизвестна')}")
    
    print("\n" + "=" * 60)
    print("🔬 КРАЙ НА ПИЛОТНИЯ ТЕСТ")
    print("=" * 60)
    
    # Записваме резултатите във файл
    results = {
        "experiment": "EXP-001",
        "date": time.strftime('%Y-%m-%d %H:%M:%S'),
        "store": "Balev Bio Market",
        "crawl_result": crawl_result,
        "comparison": comparison,
    }
    
    results_file = "experimental/pilot_results.json"
    try:
        with open(results_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n💾 Резултатите са записани в: {results_file}")
    except Exception as e:
        print(f"\n⚠️  Не успях да запиша резултатите: {e}")
    
    return results


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    # Изпълняваме а
