"""
Harmonica Price Tracker — Price History
=========================================
Records price snapshots per run for trend analysis.
Local JSON storage + Google Sheets История_{year} tab.
"""

import json
import os
from datetime import datetime

from config import STORES, GLOVO_STORES, logger

HISTORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
HISTORY_PATH = os.path.join(HISTORY_DIR, "price_history.json")

# Максимум записи в JSON файла (52 седмици × ~88 продукта = ~4500 на година)
MAX_ENTRIES = 6000


def load_history():
    """Зарежда ценова история от JSON."""
    if not os.path.exists(HISTORY_PATH):
        return []
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        logger.warning("price_history.json повреден — започваме наново")
        return []


def save_history(entries):
    """Записва ценова история, ограничена до MAX_ENTRIES."""
    if len(entries) > MAX_ENTRIES:
        entries = entries[-MAX_ENTRIES:]
    os.makedirs(HISTORY_DIR, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False)


def record_prices(final_products):
    """
    Записва ценови snapshot от текущия run.
    Добавя по един запис за всеки продукт с цени от всички магазини.
    Връща броя записани продукти.
    """
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    store_keys = [k for k, cfg in STORES.items() if not cfg.get("is_master")]
    store_keys += list(GLOVO_STORES.keys())

    entries = load_history()
    count = 0

    for p in final_products:
        name = p["name"]
        kashon = p.get("kashon") or {}

        prices = {}
        if kashon.get("eur"):
            prices["kashon"] = kashon["eur"]
        for sk in store_keys:
            sd = p.get(sk)
            if sd and sd.get("eur"):
                prices[sk] = sd["eur"]

        if not prices:
            continue

        entries.append({
            "date": date_str,
            "time": time_str,
            "product": name,
            "prices": prices,
        })
        count += 1

    save_history(entries)
    logger.info(f"Price history: {count} продукта записани ({len(entries)} общо записи)")
    return count


def get_price_trend(product_name, last_n_weeks=4):
    """
    Връща ценовия тренд за продукт от последните N седмици.
    Връща list от {date, avg_eur} сортиран по дата.
    """
    entries = load_history()
    product_entries = [e for e in entries if e["product"] == product_name]

    if not product_entries:
        return []

    # Групираме по дата
    by_date = {}
    for e in product_entries:
        d = e["date"]
        prices = list(e["prices"].values())
        if prices:
            by_date[d] = round(sum(prices) / len(prices), 2)

    # Сортираме и взимаме последните N
    sorted_dates = sorted(by_date.items(), key=lambda x: x[0])
    return [{"date": d, "avg_eur": p} for d, p in sorted_dates[-last_n_weeks:]]
