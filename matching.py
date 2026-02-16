"""
Harmonica Price Tracker — Product Matching Engine
===================================================
Keyword-based matching with weight normalization and scoring.
"""

import re


def normalize_name(name):
    """Разширена нормализация на имена за по-добро съпоставяне."""
    name = name.lower()
    # Премахване на бранд
    name = re.sub(r'\b(harmonica|хармоника)\b', '', name)
    name = re.sub(r'\bbio\b|\bбио\b', '', name)
    # Нормализация на тегловни единици
    name = re.sub(r'(\d+)\s*ml\b', r'\1мл', name)
    name = re.sub(r'(\d+)\s*g\b', r'\1г', name)
    # Decimal kg ПРЕДИ integer kg (иначе "1.5kg" → "1 5000г" вместо "1500г")
    name = re.sub(r'(\d+)[,.](\d+)\s*(?:кг|kg)\b',
                  lambda m: f"{int(float(f'{m.group(1)}.{m.group(2)}')*1000)}г", name)
    name = re.sub(r'(\d+)\s*kg\b', lambda m: f"{int(m.group(1))*1000}г", name)
    # Премахване на пунктуация (запазваме % и цифри)
    name = re.sub(r'[^\w\s%]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def extract_keywords(name):
    """Извлича значими ключови думи от име на продукт."""
    name = normalize_name(name)
    keywords = re.findall(r'[а-яa-z]{3,}|\d+(?:г|мл|%|л)?', name)
    return set(keywords)


def extract_weight_grams(name):
    """Извлича тегло в грамове за сравнение. '400г' → 400, '0.5кг' → 500."""
    name_lower = name.lower()
    match = re.search(r'(\d+[.,]?\d*)\s*(г|g|мл|ml|кг|kg|л|l)\b', name_lower)
    if match:
        value = float(match.group(1).replace(',', '.'))
        unit = match.group(2)
        if unit in ('кг', 'kg', 'л', 'l'):
            return int(value * 1000)
        return int(value)
    return None


def match_products(ref_products, store_products):
    """
    Съпоставяне на референтни (Кашон) продукти с магазинни продукти.

    Scoring:
    - Базов: брой общи keywords
    - Грамаж: +3 при съвпадение, HARD REJECT при >2x разлика (400г ≠ 2кг)
    - Процент: +2 при еднакъв % (напр. 3.6%), -2 при различен %
    - Минимален праг: пропорционален на размера на keyword set-а
    """
    matches = {}
    used_indices = set()

    for ref in ref_products:
        ref_keywords = extract_keywords(ref["name"])
        ref_weight = extract_weight_grams(ref["name"])
        best_match = None
        best_score = 0
        best_idx = -1

        # Динамичен минимален праг — поне 40% от keywords трябва да съвпаднат
        min_threshold = max(2, len(ref_keywords) * 4 // 10)

        for idx, store_prod in enumerate(store_products):
            if idx in used_indices:
                continue

            store_keywords = extract_keywords(store_prod["name"])
            common = ref_keywords & store_keywords

            if not common:
                continue

            score = len(common)

            # Грамаж: HARD REJECT при >2x разлика (елиминира 400г→2кг грешки)
            store_weight = extract_weight_grams(store_prod["name"])
            if ref_weight and store_weight:
                if ref_weight == store_weight:
                    score += 3
                else:
                    weight_ratio = max(ref_weight, store_weight) / min(ref_weight, store_weight)
                    if weight_ratio > 2.0:
                        continue  # Hard reject: 400г ≠ 2кг, 200г ≠ 500г
                    score -= 1  # Мек penalty за близки грамажи (напр. 380г vs 400г)

            # Процентен бонус/penalty (напр. 3,6% мастленост)
            ref_pct = re.findall(r'(\d+[.,]?\d*)\s*%', ref["name"])
            store_pct = re.findall(r'(\d+[.,]?\d*)\s*%', store_prod["name"])
            if ref_pct and store_pct:
                if ref_pct[0].replace(',', '.') == store_pct[0].replace(',', '.'):
                    score += 2
                else:
                    score -= 2  # Различен % — вероятно друг продукт (2% ≠ 3.6%)

            if score >= min_threshold and score > best_score:
                best_score = score
                best_match = store_prod
                best_idx = idx

        if best_match:
            matches[ref["name"]] = best_match
            used_indices.add(best_idx)

    return matches
