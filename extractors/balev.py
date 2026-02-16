"""
Balev (balev.bg) product extractor.

Extracts products from Balev markdown. Format: lines with weight + contextual prices.
"""

import re

from config import EUR_BGN_RATE, logger
from utils import (
    extract_eur_price,
    extract_bgn_price,
    extract_price_fallback,
    clean_product_name,
    deduplicate_check,
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

        if not re.search(r'\d+\s*(?:г|мл|ml|g)\b', line, re.IGNORECASE):
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

        # Търсим цена НАПРЕД от името (тесен прозорец), за да не хванем
        # цена от предходен продукт. Разширяваме само ако не намерим.
        eur, bgn = None, None
        for ctx_start, ctx_end in [(i, i + 3), (max(0, i - 1), i + 5)]:
            ctx = '\n'.join(lines[ctx_start:min(len(lines), ctx_end)])
            eur = extract_eur_price(ctx)
            bgn = extract_bgn_price(ctx)
            if not bgn and not eur:
                bgn = extract_price_fallback(ctx)
            if bgn or eur:
                break

        if bgn and not eur:
            eur = round(bgn / EUR_BGN_RATE, 2)

        if eur or bgn:
            products.append({"name": name, "eur": eur, "bgn": bgn})

    return products
