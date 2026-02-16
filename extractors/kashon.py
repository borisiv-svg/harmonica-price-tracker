"""
Kashon (kashonharmonica.bg) product extractor.

Extracts products from Kashon markdown. Format: [Name](URL) with prices nearby.
"""

import re

from config import EUR_BGN_RATE, logger
from utils import (
    extract_eur_price,
    extract_bgn_price,
    deduplicate_check,
    is_food_product,
    KASHON_BRAND_BLACKLIST,
    KASHON_JUNK_ENTRIES,
)


def extract_kashon_products(markdown):
    """Извлича продукти от Кашон. Формат: [Име](URL) с цени наблизо."""
    products = []
    seen = set()

    pattern = r'\[([^\]]{5,80})\]\(https://kashonharmonica\.bg/bg/products/([^\)]+)\)'

    for match in re.finditer(pattern, markdown):
        name = match.group(1).strip()

        if name.startswith('!') or 'logo' in name.lower():
            continue
        if len(re.findall(r'[а-яА-Яa-zA-Z]', name)) < 3:
            continue
        if deduplicate_check(name, seen):
            continue
        if not is_food_product(name):
            continue
        if any(bl in name.lower() for bl in KASHON_BRAND_BLACKLIST):
            continue
        if any(j in name.lower() for j in KASHON_JUNK_ENTRIES):
            continue

        idx = match.end()
        # Търсим цена напред (500 chars) — покрива повече layout варианти
        context_forward = markdown[idx:idx+500]
        eur = extract_eur_price(context_forward)
        bgn = extract_bgn_price(context_forward)

        # Ако не намерим напред, търсим и назад (150 chars — цената може да е преди линка)
        if not eur and not bgn:
            context_back = markdown[max(0, match.start()-150):match.start()]
            eur = extract_eur_price(context_back)
            bgn = extract_bgn_price(context_back)

        if not eur and bgn:
            eur = round(bgn / EUR_BGN_RATE, 2)

        if eur or bgn:
            products.append({"name": name, "eur": eur, "bgn": bgn})

    return products
