"""
Metro (metro.bg) product extractor.

Extracts products from Metro markdown. Line-by-line format with links/text + prices.
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


def extract_metro_products(markdown):
    """
    Извлича продукти от Metro markdown.

    Metro формат: продуктите са line-by-line, често с формат:
    - Линк или текст с име + грамаж
    - Цена X,XX лв на близък ред (понякога на същия ред)
    Блоковете не са разделени с двоен нов ред (generic extractor не работи).
    """
    products = []
    seen = set()

    lines = markdown.split('\n')

    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if not line_stripped:
            continue

        # Търсим линкове с продуктови имена
        link_match = re.search(r'(?<!!)\[([^\]]{5,120})\]\(([^\)]+)\)', line_stripped)
        name = None

        if link_match:
            candidate = link_match.group(1).strip()
            if is_food_product(candidate) and len(candidate) >= 8:
                name = candidate
        else:
            # Пробваме текстов ред с грамаж
            if re.search(r'\d+\s*(?:г|мл|ml|g)\b', line_stripped, re.IGNORECASE):
                candidate = clean_product_name(line_stripped)
                if is_food_product(candidate) and 8 <= len(candidate) <= 120:
                    name = candidate

        if not name:
            continue

        if not is_harmonica_product(name):
            context_lines = '\n'.join(lines[max(0, i - 5):i + 5])
            if 'harmonica' not in context_lines.lower() and 'хармоника' not in context_lines.lower():
                continue

        if deduplicate_check(name, seen):
            continue

        # Търсим цена НАПРЕД от името (тесен прозорец: 3 реда), за да не хванем
        # цена от съседен продукт. Разширяваме до 5 само ако не намерим.
        bgn, eur = None, None
        for ctx_start, ctx_end in [(i, i + 3), (max(0, i - 1), i + 5)]:
            ctx = '\n'.join(lines[ctx_start:min(len(lines), ctx_end)])
            bgn = extract_bgn_price(ctx)
            if not bgn:
                bgn = extract_price_fallback(ctx)
            eur = extract_eur_price(ctx)
            if bgn or eur:
                break

        if bgn or eur:
            if bgn and not eur:
                eur = round(bgn / EUR_BGN_RATE, 2)
            products.append({"name": name, "eur": eur, "bgn": bgn})

    return products
