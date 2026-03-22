"""
DM Bulgaria (dm-drogeriemarkt.bg) product extractor.

Extracts Harmonica products from DM Bulgaria search results.
Uses BS4 + HTML when available, with regex + markdown fallback.
"""

import re

from config import EUR_BGN_RATE, PRICE_RANGE_BGN, logger, BS4_AVAILABLE
if BS4_AVAILABLE:
    from config import BeautifulSoup

from utils import (
    extract_eur_price,
    extract_bgn_price,
    validate_eur_bgn,
    is_food_product,
)


def extract_dm_products(markdown_text, html_text=None):
    """
    Извлича Harmonica продукти от DM Bulgaria.

    DM.bg показва продукти в search резултати с имена и цени.
    Предпочита BS4 + HTML ако е наличен, иначе regex + markdown.
    """
    if BS4_AVAILABLE and html_text:
        return _extract_dm_bs4(html_text)
    return _extract_dm_regex(markdown_text)


def _extract_dm_bs4(html_text):
    """Извлича DM продукти с BeautifulSoup."""
    products = []
    seen = set()
    soup = BeautifulSoup(html_text, 'html.parser')

    # DM.bg типично използва product cards/tiles в search results
    product_items = soup.select(
        '[data-testid="product-tile"], .product-tile, .product-card, '
        '.search-result-item, .product-item, article.product'
    )

    # Fallback: търсим всички елементи с текст "Harmonica"
    if not product_items:
        for el in soup.find_all(['div', 'li', 'article', 'section']):
            text = el.get_text(strip=True)
            if ('harmonica' in text.lower() or 'хармоника' in text.lower()):
                # Избягваме parent контейнери (> 2000 chars = вероятно wrapper)
                if len(text) < 2000 and el not in product_items:
                    product_items.append(el)

    for item in product_items:
        text = item.get_text(' ', strip=True)
        if not ('harmonica' in text.lower() or 'хармоника' in text.lower()):
            continue

        # Име на продукт — от заглавен link или heading
        product_name = None
        for tag in item.find_all(['a', 'h2', 'h3', 'h4', 'span', 'p']):
            tag_text = tag.get_text(strip=True)
            if (tag_text and len(tag_text) > 10
                    and ('harmonica' in tag_text.lower() or 'хармоника' in tag_text.lower())):
                product_name = tag_text
                break

        if not product_name:
            continue

        name_key = product_name.lower()[:40]
        if name_key in seen:
            continue

        if not is_food_product(product_name):
            continue

        # Цени — EUR и BGN
        price_eur = extract_eur_price(text)
        price_bgn = extract_bgn_price(text)

        # DM.bg може да показва цена само в лева
        if not price_bgn and not price_eur:
            # Търсим цена без валутен суфикс (напр. "3.99")
            price_match = re.search(r'(\d+)[,.](\d{2})', text)
            if price_match:
                try:
                    price = float(f"{price_match.group(1)}.{price_match.group(2)}")
                    if PRICE_RANGE_BGN[0] <= price <= PRICE_RANGE_BGN[1]:
                        price_bgn = round(price, 2)
                except ValueError:
                    pass

        price_eur, price_bgn = validate_eur_bgn(price_eur, price_bgn)
        if product_name and (price_eur or price_bgn):
            seen.add(name_key)
            products.append({
                'name': product_name,
                'eur': price_eur,
                'bgn': price_bgn,
            })

    logger.info(f"DM BS4: {len(products)} продукта извлечени")
    return products


def _extract_dm_regex(markdown_text):
    """Извлича DM продукти с regex (fallback ако BS4 не е наличен)."""
    products = []
    seen = set()

    # Pattern 1: [Product Name](url) с цени наблизо
    link_pattern = r'\[([^\]]*(?:harmonica|хармоника)[^\]]*)\]\([^\)]+\)'
    for match in re.finditer(link_pattern, markdown_text, re.IGNORECASE):
        name = match.group(1).strip()
        if name.startswith('!') or len(name) < 10:
            continue

        name_key = name.lower()[:40]
        if name_key in seen:
            continue
        if not is_food_product(name):
            continue

        idx = match.end()
        context = markdown_text[max(0, idx - 100):idx + 400]

        eur = extract_eur_price(context)
        bgn = extract_bgn_price(context)

        if eur or bgn:
            seen.add(name_key)
            products.append({"name": name, "eur": eur, "bgn": bgn})

    # Pattern 2: Просто текстови блокове с Harmonica + цени
    blocks = re.split(r'\n{2,}', markdown_text)
    for block in blocks:
        if not ('harmonica' in block.lower() or 'хармоника' in block.lower()):
            continue

        # Извличаме потенциално име (първия ред с Harmonica)
        for line in block.split('\n'):
            if 'harmonica' in line.lower() or 'хармоника' in line.lower():
                name = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'\1', line)
                name = re.sub(r'[#*_>|]', '', name).strip()
                if len(name) > 10:
                    name_key = name.lower()[:40]
                    if name_key not in seen and is_food_product(name):
                        eur = extract_eur_price(block)
                        bgn = extract_bgn_price(block)
                        if eur or bgn:
                            seen.add(name_key)
                            products.append({"name": name, "eur": eur, "bgn": bgn})
                    break

    logger.info(f"DM regex: {len(products)} продукта извлечени")
    return products


def extract_dm_from_curl_html(html_text):
    """
    Парсва DM продукти от HTML, получен чрез curl_cffi.
    Използва се когато Algolia API не е наличен, но curl_cffi bypass-ва Cloudflare.
    """
    if not html_text:
        return []
    if BS4_AVAILABLE:
        return _extract_dm_bs4(html_text)
    return []
