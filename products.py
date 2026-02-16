"""
Harmonica Price Tracker — Product List Management
===================================================
Load, update, and save the reference product list (harmonica_products.json).
"""

import json
import os
import re
from datetime import datetime

from config import EUR_BGN_RATE, PRODUCTS_JSON_PATH, logger


# Всички продукти от JSON (включително removed) — за запазване при save
_all_loaded_products = []


def load_product_list():
    """
    Зарежда референтен списък продукти от harmonica_products.json.
    Връща списък от активни продукти с name, ref_eur, ref_bgn, status.
    Запазва всички продукти (вкл. removed) в _all_loaded_products.
    Fallback: ако файлът не съществува, връща празен списък.
    """
    global _all_loaded_products

    if not os.path.exists(PRODUCTS_JSON_PATH):
        logger.warning(f"Продуктов файл не е намерен: {PRODUCTS_JSON_PATH}")
        return []

    try:
        with open(PRODUCTS_JSON_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)

        products = []
        for p in data.get("products", []):
            ref_eur = p.get("ref_eur")
            ref_bgn = p.get("ref_bgn")
            # Изчисляваме EUR от BGN ако липсва
            if not ref_eur and ref_bgn:
                ref_eur = round(ref_bgn / EUR_BGN_RATE, 2)

            products.append({
                "name": p["name"],
                "ref_eur": ref_eur,
                "ref_bgn": ref_bgn,
                "url_slug": p.get("url_slug", ""),
                "status": p.get("status", "active"),
                "active": p.get("active", True),
                "added_date": p.get("added_date", ""),
            })

        _all_loaded_products = products
        active = [p for p in products if p["active"]]
        logger.info(f"Заредени {len(active)} активни продукта от {os.path.basename(PRODUCTS_JSON_PATH)}")
        return active
    except Exception as e:
        logger.error(f"Грешка при зареждане на продуктов файл: {e}")
        return []


def update_product_list_with_new(reference_products, kashon_products):
    """
    Сравнява референтния списък (от JSON) с извлечените от Кашон продукти.
    Добавя нови продукти с status='new'. Връща обновен reference list.
    Реактивира removed продукти, ако се появят отново в Кашон.
    """
    active_names_lower = {p["name"].lower() for p in reference_products}

    # Map на removed продукти за re-activation
    removed_map = {}
    for p in _all_loaded_products:
        if not p.get("active", True) and p["name"].lower() not in active_names_lower:
            removed_map[p["name"].lower()] = p

    new_count = 0
    reactivated_count = 0

    for kp in kashon_products:
        name_lower = kp["name"].lower()
        if name_lower in active_names_lower:
            continue

        if name_lower in removed_map:
            # Реактивиране — продуктът е бил removed, но отново е на Кашон
            reactivated = removed_map[name_lower]
            reactivated["active"] = True
            reactivated["status"] = "reactivated"
            if kp.get("eur"):
                reactivated["ref_eur"] = kp["eur"]
            if kp.get("bgn"):
                reactivated["ref_bgn"] = kp["bgn"]
            reference_products.append(reactivated)
            active_names_lower.add(name_lower)
            reactivated_count += 1
        else:
            # Нов продукт
            reference_products.append({
                "name": kp["name"],
                "ref_eur": kp.get("eur"),
                "ref_bgn": kp.get("bgn"),
                "status": "new",
                "active": True,
            })
            active_names_lower.add(name_lower)
            new_count += 1

    if reactivated_count:
        logger.info(f"Реактивирани {reactivated_count} продукта (бяха removed, намерени отново в Кашон)")
    if new_count:
        logger.info(f"Открити {new_count} нови продукта от Кашон (маркирани като 'new')")

    return reference_products


def save_product_list(reference_products):
    """Записва обновения списък обратно в harmonica_products.json.
    Запазва и removed продуктите от оригиналния JSON."""
    try:
        os.makedirs(os.path.dirname(PRODUCTS_JSON_PATH), exist_ok=True)

        # Обединяваме: активни/нови от reference + removed от оригиналния JSON
        active_names = {p["name"].lower() for p in reference_products}
        removed = [p for p in _all_loaded_products
                   if not p.get("active", True) and p["name"].lower() not in active_names]
        all_products = list(reference_products) + removed

        products_data = []
        for i, p in enumerate(all_products, 1):
            ref_eur = p.get("ref_eur")
            ref_bgn = p.get("ref_bgn")
            name = p["name"]
            # Генериране на keywords от името
            words = re.findall(r'[а-яА-Яa-zA-Z]+|\d+[.,]?\d*\s*(?:г|мл|ml|g|kg|кг|л|l|%)',
                               name.lower())
            keywords = [w.strip() for w in words if len(w.strip()) > 1]

            products_data.append({
                "id": i,
                "name": name,
                "keywords": keywords,
                "ref_eur": ref_eur,
                "ref_bgn": ref_bgn,
                "url_slug": p.get("url_slug", ""),
                "active": p.get("active", True),
                "status": p.get("status", "active"),
                "added_date": p.get("added_date", datetime.now().strftime("%Y-%m-%d")),
            })

        active_count = sum(1 for p in products_data if p["active"])
        output = {
            "version": "2.0",
            "last_sync": datetime.now().strftime("%Y-%m-%d"),
            "source": "kashonharmonica.bg",
            "total_products": len(products_data),
            "products": products_data,
        }

        with open(PRODUCTS_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        logger.info(f"Продуктов файл обновен: {active_count} активни + {len(products_data) - active_count} removed")
    except Exception as e:
        logger.error(f"Грешка при запис на продуктов файл: {e}")
