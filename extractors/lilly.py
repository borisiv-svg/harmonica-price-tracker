"""
Lilly Drogerie (lillydrogerie.bg) product extractor.

Extracts Harmonica products from Lilly Drogerie brand page.
Uses BeautifulSoup + HTML for stable parsing, with regex + markdown fallback.
"""

import json
import re

from config import EUR_BGN_RATE, logger, BS4_AVAILABLE
if BS4_AVAILABLE:
    from config import BeautifulSoup

from utils import (
    extract_eur_price,
    extract_bgn_price,
    validate_eur_bgn,
    is_food_product,
)


def extract_lilly_products(markdown_text, html_text=None):
    """
    Извлича Harmonica продукти от Lilly Drogerie brand page.

    Предпочита BeautifulSoup + HTML за по-стабилно парсване.
    Ако BS4 не е наличен или HTML липсва, използва regex + markdown.

    Връща list of dicts с допълнително поле 'in_stock' (bool).
    """
    products = []
    if BS4_AVAILABLE and html_text:
        products = _extract_lilly_bs4(html_text)
    if not products:
        products = _extract_lilly_regex(markdown_text)
    if not products:
        # Допълнителен debug: какво съдържа HTML-а
        html_preview = ""
        if html_text:
            soup = BeautifulSoup(html_text, 'html.parser') if BS4_AVAILABLE else None
            if soup:
                # Проверяваме за Harmonica ключова дума в HTML
                harmonica_count = html_text.upper().count('HARMONICA')
                # Проверяваме за типични Magento product selectors
                selectors = ['.product-item', '.product-items', 'ol.products',
                             '.products-grid', '.category-products', '[data-role=product]']
                found_selectors = [s for s in selectors if soup.select_one(s)]
                html_preview = (f"harmonica_refs={harmonica_count}, "
                               f"selectors={found_selectors or 'NONE'}, "
                               f"title={soup.title.string if soup.title else 'N/A'}")
        logger.warning(f"Lilly: 0 продукта, markdown len={len(markdown_text)}, "
                       f"html len={len(html_text) if html_text else 0}, "
                       f"{html_preview}")
    return products


def _find_product_container(element, max_levels=6):
    """
    Вървим нагоре от element до намерим контейнер с цена.
    Връща контейнер или None.
    """
    current = element
    for _ in range(max_levels):
        parent = current.parent
        if not parent or parent.name in ('body', 'html', '[document]'):
            break
        if parent.name in ('header', 'footer', 'nav', 'head'):
            return None

        text = parent.get_text(' ', strip=True)
        if len(text) > 3000:
            cur_text = current.get_text(' ', strip=True)
            return current if re.search(r'\d+[.,]\d{2}', cur_text) else None

        if re.search(r'\d+[.,]\d{2}', text):
            if len(text) < 500:
                current = parent
                continue
            return parent

        current = parent

    if current and current.name not in ('body', 'html', '[document]'):
        text = current.get_text(' ', strip=True)
        if re.search(r'\d+[.,]\d{2}', text) and len(text) < 3000:
            return current
    return None


def _extract_lilly_bs4(html_text):
    """
    Извлича Lilly продукти с BeautifulSoup.

    Lilly използва Hyvä Theme (Alpine.js + Tailwind CSS) —
    стандартните Magento CSS selectors не съществуват.

    Стратегии:
    1. JSON-LD structured data (@type: Product / ItemList)
    2. Елементи с HARMONICA в text, title, alt атрибути
    3. Legacy Magento CSS selectors (fallback)
    """
    products = []
    seen = set()
    soup = BeautifulSoup(html_text, 'html.parser')

    # Стратегия 1: JSON-LD structured data
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string or '')
            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                if data.get('@type') == 'ItemList':
                    items = data.get('itemListElement', [])
                elif data.get('@type') == 'Product':
                    items = [data]
                elif 'itemListElement' in data:
                    items = data['itemListElement']

            for item in items:
                product = item.get('item', item) if isinstance(item, dict) else {}
                name = product.get('name', '')
                if not name:
                    continue

                price = None
                offers = product.get('offers', {})
                if isinstance(offers, dict):
                    price = offers.get('price')
                elif isinstance(offers, list) and offers:
                    price = offers[0].get('price')

                if price:
                    price_bgn = round(float(price), 2)
                    price_eur = round(price_bgn / EUR_BGN_RATE, 2)
                    price_eur, price_bgn = validate_eur_bgn(price_eur, price_bgn)
                    name_key = name.lower()[:40]
                    if name_key not in seen:
                        seen.add(name_key)
                        in_stock = True
                        if isinstance(offers, dict):
                            avail = offers.get('availability', '')
                            in_stock = 'OutOfStock' not in avail
                        products.append({
                            'name': name,
                            'eur': price_eur,
                            'bgn': price_bgn,
                            'in_stock': in_stock,
                        })
        except (json.JSONDecodeError, ValueError, TypeError):
            continue

    if products:
        logger.info(f"Lilly BS4: {len(products)} продукта от JSON-LD")
        return products

    # Стратегия 2: Намиране на product containers
    product_containers = []
    found_container_ids = set()

    # 2a: <a> tags с HARMONICA в text content
    for link in soup.find_all('a', href=True):
        link_text = link.get_text(strip=True)
        href = link.get('href', '')
        if not link_text or 'harmonica' not in link_text.lower():
            continue
        if len(link_text) < 5:
            continue
        if any(x in href.lower() for x in ['/media/', '.jpg', '.png', '.svg', '.css', '.js']):
            continue
        container = _find_product_container(link)
        if container:
            cid = id(container)
            if cid not in found_container_ids:
                found_container_ids.add(cid)
                product_containers.append(container)

    # 2b: <a> и <img> с HARMONICA в title/alt атрибути
    for attr_name in ['title', 'alt']:
        for el in soup.find_all(attrs={attr_name: re.compile(r'harmonica', re.IGNORECASE)}):
            if el.find_parent(['header', 'nav', 'footer', 'head']):
                continue
            container = _find_product_container(el)
            if container:
                cid = id(container)
                if cid not in found_container_ids:
                    found_container_ids.add(cid)
                    product_containers.append(container)

    # 2c: Text nodes с HARMONICA (за Hyvä span/div)
    for text_node in soup.find_all(string=re.compile(r'harmonica', re.IGNORECASE)):
        parent = text_node.find_parent()
        if not parent:
            continue
        if parent.name in ('script', 'style', 'meta', 'title', 'head', 'noscript'):
            continue
        if parent.find_parent(['header', 'nav', 'footer', 'head']):
            continue
        container = _find_product_container(parent)
        if container:
            cid = id(container)
            if cid not in found_container_ids:
                found_container_ids.add(cid)
                product_containers.append(container)

    logger.info(f"Lilly BS4: {len(product_containers)} потенциални контейнери")

    for container in product_containers:
        text = container.get_text(' ', strip=True)

        product_name = None

        # Опит 1: <a> с HARMONICA text content
        for link in container.find_all('a', href=True):
            lt = link.get_text(strip=True)
            href = link.get('href', '')
            if lt and 'harmonica' in lt.lower() and len(lt) > 10:
                if not any(x in href.lower() for x in ['/media/', '.jpg', '.png', '.svg']):
                    product_name = lt
                    break

        # Опит 2: <a title> с HARMONICA
        if not product_name:
            for link in container.find_all('a', attrs={'title': True}):
                title = link.get('title', '')
                if 'harmonica' in title.lower() and len(title) > 10:
                    product_name = title
                    break

        # Опит 3: <img alt> с HARMONICA
        if not product_name:
            for img in container.find_all('img', attrs={'alt': True}):
                alt = img.get('alt', '')
                if 'harmonica' in alt.lower() and len(alt) > 10:
                    product_name = alt
                    break

        # Опит 4: <span>, <div>, <h2-h5>, <strong>, <p> с HARMONICA
        if not product_name:
            for tag in container.find_all(['h2', 'h3', 'h4', 'h5', 'span', 'strong', 'p', 'div']):
                tag_text = tag.get_text(strip=True)
                if tag_text and 'harmonica' in tag_text.lower() and 10 < len(tag_text) < 200:
                    if is_food_product(tag_text):
                        product_name = tag_text
                        break

        if not product_name:
            continue

        if any(x in product_name.lower() for x in ['навигация', 'меню', 'cookie', 'продукти на']):
            continue

        name_key = product_name.lower()[:40]
        if name_key in seen:
            continue

        # Цени
        price_bgn = extract_bgn_price(text)
        price_eur = extract_eur_price(text)

        if not price_bgn and not price_eur:
            price_match = re.search(r'(\d+)[,.](\d{2})', text)
            if price_match:
                try:
                    price = float(f"{price_match.group(1)}.{price_match.group(2)}")
                    if 0.50 <= price <= 100:
                        price_bgn = round(price, 2)
                except ValueError:
                    pass

        if price_bgn and not price_eur:
            price_eur = round(price_bgn / EUR_BGN_RATE, 2)

        in_stock = 'изчерпан' not in text.lower()

        if product_name and (price_eur or price_bgn):
            seen.add(name_key)
            products.append({
                'name': product_name,
                'eur': price_eur,
                'bgn': price_bgn,
                'in_stock': in_stock,
            })

    # Стратегия 3: Legacy Magento CSS selectors
    if not products:
        product_items = soup.select(
            '.product-item, .product-item-info, li.item.product, '
            '.products-grid .item, .category-products .item'
        )
        for item in product_items:
            text = item.get_text(' ', strip=True)
            if 'harmonica' not in text.lower():
                continue
            for link in item.find_all('a', href=True):
                lt = link.get_text(strip=True)
                if lt and 'harmonica' in lt.lower() and len(lt) > 5:
                    name_key = lt.lower()[:40]
                    if name_key not in seen:
                        price_bgn = extract_bgn_price(text)
                        price_eur = extract_eur_price(text)
                        if price_bgn or price_eur:
                            seen.add(name_key)
                            products.append({
                                'name': lt,
                                'eur': price_eur,
                                'bgn': price_bgn,
                                'in_stock': 'изчерпан' not in text.lower(),
                            })
                    break

    logger.info(f"Lilly BS4: {len(products)} продукта извлечени")
    return products


def _extract_lilly_regex(markdown_text):
    """Извлича Lilly продукти с regex (fallback)."""
    products = []
    product_blocks = re.split(r'\n\s*\*\s+', markdown_text)

    for block in product_blocks:
        if 'lillydrogerie.bg' not in block:
            continue

        name_match = re.search(
            r'(?<!!)\[([^\]]*HARMONICA[^\]]*)\]\(https://lillydrogerie\.bg/(?!media/)([^\s\)]+)',
            block
        )
        if not name_match:
            continue

        product_name = name_match.group(1).strip()
        product_slug = name_match.group(2).strip('" ')
        product_url = f"https://lillydrogerie.bg/{product_slug}"

        eur_match = re.search(r'(\d+[.,]\d{2})\s*€', block)
        price_eur = float(eur_match.group(1).replace(',', '.')) if eur_match else None

        bgn_match = re.search(r'(\d+[.,]\d{2})\s*лв', block)
        price_bgn = float(bgn_match.group(1).replace(',', '.')) if bgn_match else None

        in_stock = 'Изчерпан' not in block

        if product_name and (price_eur or price_bgn):
            products.append({
                'name': product_name,
                'eur': price_eur,
                'bgn': price_bgn,
                'in_stock': in_stock,
                'url': product_url,
            })

    logger.info(f"Lilly regex: {len(products)} продукта извлечени")
    return products
