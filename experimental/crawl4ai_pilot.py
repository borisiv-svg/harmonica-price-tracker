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
# ОСНОВНИ ФУНКЦИИ
# =============================================================================

async def crawl_balev_with_crawl4ai():
    """
    Извлича продукти от Bal
