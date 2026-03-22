"""
Harmonica Price Tracker — Google Sheets Writer
================================================
Writes product data and formatting to Google Sheets.
"""

import os
import re
from datetime import datetime

from config import GSPREAD_AVAILABLE, STORES, GLOVO_STORES, EUR_BGN_RATE, logger

if GSPREAD_AVAILABLE:
    import gspread

from utils import categorize_product


# =============================================================================
# GOOGLE SHEETS WRITER — универсален, с in_stock сиво форматиране
# =============================================================================

def extract_weight(name):
    """Извлича грамаж от име на продукт. Напр. 'Био вафли 40г' → '40г', '1.7 kg' → '1.7kg'"""
    match = re.search(r'(\d+[.,]?\d*)\s*(г|мл|ml|g|kg|кг|л|l)\b', name, re.IGNORECASE)
    if match:
        return f"{match.group(1)}{match.group(2)}"
    return ""


def write_to_sheets(final_products, stats):
    """
    Записва данните в Google Sheets.
    Формат: № | Продукт | Грамаж | Кашон EUR | Кашон BGN(лв) | Store1 EUR | ... | Ср.EUR | Статус
    Всички цени са в EUR. Кашон BGN е чисто информативна колона (левова равностойност).
    """
    if not GSPREAD_AVAILABLE:
        logger.warning("gspread not available — skipping Sheets write")
        return False

    SPREADSHEET_NAME = "Harmonica Price Tracker"
    BASE_TAB = "Ценови Тракер"
    tab_suffix = os.environ.get("SHEET_TAB_SUFFIX", "")
    tab_name = f"{BASE_TAB}{tab_suffix}"

    # Магазини без Кашон (те показват само EUR) + Glovo магазини
    store_columns = [key for key, cfg in STORES.items() if not cfg.get("is_master")]
    store_columns += list(GLOVO_STORES.keys())
    store_display_names = {key: cfg["name"] for key, cfg in STORES.items()}
    store_display_names.update({k: f"Glovo {cfg['name']}" for k, cfg in GLOVO_STORES.items()})

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    logger.info(f"Google Sheets: записване в '{tab_name}'")
    logger.info(f"Магазини: Кашон + {', '.join(store_display_names[s] for s in store_columns)}")

    try:
        creds_json = os.environ.get("GOOGLE_CREDENTIALS")
        if creds_json:
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                f.write(creds_json)
                creds_path = f.name
            gc = gspread.service_account(filename=creds_path)
            os.unlink(creds_path)
        else:
            gc = gspread.service_account(filename='credentials.json')

        spreadsheet_id = os.environ.get("SPREADSHEET_ID")
        if spreadsheet_id:
            spreadsheet = gc.open_by_key(spreadsheet_id)
        else:
            spreadsheet = gc.open(SPREADSHEET_NAME)

        try:
            sheet = spreadsheet.worksheet(tab_name)
        except gspread.exceptions.WorksheetNotFound:
            sheet = spreadsheet.add_worksheet(title=tab_name, rows=200, cols=26)
            logger.info(f"Създаден нов таб: {tab_name}")

        logger.info(f"Свързан с '{tab_name}'")

    except Exception as e:
        logger.error(f"Google Sheets връзка неуспешна: {e}")
        return False

    # --- Изграждане на данните ---
    # Колони: №(0) | Продукт(1) | Грамаж(2) | Кашон EUR(3) | Кашон BGN(лв)(4) | Store1(5) | ... | Ср.EUR | Статус | Откл.%
    HEADER_ROW = 4           # 1-indexed sheet row (0-indexed: 3)
    KASHON_EUR_COL = 3       # Кашон EUR (основна)
    KASHON_BGN_COL = 4       # Кашон BGN (информативна)
    STORE_COL_START = 5      # Първи external store

    headers = ['№', 'Продукт', 'Грамаж', 'Кашон EUR', 'Кашон BGN(лв)']
    for store_key in store_columns:
        headers.append(store_display_names[store_key])
    headers.extend(['Ср.Маг.EUR', 'Статус', 'Откл.%'])

    DEVIATION_COL = len(headers) - 1  # Последната колона

    all_data = []

    all_data.append([f'HARMONICA - Ценови Тракер v10.14'] + [''] * (len(headers) - 1))

    meta = [f'Актуализация: {now}', '', f'Курс: 1 EUR = {EUR_BGN_RATE} BGN', '',
            f'Магазини: {len(STORES) + len(GLOVO_STORES)}']
    meta.extend([''] * (len(headers) - len(meta)))
    all_data.append(meta)

    all_data.append([''] * len(headers))
    all_data.append(headers)

    # --- Сортиране по категории ---
    sorted_products = sorted(final_products, key=lambda p: categorize_product(p["name"]))

    out_of_stock_cells = []
    deviation_cells_high = []   # (row, col) — цена >10% над средната
    deviation_cells_low = []    # (row, col) — цена >10% под средната
    category_separator_rows = []  # row indices за форматиране на разделителите
    new_product_rows = []         # row indices за нови продукти (зелен фон)
    removed_product_rows = []     # row indices за отпаднали продукти (жълт фон)

    current_category = None
    product_num = 0

    for product in sorted_products:
        cat_idx, cat_name = categorize_product(product["name"])

        # Добавяме разделител при нова категория
        if cat_name != current_category:
            current_category = cat_name
            separator_row = [cat_name] + [''] * (len(headers) - 1)
            all_data.append(separator_row)
            category_separator_rows.append(len(all_data) - 1)  # 0-indexed

        product_num += 1

        # Проследяване на статус за цветово кодиране
        product_status = product.get("status", "active")
        row_0idx_status = len(all_data)  # текущ row index за цветово маркиране
        if product_status == "new":
            new_product_rows.append(row_0idx_status)
        elif product_status == "removed":
            removed_product_rows.append(row_0idx_status)

        kashon = product.get("kashon") or {}
        kashon_bgn = kashon.get("bgn")
        kashon_eur = kashon.get("eur")

        # Ако имаме EUR но нямаме BGN — изчисляваме BGN от EUR × курс
        if kashon_eur and not kashon_bgn:
            kashon_bgn = round(kashon_eur * EUR_BGN_RATE, 2)
        # Ако имаме BGN но нямаме EUR — изчисляваме EUR от BGN / курс
        elif kashon_bgn and not kashon_eur:
            kashon_eur = round(kashon_bgn / EUR_BGN_RATE, 2)

        row = [
            product_num,
            product["name"],
            extract_weight(product["name"]),
            kashon_eur if kashon_eur else '',
            kashon_bgn if kashon_bgn else '',
        ]

        # Събираме EUR цени от external stores за средната
        # (Кашон е reference/производствена цена — не участва в средната на магазините)
        all_prices_eur = []

        store_prices_info = []  # [(col_index, price_eur)] за deviation check

        # 0-indexed sheet row за текущия продукт
        row_0idx = len(all_data)

        for col_offset, store_key in enumerate(store_columns):
            store_data = product.get(store_key)
            col_index = STORE_COL_START + col_offset

            if store_data:
                price_eur = store_data.get("eur")
                row.append(price_eur if price_eur else '')

                if price_eur:
                    all_prices_eur.append(price_eur)
                    store_prices_info.append((col_index, price_eur))

                if not store_data.get("in_stock", True):
                    out_of_stock_cells.append((row_0idx, col_index))
            else:
                row.append('')

        # Средна EUR (от external магазини, без Кашон)
        if all_prices_eur:
            avg_eur = round(sum(all_prices_eur) / len(all_prices_eur), 2)
            row.append(avg_eur)
        else:
            avg_eur = None
            row.append('')

        # Статус: в колко магазина е намерен
        matched_count = sum(1 for s in store_columns if product.get(s))
        row.append(f"{matched_count}/{len(store_columns)}")

        # Откл.%: максимално процентно отклонение от средната в този ред
        max_deviation_pct = None
        if avg_eur and len(all_prices_eur) >= 2:
            threshold_high = avg_eur * 1.10
            threshold_low = avg_eur * 0.90

            all_deviations = []

            # Проверяваме Кашон EUR (col 3 — KASHON_EUR_COL)
            if kashon_eur:
                dev_pct = ((kashon_eur - avg_eur) / avg_eur) * 100
                all_deviations.append(dev_pct)
                if kashon_eur > threshold_high:
                    deviation_cells_high.append((row_0idx, KASHON_EUR_COL))
                elif kashon_eur < threshold_low:
                    deviation_cells_low.append((row_0idx, KASHON_EUR_COL))

            # Проверяваме external магазини
            for col_idx, price in store_prices_info:
                dev_pct = ((price - avg_eur) / avg_eur) * 100
                all_deviations.append(dev_pct)
                if price > threshold_high:
                    deviation_cells_high.append((row_0idx, col_idx))
                elif price < threshold_low:
                    deviation_cells_low.append((row_0idx, col_idx))

            # Намираме макс. отклонение по абсолютна стойност
            if all_deviations:
                max_dev = max(all_deviations, key=abs)
                max_deviation_pct = round(max_dev, 1)

        if max_deviation_pct is not None:
            # Записваме като число (напр. 10.5 за +10.5%) — форматирането е в Sheets
            row.append(max_deviation_pct)
        else:
            row.append('')

        all_data.append(row)

    # НЕ добавяме стрелки (↑/↓) в клетките — те превръщат числата в текст
    # и разбиват числовото форматиране (#,##0.00) и подравняването.
    # Вместо това разчитаме на цветовото форматиране (червено/синьо) за индикация.

    try:
        sheet.clear()
        sheet.update(values=all_data, range_name='A1')
        logger.info(f"Записани {len(all_data)} реда × {len(headers)} колони")
    except Exception as e:
        logger.error(f"Грешка при запис: {e}")
        return False

    # --- Форматиране ---
    try:
        last_row = len(all_data)
        last_col = len(headers)

        # Разлепяме всички merge-нати клетки от предишен run в ОТДЕЛНА заявка.
        # Използваме пълния размер на sheet-а, за да покрием merges от runs
        # с различен брой колони. Ако няма merges — просто no-op.
        try:
            sheet.spreadsheet.batch_update({"requests": [{
                "unmergeCells": {
                    "range": {"sheetId": sheet.id,
                              "startRowIndex": 0, "endRowIndex": sheet.row_count,
                              "startColumnIndex": 0, "endColumnIndex": sheet.col_count}
                }
            }]})
        except Exception:
            pass  # Няма merge-нати клетки или друга грешка — продължаваме

        format_requests = []

        # Заглавен ред
        format_requests.append({
            "repeatCell": {
                "range": {"sheetId": sheet.id,
                          "startRowIndex": 0, "endRowIndex": 1,
                          "startColumnIndex": 0, "endColumnIndex": last_col},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": {"red": 0.13, "green": 0.35, "blue": 0.22},
                    "textFormat": {"bold": True, "fontSize": 14,
                                   "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                    "horizontalAlignment": "CENTER"
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"
            }
        })

        format_requests.append({
            "mergeCells": {
                "range": {"sheetId": sheet.id,
                          "startRowIndex": 0, "endRowIndex": 1,
                          "startColumnIndex": 0, "endColumnIndex": last_col},
                "mergeType": "MERGE_ALL"
            }
        })

        # Метаданни
        format_requests.append({
            "repeatCell": {
                "range": {"sheetId": sheet.id,
                          "startRowIndex": 1, "endRowIndex": 2,
                          "startColumnIndex": 0, "endColumnIndex": last_col},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": {"red": 0.92, "green": 0.97, "blue": 0.92},
                    "textFormat": {"italic": True, "fontSize": 10}
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat)"
            }
        })

        # Header
        format_requests.append({
            "repeatCell": {
                "range": {"sheetId": sheet.id,
                          "startRowIndex": HEADER_ROW - 1, "endRowIndex": HEADER_ROW,
                          "startColumnIndex": 0, "endColumnIndex": last_col},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": {"red": 0.85, "green": 0.92, "blue": 0.85},
                    "textFormat": {"bold": True, "fontSize": 10},
                    "horizontalAlignment": "CENTER"
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"
            }
        })

        # Ресет: бял фон + черен текст за всички data клетки (изчистваме остатъци)
        if last_row > HEADER_ROW:
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id,
                              "startRowIndex": HEADER_ROW, "endRowIndex": last_row,
                              "startColumnIndex": 0, "endColumnIndex": last_col},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": {"red": 1, "green": 1, "blue": 1},
                        "textFormat": {
                            "foregroundColor": {"red": 0, "green": 0, "blue": 0},
                            "bold": False, "italic": False, "fontSize": 10,
                        }
                    }},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)"
                }
            })

        # Категорийни разделители — тъмнозелен фон с бял bold текст
        for sep_row_idx in category_separator_rows:
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id,
                              "startRowIndex": sep_row_idx, "endRowIndex": sep_row_idx + 1,
                              "startColumnIndex": 0, "endColumnIndex": last_col},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": {"red": 0.18, "green": 0.49, "blue": 0.20},
                        "textFormat": {"bold": True, "fontSize": 10,
                                       "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                    }},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)"
                }
            })
            # Merge-ваме категорийния ред за по-чист вид
            format_requests.append({
                "mergeCells": {
                    "range": {"sheetId": sheet.id,
                              "startRowIndex": sep_row_idx, "endRowIndex": sep_row_idx + 1,
                              "startColumnIndex": 0, "endColumnIndex": last_col},
                    "mergeType": "MERGE_ALL"
                }
            })

        # Ширини
        col_widths = {0: 35, 1: 250, 2: 55, 3: 80, 4: 80}  # №, Продукт, Грамаж, Кашон EUR, Кашон BGN(лв)
        for offset in range(len(store_columns)):
            col_widths[STORE_COL_START + offset] = 80
        avg_col = STORE_COL_START + len(store_columns)
        col_widths[avg_col] = 75       # Ср.EUR
        col_widths[avg_col + 1] = 55   # Статус
        col_widths[DEVIATION_COL] = 65  # Откл.%

        for col_idx, width in col_widths.items():
            format_requests.append({
                "updateDimensionProperties": {
                    "range": {"sheetId": sheet.id,
                              "dimension": "COLUMNS",
                              "startIndex": col_idx, "endIndex": col_idx + 1},
                    "properties": {"pixelSize": width},
                    "fields": "pixelSize"
                }
            })

        # Числово форматиране за ценови колони (2 десетични знака)
        price_cols_start = KASHON_EUR_COL  # от Кашон EUR до последния магазин + Ср.EUR
        price_cols_end = STORE_COL_START + len(store_columns) + 1  # +1 за Ср.EUR
        if last_row > HEADER_ROW:
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id,
                              "startRowIndex": HEADER_ROW, "endRowIndex": last_row,
                              "startColumnIndex": price_cols_start,
                              "endColumnIndex": price_cols_end},
                    "cell": {"userEnteredFormat": {
                        "numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"},
                        "horizontalAlignment": "RIGHT",
                    }},
                    "fields": "userEnteredFormat(numberFormat,horizontalAlignment)"
                }
            })

        # Числово форматиране за Откл.% колона (с +/- знак)
        if last_row > HEADER_ROW:
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id,
                              "startRowIndex": HEADER_ROW, "endRowIndex": last_row,
                              "startColumnIndex": DEVIATION_COL,
                              "endColumnIndex": DEVIATION_COL + 1},
                    "cell": {"userEnteredFormat": {
                        "numberFormat": {"type": "NUMBER", "pattern": "+#,##0.0;-#,##0.0;0.0"},
                        "horizontalAlignment": "RIGHT",
                    }},
                    "fields": "userEnteredFormat(numberFormat,horizontalAlignment)"
                }
            })

        # Фиксиране на header реда (freeze)
        format_requests.append({
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet.id,
                    "gridProperties": {"frozenRowCount": HEADER_ROW}
                },
                "fields": "gridProperties.frozenRowCount"
            }
        })

        # Светлозелен фон за нови продукти (ПРЕДИ deviation оцветяването)
        for row_idx in new_product_rows:
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id,
                              "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                              "startColumnIndex": 0, "endColumnIndex": last_col},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": {"red": 0.85, "green": 0.95, "blue": 0.85},
                        "textFormat": {
                            "foregroundColor": {"red": 0.1, "green": 0.4, "blue": 0.1},
                        }
                    }},
                    "fields": "userEnteredFormat(backgroundColor,textFormat.foregroundColor)"
                }
            })

        # Сиво форматиране за изчерпани (OOS)
        for row_idx, col_idx in out_of_stock_cells:
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id,
                              "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                              "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": {"red": 0.93, "green": 0.93, "blue": 0.93},
                        "textFormat": {
                            "foregroundColor": {"red": 0.6, "green": 0.6, "blue": 0.6},
                            "italic": True,
                        }
                    }},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)"
                }
            })

        # Червено (↑) за цени >10% над средната (СЛЕД new/removed)
        for row_idx, col_idx in deviation_cells_high:
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id,
                              "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                              "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": {"red": 0.96, "green": 0.80, "blue": 0.80},
                        "textFormat": {
                            "foregroundColor": {"red": 0.7, "green": 0.0, "blue": 0.0},
                            "bold": True,
                        }
                    }},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)"
                }
            })

        # Светлосиньо (↓) за цени >10% под средната (СЛЕД new/removed)
        for row_idx, col_idx in deviation_cells_low:
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id,
                              "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                              "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": {"red": 0.82, "green": 0.91, "blue": 0.98},
                        "textFormat": {
                            "foregroundColor": {"red": 0.0, "green": 0.3, "blue": 0.6},
                            "bold": True,
                        }
                    }},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)"
                }
            })

        # Жълт фон за отпаднали продукти
        for row_idx in removed_product_rows:
            format_requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet.id,
                              "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                              "startColumnIndex": 0, "endColumnIndex": last_col},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": {"red": 1.0, "green": 0.95, "blue": 0.80},
                        "textFormat": {
                            "foregroundColor": {"red": 0.6, "green": 0.5, "blue": 0.0},
                            "strikethrough": True,
                        }
                    }},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)"
                }
            })

        if format_requests:
            sheet.spreadsheet.batch_update({"requests": format_requests})
            logger.info(f"Форматиране: {len(format_requests)} заявки")
            if category_separator_rows:
                logger.info(f"Категории: {len(category_separator_rows)} разделителни реда")
            if new_product_rows:
                logger.info(f"Нови продукти: {len(new_product_rows)} реда (зелен фон)")
            if removed_product_rows:
                logger.info(f"Отпаднали продукти: {len(removed_product_rows)} реда (жълт фон)")
            if out_of_stock_cells:
                logger.info(f"Сиво форматиране: {len(out_of_stock_cells)} изчерпани клетки")
            if deviation_cells_high or deviation_cells_low:
                logger.info(f"Отклонения: {len(deviation_cells_high)} ↑ червени, "
                            f"{len(deviation_cells_low)} ↓ сини")

        return True

    except Exception as e:
        logger.warning(f"Форматиране пропуснато (данните са записани): {e}")
        return True


# =============================================================================
# ИСТОРИЯ TAB — append-only ценова история по седмици
# =============================================================================

def append_history_to_sheets(final_products):
    """
    Добавя ред за всеки продукт в История_{year} таба.
    Append-only — не изтрива стари данни, натрупва история.
    Използва същия spreadsheet като write_to_sheets().
    """
    if not GSPREAD_AVAILABLE:
        logger.warning("gspread not available — skipping history append")
        return False

    current_year = datetime.now().year
    tab_suffix = os.environ.get("SHEET_TAB_SUFFIX", "")
    history_tab_name = f"История_{current_year}{tab_suffix}"

    store_keys = [k for k, cfg in STORES.items() if not cfg.get("is_master")]
    store_keys += list(GLOVO_STORES.keys())
    store_display = {k: cfg["name"] for k, cfg in STORES.items()}
    store_display.update({k: f"Glovo {cfg['name']}" for k, cfg in GLOVO_STORES.items()})

    date_str = datetime.now().strftime("%d.%m.%Y")
    time_str = datetime.now().strftime("%H:%M")

    try:
        creds_json = os.environ.get("GOOGLE_CREDENTIALS")
        if creds_json:
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                f.write(creds_json)
                creds_path = f.name
            gc = gspread.service_account(filename=creds_path)
            os.unlink(creds_path)
        else:
            gc = gspread.service_account(filename='credentials.json')

        spreadsheet_id = os.environ.get("SPREADSHEET_ID")
        if spreadsheet_id:
            spreadsheet = gc.open_by_key(spreadsheet_id)
        else:
            spreadsheet = gc.open("Harmonica Price Tracker")

    except Exception as e:
        logger.error(f"История: Sheets връзка неуспешна: {e}")
        return False

    # Headers за История таба
    headers = ['Дата', 'Час', 'Продукт', 'Грамаж', 'Кашон EUR']
    for sk in store_keys:
        headers.append(store_display.get(sk, sk))
    headers.extend(['Ср.EUR', 'Мин.EUR', 'Макс.EUR'])

    try:
        try:
            hist = spreadsheet.worksheet(history_tab_name)
        except gspread.exceptions.WorksheetNotFound:
            hist = spreadsheet.add_worksheet(title=history_tab_name, rows=5000, cols=len(headers))
            hist.update(values=[headers], range_name='A1')
            hist.freeze(rows=1)
            # Bold + green header
            hist.spreadsheet.batch_update({"requests": [{
                "repeatCell": {
                    "range": {"sheetId": hist.id,
                              "startRowIndex": 0, "endRowIndex": 1,
                              "startColumnIndex": 0, "endColumnIndex": len(headers)},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": {"red": 0.18, "green": 0.49, "blue": 0.20},
                        "textFormat": {"bold": True, "fontSize": 10,
                                       "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                    }},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)"
                }
            }]})
            logger.info(f"Създаден нов таб: {history_tab_name}")

        # Изграждаме редовете
        hist_rows = []
        for p in final_products:
            kashon = p.get("kashon") or {}
            kashon_eur = kashon.get("eur")

            row = [date_str, time_str, p["name"], extract_weight(p["name"]),
                   kashon_eur if kashon_eur else '']

            all_eur = []
            if kashon_eur:
                all_eur.append(kashon_eur)

            for sk in store_keys:
                sd = p.get(sk)
                if sd and sd.get("eur"):
                    row.append(sd["eur"])
                    all_eur.append(sd["eur"])
                else:
                    row.append('')

            if all_eur:
                avg = round(sum(all_eur) / len(all_eur), 2)
                row.extend([avg, min(all_eur), max(all_eur)])
            else:
                row.extend(['', '', ''])

            hist_rows.append(row)

        if hist_rows:
            hist.append_rows(hist_rows, value_input_option='USER_ENTERED')
            logger.info(f"История: {len(hist_rows)} реда добавени в {history_tab_name}")

        return True

    except Exception as e:
        logger.error(f"История грешка: {str(e)[:120]}")
        return False
