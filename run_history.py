"""
Harmonica Price Tracker — Run History & Health Monitoring
==========================================================
Записва брой продукти по магазин при всеки run.
Открива деградация: 0 продукта или >50% спад спрямо предишен run.
"""

import json
import os
from datetime import datetime

from config import STORES, GLOVO_STORES, PROJECT_ROOT, logger

HISTORY_PATH = os.path.join(PROJECT_ROOT, "data", "run_history.json")
MAX_HISTORY_ENTRIES = 50  # Пазим последните 50 run-а


def load_history():
    """Зарежда run history от JSON файл. Връща списък с записи."""
    if not os.path.exists(HISTORY_PATH):
        return []
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        # Legacy format: {"runs": [...]}
        return data.get("runs", [])
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Run history файлът е повреден, започваме наново: {e}")
        return []


def save_history(history):
    """Записва run history в JSON файл."""
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    # Пазим само последните MAX_HISTORY_ENTRIES
    trimmed = history[-MAX_HISTORY_ENTRIES:]
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)


def build_run_entry(store_counts, total_ref, total_time):
    """
    Създава запис за текущия run.

    Args:
        store_counts: dict {store_key: matched_count} — включва всички магазини
        total_ref: int — общ брой референтни продукти
        total_time: float — общо време за run в секунди

    Returns:
        dict с дата, общ брой, време и counts по магазин
    """
    entry = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_ref": total_ref,
        "total_time": round(total_time, 1),
        "stores": {},
    }
    for store_key in store_counts:
        entry["stores"][store_key] = store_counts[store_key]
    return entry


def check_health(current_entry, history):
    """
    Сравнява текущия run с предишния и генерира alerts.

    Args:
        current_entry: dict — текущ run entry (от build_run_entry)
        history: list — пълна история (без текущия run)

    Returns:
        list of dicts: [{"store": key, "type": "zero"|"drop", "current": N, "previous": N, "drop_pct": N}]
    """
    alerts = []
    current_stores = current_entry.get("stores", {})

    # Намираме предишния run (последния в history)
    previous = history[-1] if history else None
    previous_stores = previous.get("stores", {}) if previous else {}

    # Всички магазини (без master/kashon — той е reference source)
    all_store_keys = set()
    for key, cfg in STORES.items():
        if not cfg.get("is_master"):
            all_store_keys.add(key)
    for key in GLOVO_STORES:
        all_store_keys.add(key)

    for store_key in sorted(all_store_keys):
        current_count = current_stores.get(store_key, 0)
        prev_count = previous_stores.get(store_key, 0) if previous else None

        # Alert 1: 0 продукта от магазин, който преди е имал
        if current_count == 0:
            alerts.append({
                "store": store_key,
                "type": "zero",
                "current": current_count,
                "previous": prev_count,
            })
            continue

        # Alert 2: >50% спад спрямо предишен run
        if prev_count is not None and prev_count > 0:
            drop_pct = ((prev_count - current_count) / prev_count) * 100
            if drop_pct > 50:
                alerts.append({
                    "store": store_key,
                    "type": "drop",
                    "current": current_count,
                    "previous": prev_count,
                    "drop_pct": round(drop_pct, 1),
                })

    return alerts


def get_store_display_name(store_key):
    """Връща display name за магазин."""
    if store_key in STORES:
        return STORES[store_key]["name"]
    if store_key in GLOVO_STORES:
        return f"Glovo {GLOVO_STORES[store_key]['name']}"
    return store_key


def format_health_summary(alerts, current_entry):
    """
    Форматира health summary за логване.

    Returns:
        str — multi-line summary
    """
    lines = []
    current_stores = current_entry.get("stores", {})

    if not alerts:
        total_stores = len([k for k, v in current_stores.items() if v > 0])
        lines.append(f"Health OK — {total_stores} магазина с продукти, без аномалии")
        return "\n".join(lines)

    lines.append(f"HEALTH ALERTS — {len(alerts)} проблема:")
    for alert in alerts:
        name = get_store_display_name(alert["store"])
        if alert["type"] == "zero":
            prev = alert.get("previous")
            if prev and prev > 0:
                lines.append(f"  ⚠ {name}: 0 продукта (предишен run: {prev})")
            else:
                lines.append(f"  ⚠ {name}: 0 продукта")
        elif alert["type"] == "drop":
            lines.append(
                f"  ⚠ {name}: {alert['current']} продукта "
                f"(спад {alert['drop_pct']}% от {alert['previous']})"
            )
    return "\n".join(lines)


def record_run(store_counts, total_ref, total_time):
    """
    Главна функция: записва run, проверява health, връща alerts.

    Args:
        store_counts: dict {store_key: matched_count}
        total_ref: int
        total_time: float

    Returns:
        tuple: (alerts_list, health_summary_str)
    """
    history = load_history()
    entry = build_run_entry(store_counts, total_ref, total_time)
    alerts = check_health(entry, history)

    # Записваме текущия run
    history.append(entry)
    save_history(history)

    summary = format_health_summary(alerts, entry)
    return alerts, summary
