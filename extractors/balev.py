"""
Balev (balev.bg) product extractor.

Extracts products from Balev markdown. Format: lines with weight + contextual prices.
"""

import re

from config import EUR_BGN_RATE, logger
from utils import (
    clean_product_name,
    deduplicate_check,
    find_price_bounded,
    is_food_product,
    is_harmonica_product,
)


def extract_balev_products(markdown):
    """Извлича продукти от Balev. Формат: редове с грамаж + контекстни цени."""
    products = []
    seen = set()

    lines = markdown.split('\n')

    for i, line in enumerate(lines):
        line = line.strip()

        if not re.search(r'\d+\s*(?:гр|г|мл|ml|g|kg|кг|л|l)\b', line, re.IGNORECASE):
            continue

        name = clean_product_name(line)

        if len(name) < 5 or len(name) > 80:
            continue
        if len(re.findall(r'[а-яА-Яa-zA-Z]', name)) < 3:
            continue

        if not (is_harmonica_product(name) or 'harmonica' in markdown[max(0,i-5):i+5].lower()):
            context_lines = '\n'.join(lines[max(0,i-3):i+3])
            if not ('harmonica' in context_lines.lower() or 'хармоника' in context_lines.lower()):
                continue

        if deduplicate_check(name, seen):
            continue
        if not is_food_product(name):
            continue

        # Bounded forward search: търсим цена НАПРЕД, но спираме при
        # следващия продуктов ред (предотвратява "price bleed")
        eur, bgn = find_price_bounded(lines, i)

        if bgn and not eur:
            eur = round(bgn / EUR_BGN_RATE, 2)

        if eur or bgn:
            products.append({"name": name, "eur": eur, "bgn": bgn})

    return products
