"""
Generic (universal fallback) product extractor.

Universal fallback extractor that works with any markdown format.
Used for new stores that don't have a dedicated extractor.
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


def _normalize_image_links(markdown):
    """
    Нормализира [![alt](img)](url) → [alt](url).
    Тази комбинация (image-wrapped-in-link) объркваше link regex-а
    и създаваше дубликати с '![' в имената.
    """
    return re.sub(
        r'\[!\[([^\]]+)\]\([^\)]+\)\]\(([^\)]+)\)',
        r'[\1](\2)',
        markdown,
    )


def _extract_generic_products(markdown, brand_page=False):
    """
    Универсален fallback extractor. Работи с всякакъв markdown.

    Стратегия:
    1. Разделя markdown на блокове (двоен нов ред)
    2. Търси блокове с BGN цена (X,XX лв)
    3. Извлича най-подходящия текст като име на продукт
    4. Ако brand_page=True, не проверява за "harmonica" в името
    5. Винаги пробва и двата подхода, взима по-добрия резултат
    """
    markdown = _normalize_image_links(markdown)
    block_products = _extract_generic_block_based(markdown, brand_page)
    line_products = _extract_generic_line_by_line(markdown, brand_page)

    # Взимаме подхода с повече продукти
    if len(line_products) > len(block_products):
        return line_products
    return block_products


def _extract_generic_block_based(markdown, brand_page=False):
    """Block-based extraction: разделя по двоен нов ред."""
    products = []
    seen = set()

    blocks = re.split(r'\n{2,}', markdown)

    for block in blocks:
        if not brand_page and not is_harmonica_product(block):
            continue

        bgn = extract_bgn_price(block)
        eur = extract_eur_price(block)
        if not bgn and not eur:
            bgn = extract_price_fallback(block)
        if not bgn and not eur:
            continue

        if bgn and not eur:
            eur = round(bgn / EUR_BGN_RATE, 2)

        name = None

        link_match = re.search(r'(?<!!)\[([^\]]{5,100})\]\([^\)]+\)', block)
        if link_match:
            candidate = link_match.group(1).strip()
            if len(candidate) > 5 and is_food_product(candidate):
                name = candidate

        if not name:
            heading_match = re.search(r'#+\s*(.{5,80})', block)
            if heading_match:
                candidate = heading_match.group(1).strip()
                if is_food_product(candidate):
                    name = candidate

        if not name:
            # Image alt текст: ![Продукт 400g](img.jpg) — clean_product_name го изтрива
            img_match = re.search(r'!\[([^\]]{8,120})\]\([^\)]+\)', block)
            if img_match:
                candidate = img_match.group(1).strip()
                if is_food_product(candidate):
                    name = candidate

        if not name:
            for line in block.split('\n'):
                line = clean_product_name(line)
                if (len(line) > 10 and
                        len(re.findall(r'[а-яА-Яa-zA-Z]', line)) >= 3 and
                        is_food_product(line)):
                    name = line
                    break

        if not name:
            continue
        if deduplicate_check(name, seen):
            continue

        products.append({"name": name, "eur": eur, "bgn": bgn})

    return products


def _extract_generic_line_by_line(markdown, brand_page=False):
    """Line-by-line extraction: сканира ред по ред (за сайтове без двойни нови редове)."""
    products = []
    seen = set()
    lines = markdown.split('\n')

    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if not line_stripped or len(line_stripped) < 5:
            continue

        name = None

        # Опит 1: Link текст
        link_match = re.search(r'(?<!!)\[([^\]]{5,120})\]\(([^\)]+)\)', line_stripped)
        if link_match:
            candidate = link_match.group(1).strip()
            if is_food_product(candidate) and len(candidate) >= 8:
                name = candidate
        else:
            # Опит 2: Текстов ред с грамаж (признак за продукт)
            if re.search(r'\d+\s*(?:г|мл|ml|g|kg|кг|л)\b', line_stripped, re.IGNORECASE):
                candidate = clean_product_name(line_stripped)
                if is_food_product(candidate) and 8 <= len(candidate) <= 150:
                    name = candidate

        if not name:
            # Опит 3: Image alt текст (![Продукт 400g](img.jpg))
            # clean_product_name() изтрива image alt, затова го извличаме директно
            img_match = re.search(r'!\[([^\]]{8,120})\]\([^\)]+\)', line_stripped)
            if img_match:
                candidate = img_match.group(1).strip()
                if is_food_product(candidate):
                    name = candidate

        if not name and brand_page:
            # Опит 4 (само за brand pages): plain text с food keywords
            # На brand pages имената може да са без линкове и без грамаж
            candidate = clean_product_name(line_stripped)
            if (10 <= len(candidate) <= 150 and
                    len(re.findall(r'[а-яА-Яa-zA-Z]', candidate)) >= 5 and
                    is_food_product(candidate) and
                    not re.match(r'^[\d\s,.€лв]+$', candidate)):  # не е чисто цена
                name = candidate

        if not name:
            continue

        # Проверка за harmonica (освен при brand_page)
        if not brand_page:
            if not is_harmonica_product(name):
                context_lines = '\n'.join(lines[max(0, i - 5):i + 5])
                if not is_harmonica_product(context_lines):
                    continue

        if deduplicate_check(name, seen):
            continue

        # Търсим цена НАПРЕД от името (тесен прозорец: 3 реда), после разширяваме (5).
        # По-тесен контекст намалява risk от price bleed между съседни продукти.
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
