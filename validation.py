"""
Harmonica Price Tracker — Claude Price Validation
===================================================
Uses Claude Sonnet to validate suspicious prices (>50% deviation from median).
"""

import json
import re
import time

from config import ANTHROPIC_AVAILABLE, ANTHROPIC_API_KEY, CLAUDE_MODEL, logger
from matching import extract_weight_grams

if ANTHROPIC_AVAILABLE:
    import anthropic


def validate_prices_with_claude(final_products, all_store_keys):
    """
    Използва Claude Sonnet за валидация на съмнителни цени.
    Открива outlier-и (>50% отклонение от медианата) и ги изпраща за оценка.
    Връща final_products с добавени полета 'flagged' и 'claude_note'.
    """
    if not ANTHROPIC_AVAILABLE or not ANTHROPIC_API_KEY:
        logger.warning("Claude валидация пропусната — липсва API ключ или anthropic модул")
        return final_products, {}

    # 1. Намираме съмнителни цени — сравняваме по EUR
    suspicious = []
    for product in final_products:
        eur_prices = {}
        for sk in ["kashon"] + list(all_store_keys):
            data = product.get(sk)
            if data and data.get("eur") and data["eur"] > 0:
                eur_prices[sk] = data["eur"]

        if len(eur_prices) < 3:
            continue

        values = sorted(eur_prices.values())
        mid = len(values) // 2
        median = (values[mid] + values[mid - 1]) / 2 if len(values) % 2 == 0 else values[mid]

        weight_g = extract_weight_grams(product["name"])

        for store, price in eur_prices.items():
            deviation = abs(price - median) / median * 100
            if deviation > 50:
                eur_per_100 = None
                if weight_g and weight_g > 0:
                    eur_per_100 = round(price / weight_g * 100, 2)
                suspicious.append({
                    "product": product["name"],
                    "store": store,
                    "price_eur": price,
                    "median_eur": round(median, 2),
                    "deviation_pct": round(deviation, 1),
                    "all_prices": {k: round(v, 2) for k, v in eur_prices.items()},
                    "weight_g": weight_g,
                    "eur_per_100g": eur_per_100,
                })

    if not suspicious:
        logger.info("Claude валидация: няма съмнителни цени (всички в ±50% от медианата)")
        return final_products, {}

    logger.info(f"Claude валидация: {len(suspicious)} съмнителни цени открити, изпращаме към Sonnet...")

    # 2. Изпращаме batch към Claude Sonnet
    price_lines = []
    for i, s in enumerate(suspicious, 1):
        prices_str = ", ".join(f"{k}={v:.2f}€" for k, v in s["all_prices"].items())
        per_100_str = ""
        if s.get("eur_per_100g") is not None:
            per_100_str = f", {s['eur_per_100g']:.2f}€/100г"
        weight_str = f" ({s['weight_g']}г)" if s.get("weight_g") else ""
        price_lines.append(
            f"{i}. Продукт: \"{s['product']}\"{weight_str}\n"
            f"   Магазин: {s['store']} → {s['price_eur']:.2f}€{per_100_str} "
            f"(медиана: {s['median_eur']:.2f}€, отклонение: {s['deviation_pct']:.0f}%)\n"
            f"   Всички цени: {prices_str}"
        )

    prompt = f"""Ти си експерт по цените на био храни и напитки в България от марката Хармоника (Harmonica).

Анализирай следните съмнителни цени (в EUR). За всяка реши:
- "ГРЕШНА" — цената е очевидно грешна (грешен match, грешно извлечена цена, цена за друг продукт или друг грамаж)
- "ВЯРНА" — цената е реална, макар и различна (промоция, по-висока цена в определен магазин)
- "СЪМНИТЕЛНА" — не можеш да прецениш със сигурност

Контекст за типични цени в EUR (1 EUR = 1.9558 BGN, фиксиран курс):
- Кисело мляко 400г: 1.28-1.79€
- Кисело мляко 2кг: 4.09-6.14€ (затова 4-5€ за 2кг е нормално!)
- Вафла 30г: 0.46-0.77€
- Сирене краве 400г: 5.11-7.67€
- Айран 500мл: 0.77-1.28€
- Масло 125г: 1.53-2.56€
- Тахан 250г: 2.56-4.09€

ВАЖНО:
- Внимавай за грамажа! Ако едни магазини продават 400г, а съмнителната цена може да е за 2кг версия — тя може да е вярна.
- Ако е показана цена/100г — ползвай я за сравнение. За масови продукти (мляко, вафли, бисквити) нормалната цена е 0.3-3€/100г. Над 5€/100г е съмнително, над 10€/100г е почти сигурно грешка.

Съмнителни цени:
{chr(10).join(price_lines)}

Отговори САМО в JSON формат (без markdown):
[
  {{"index": 1, "verdict": "ГРЕШНА|ВЯРНА|СЪМНИТЕЛНА", "reason": "кратко обяснение", "action": "remove|keep|flag"}},
  ...
]"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        start_t = time.time()
        # ~150 tokens per verdict + buffer; minimum 2000
        needed_tokens = max(2000, len(suspicious) * 150 + 500)
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=needed_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.time() - start_t
        response_text = message.content[0].text.strip()
        logger.info(f"Claude Sonnet отговори за {elapsed:.1f}s ({message.usage.input_tokens} in, "
                    f"{message.usage.output_tokens} out)")

        # Парсваме JSON
        # Отстраняваме markdown wrapper ако има
        if response_text.startswith("```"):
            response_text = re.sub(r'^```(?:json)?\s*', '', response_text)
            response_text = re.sub(r'\s*```$', '', response_text)

        try:
            verdicts = json.loads(response_text)
        except json.JSONDecodeError:
            # Truncated JSON — опитваме да спасим валидните verdict-и
            logger.warning("Claude JSON truncated — опит за частично парсване...")
            # Намираме последния пълен обект (завършващ на })
            last_brace = response_text.rfind('}')
            if last_brace > 0:
                truncated = response_text[:last_brace + 1]
                # Затваряме масива
                if not truncated.rstrip().endswith(']'):
                    truncated = truncated.rstrip().rstrip(',') + '\n]'
                try:
                    verdicts = json.loads(truncated)
                    logger.info(f"  Спасени {len(verdicts)}/{len(suspicious)} verdict-и от truncated JSON")
                except json.JSONDecodeError as e2:
                    logger.error(f"Claude JSON repair неуспешен: {e2}")
                    logger.error(f"Отговор: {response_text[:500]}")
                    return final_products, {}
            else:
                logger.error(f"Claude JSON грешка: няма валидни verdict-и")
                logger.error(f"Отговор: {response_text[:500]}")
                return final_products, {}

    except Exception as e:
        logger.error(f"Claude API грешка: {e}")
        return final_products, {}

    # 3. Прилагаме решенията
    removed_count = 0
    flagged_count = 0
    kept_count = 0
    validation_log = {}

    for verdict in verdicts:
        idx = verdict.get("index", 0) - 1
        if idx < 0 or idx >= len(suspicious):
            continue

        s = suspicious[idx]
        action = verdict.get("action", "flag")
        reason = verdict.get("reason", "")
        verdict_text = verdict.get("verdict", "?")

        log_key = f"{s['product']}|{s['store']}"
        validation_log[log_key] = {
            "verdict": verdict_text,
            "action": action,
            "reason": reason,
            "price_eur": s["price_eur"],
            "median_eur": s["median_eur"],
        }

        if action == "remove":
            # Нулираме грешната цена
            for product in final_products:
                if product["name"] == s["product"] and product.get(s["store"]):
                    product[s["store"]] = None
                    removed_count += 1
                    logger.info(f"  ✗ ПРЕМАХНАТА: {s['store']} {s['product'][:40]} "
                                f"({s['price_eur']:.2f}€) — {reason}")
                    break
        elif action == "flag":
            # Маркираме за ръчна проверка
            for product in final_products:
                if product["name"] == s["product"] and product.get(s["store"]):
                    if not product.get("_flags"):
                        product["_flags"] = []
                    product["_flags"].append(f"{s['store']}: {reason}")
                    flagged_count += 1
                    logger.info(f"  ⚠ ФЛАГ: {s['store']} {s['product'][:40]} "
                                f"({s['price_eur']:.2f}€) — {reason}")
                    break
        else:
            kept_count += 1
            logger.info(f"  ✓ OK: {s['store']} {s['product'][:40]} "
                        f"({s['price_eur']:.2f}€) — {reason}")

    logger.info(f"Claude валидация: {removed_count} премахнати, {flagged_count} флагнати, "
                f"{kept_count} потвърдени")

    return final_products, validation_log
