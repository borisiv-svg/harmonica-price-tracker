"""
T-Market (tmarketonline.bg) product extractor.

Extracts Harmonica products from T-Market Online vendor page.
Uses link patterns, generic fallback, and BS4 HTML parsing.
"""

import re

from config import EUR_BGN_RATE, logger, BS4_AVAILABLE
if BS4_AVAILABLE:
    from config import BeautifulSoup

from utils import (
    extract_eur_price,
    extract_bgn_price,
    deduplicate_check,
    is_food_product,
    is_harmonica_product,
)
from extractors.generic import _extract_generic_products


def extract_tmarket_products(markdown, html_text=None, brand_page=True):
    """
    Извлича Harmonica продукти от T-Market Online.

    T-Market vendor page: tmarketonline.bg/vendor/harmonica-1881705916
    На vendor page всички продукти са Harmonica → skip harmonica name check.
    Цени в BGN.
    """
    products = []
    seen = set()

    # Pattern 1: Всички links с продуктови имена
    link_pattern = r'\[([^\]]{5,120})\]\(((?:https?://[^\)]+|/[^\)]+))\)'
    for match in re.finditer(link_pattern, markdown):
        name = match.group(1).strip()

        if name.startswith('!') or 'logo' in name.lower():
            continue
        if len(re.findall(r'[а-яА-Яa-zA-Z]', name)) < 3:
            continue
        if not brand_page and not is_harmonica_product(name):
            continue
        if not is_food_product(name):
            continue

        name_key = name.lower()[:30]
        if name_key in seen:
            continue

        idx = match.end()
        context = markdown[max(0, idx - 150):idx + 400]

        bgn = extract_bgn_price(context)
        eur = extract_eur_price(context)

        if bgn and not eur:
            eur = round(bgn / EUR_BGN_RATE, 2)

        if bgn or eur:
            seen.add(name_key)
            products.append({"name": name, "eur": eur, "bgn": bgn})

    # Pattern 2: Generic text blocks + BS4 fallback
    if not products:
        products = _extract_generic_products(markdown, brand_page=brand_page)

    if BS4_AVAILABLE and html_text and not products:
        soup = BeautifulSoup(html_text, 'html.parser')
        for item in soup.select('.product-card, .product-item, .product, [class*=product]'):
            text = item.get_text(' ', strip=True)
            if not brand_page and not is_harmonica_product(text):
                continue
            name_el = item.select_one('h2, h3, h4, a.product-name, [class*=title], [class*=name]')
            if not name_el:
                for link in item.find_all('a', href=True):
                    link_text = link.get_text(strip=True)
                    if len(link_text) > 10:
                        name_el = link
                        break
            if not name_el:
                continue
            product_name = name_el.get_text(strip=True)
            name_key = product_name.lower()[:30]
            if name_key in seen or not is_food_product(product_name):
                continue
            bgn = extract_bgn_price(text)
            eur = extract_eur_price(text)
            if bgn and not eur:
                eur = round(bgn / EUR_BGN_RATE, 2)
            if bgn or eur:
                seen.add(name_key)
                products.append({"name": product_name, "eur": eur, "bgn": bgn})

    if not products:
        logger.warning(f"T-Market: 0 продукта, markdown len={len(markdown)}, "
                       f"preview: {markdown[:500]}")
    else:
        logger.info(f"T-Market: {len(products)} продукта извлечени")
    return products
