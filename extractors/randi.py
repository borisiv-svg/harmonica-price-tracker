"""
Randi (randi.bg) product extractor.

Extracts products from Randi.bg markdown. Product blocks contain links with
names and prices on separate lines.
"""

import re

from config import EUR_BGN_RATE, logger
from utils import (
    extract_eur_price,
    extract_bgn_price,
    extract_price_fallback,
    is_food_product,
    is_harmonica_product,
)


def extract_randi_products(markdown):
    """
    Извлича продукти от Randi.bg markdown.

    Randi формат: продуктовите блокове съдържат линк с име + цена X,XX лв
    на отделен ред. Блоковете са разделени визуално.
    """
    products = []
    seen = set()

    lines = markdown.split('\n')

    for i, line in enumerate(lines):
        line_stripped = line.strip()

        # Търсим линкове с продуктови имена
        link_match = re.search(r'(?<!!)\[([^\]]{5,120})\]\(([^\)]+)\)', line_stripped)
        if not link_match:
            continue

        name = link_match.group(1).strip()

        # Филтрираме навигационни линкове
        if not is_food_product(name):
            continue
        if len(name) < 8:
            continue
        if not is_harmonica_product(name):
            # Проверяваме контекста за harmonica
            context_lines = '\n'.join(lines[max(0, i - 3):i + 5])
            if 'harmonica' not in context_lines.lower() and 'хармоника' not in context_lines.lower():
                continue

        name_key = name.lower()[:30]
        if name_key in seen:
            continue

        # Търсим цена НАПРЕД от името (тесен прозорец), после разширяваме
        bgn, eur = None, None
        for ctx_start, ctx_end in [(i, i + 3), (max(0, i - 1), i + 5)]:
            context = '\n'.join(lines[ctx_start:min(len(lines), ctx_end)])
            bgn = extract_bgn_price(context)
            if not bgn:
                bgn = extract_price_fallback(context)
            eur = extract_eur_price(context)
            if bgn or eur:
                break

        if bgn or eur:
            if bgn and not eur:
                eur = round(bgn / EUR_BGN_RATE, 2)
            seen.add(name_key)
            products.append({"name": name, "eur": eur, "bgn": bgn})

    return products
