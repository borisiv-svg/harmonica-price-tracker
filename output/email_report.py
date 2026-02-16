"""
Harmonica Price Tracker — Email Report
========================================
Sends HTML email reports with price tracking summary.
"""

import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import STORES, GLOVO_STORES, logger


def send_email_report(final_products, stats):
    """
    Изпраща HTML имейл с обобщение на резултатите от experimental scraper.
    """
    gmail_user = os.environ.get('GMAIL_USER')
    gmail_pass = os.environ.get('GMAIL_APP_PASSWORD')
    recipients = os.environ.get('ALERT_EMAIL', gmail_user)
    spreadsheet_id = os.environ.get('SPREADSHEET_ID', '')

    if not gmail_user or not gmail_pass:
        logger.warning("Gmail credentials не са зададени — пропускане на имейл")
        return

    if not recipients:
        logger.warning("ALERT_EMAIL не е зададен — пропускане на имейл")
        return

    sheets_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}" if spreadsheet_id else ""
    date_str = datetime.now().strftime("%d.%m.%Y")
    time_str = datetime.now().strftime("%H:%M")

    # Статистики
    total_products = len(final_products)
    store_keys = [key for key, cfg in STORES.items() if not cfg.get("is_master")]
    store_keys += list(GLOVO_STORES.keys())

    # Покритие по магазини
    store_coverage = {}
    all_display = {}
    all_display.update({k: cfg["name"] for k, cfg in STORES.items()})
    all_display.update({k: f"Glovo {cfg['name']}" for k, cfg in GLOVO_STORES.items()})

    for sk in store_keys:
        count = len([p for p in final_products if p.get(sk)])
        store_coverage[all_display.get(sk, sk)] = count

    # Продукти с отклонение >10%
    alerts = []
    for p in final_products:
        all_prices = []
        kashon = p.get("kashon") or {}
        if kashon.get("eur"):
            all_prices.append(kashon["eur"])
        for sk in store_keys:
            sd = p.get(sk)
            if sd and sd.get("eur"):
                all_prices.append(sd["eur"])
        if len(all_prices) >= 2:
            avg = sum(all_prices) / len(all_prices)
            max_dev = max(((pr - avg) / avg) * 100 for pr in all_prices)
            min_dev = min(((pr - avg) / avg) * 100 for pr in all_prices)
            extreme = max_dev if abs(max_dev) >= abs(min_dev) else min_dev
            if abs(extreme) > 10:
                alerts.append({"name": p["name"], "deviation": round(extreme, 1)})

    warning_count = len(alerts)
    ok_count = total_products - warning_count

    if warning_count > 0:
        subject = f"Harmonica: {warning_count} продукта с отклонение >10%"
    else:
        subject = f"Harmonica: Всички цени в норма ({total_products} продукта)"

    html = f"""<html><head><style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .header {{ background: #2e7d32; color: white; padding: 20px; text-align: center; }}
        .header h1 {{ margin: 0; font-size: 22px; }}
        .header p {{ margin: 5px 0 0; font-size: 13px; opacity: 0.9; }}
        .summary {{ background: #f5f5f5; padding: 15px; margin: 20px; border-radius: 5px; }}
        .stats {{ display: flex; justify-content: space-around; text-align: center; }}
        .stat-box {{ padding: 10px; }}
        .stat-number {{ font-size: 28px; font-weight: bold; }}
        .stat-label {{ font-size: 12px; color: #666; }}
        .ok {{ color: #2e7d32; }}
        .warning {{ color: #d32f2f; }}
        .alert-section {{ background: #ffebee; border-left: 4px solid #d32f2f; padding: 15px; margin: 20px; }}
        .coverage {{ margin: 20px; }}
        .bar-bg {{ background: #e0e0e0; height: 18px; border-radius: 9px; margin: 4px 0; overflow: hidden; }}
        .bar-fill {{ background: #4caf50; height: 100%; }}
        .footer {{ background: #f5f5f5; padding: 15px; text-align: center; font-size: 12px; color: #666; }}
        .button {{ display: inline-block; background: #2e7d32; color: white; padding: 10px 20px;
                   text-decoration: none; border-radius: 5px; margin: 10px; }}
    </style></head><body>
    <div class="header">
        <h1>HARMONICA Price Tracker</h1>
        <p>Отчет за {date_str} в {time_str} ч.</p>
    </div>
    <div class="summary">
        <h2 style="color:#2e7d32; margin-top:0;">Обобщение</h2>
        <div class="stats">
            <div class="stat-box"><div class="stat-number">{total_products}</div><div class="stat-label">Продукта</div></div>
            <div class="stat-box"><div class="stat-number ok">{ok_count}</div><div class="stat-label">В норма</div></div>
            <div class="stat-box"><div class="stat-number warning">{warning_count}</div><div class="stat-label">С отклонение</div></div>
            <div class="stat-box"><div class="stat-number">{len(STORES)+len(GLOVO_STORES)}</div><div class="stat-label">Магазина</div></div>
        </div>
    </div>"""

    if alerts:
        html += f'<div class="alert-section"><h2 style="color:#d32f2f;margin-top:0;">Отклонения &gt;10%</h2>'
        for a in alerts[:15]:
            arrow = "↑" if a["deviation"] > 0 else "↓"
            color = "#d32f2f" if a["deviation"] > 0 else "#1565c0"
            html += f'<p><strong>{a["name"]}</strong>: <span style="color:{color}">{arrow} {abs(a["deviation"]):.1f}%</span></p>'
        if len(alerts) > 15:
            html += f'<p><em>... и още {len(alerts)-15} продукта</em></p>'
        html += '</div>'
    else:
        html += '<div class="summary" style="background:#e8f5e9;border-left:4px solid #2e7d32;margin:20px;"><h2 style="color:#2e7d32;margin-top:0;">Всички цени са в норма</h2></div>'

    html += '<div class="coverage"><h2 style="color:#2e7d32;">Покритие по магазини</h2>'
    for store_name, count in store_coverage.items():
        pct = (count / total_products * 100) if total_products else 0
        html += f'<div style="font-size:13px;color:#666;"><strong>{store_name}</strong>: {count}/{total_products} ({pct:.0f}%)</div>'
        html += f'<div class="bar-bg"><div class="bar-fill" style="width:{pct}%"></div></div>'
    html += '</div>'

    if sheets_url:
        html += f'<div style="text-align:center;margin:20px;"><a href="{sheets_url}" class="button">Отвори в Google Sheets</a></div>'

    html += f'<div class="footer"><p><strong>Harmonica Price Tracker v10.3</strong></p><p>Автоматично генерирано на {date_str} в {time_str} ч.</p></div></body></html>'

    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = gmail_user
        msg['To'] = recipients
        msg['Subject'] = subject
        msg.attach(MIMEText(html, 'html', 'utf-8'))

        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(gmail_user, gmail_pass)
            server.send_message(msg)

        logger.info(f"Имейл изпратен до {recipients}")
    except Exception as e:
        logger.error(f"Имейл грешка: {str(e)[:80]}")
