# Changelog — Harmonica Price Tracker

Всички значими промени в проекта се документират тук.

Форматът е базиран на [Keep a Changelog](https://keepachangelog.com/bg/1.0.0/).

---
## v9.6.0 - 2026-02-14

### Добавено
- **Claude Sonnet 4.5 ценова валидация** в experimental scraper — автоматично откриване и оценка на съмнителни цени преди записване в Google Sheets
- Нова функция `validate_prices_with_claude()` — изпраща batch от outlier цени (>50% отклонение от медианата) към Claude Sonnet за оценка
- Три типа вердикти: **ГРЕШНА** (автоматично премахната), **ВЯРНА** (запазена), **СЪМНИТЕЛНА** (флагната за ръчна проверка)
- `ANTHROPIC_API_KEY` environment variable — опционално, без ключ валидацията се пропуска gracefully
- `CLAUDE_MODEL` константа (`claude-sonnet-4-5-20250929`)
- `validation_log` в JSON output (`experimental/pilot_results.json`) за одит на всяко решение
- Anthropic SDK import с graceful fallback (`ANTHROPIC_AVAILABLE` флаг)
- Claude наличност се логва при стартиране

### Променено
- Версия обновена от v9.5.0 на v9.6.0
- JSON output включва `claude_validation` поле
- Вътрешни `_flags` полета се почистват преди JSON запис

### Технически детайли
- Валидацията се изпълнява между стъпка 3 (matching) и стъпка 4 (statistics) в `main()`
- Prompt-ът включва контекст за типични цени на Harmonica продукти в България (2024-2026)
- Claude оценява дали цената е за правилен грамаж, правилен продукт, или е грешно парсната
- Грешни цени се нулират (`product[store] = None`) преди statistics и sheets write
- `anthropic==0.40.0` вече е в requirements.txt (бе неизползван до сега)

---
## v9.5.0 - 2026-02-10

### Добавено
- **Logging модул** в scraper.py и scraper_experimental.py — заместващ print() с подходящи logging нива (INFO, WARNING, ERROR, DEBUG). Логове се записват във файл + конзола.
- **Паралелно краулване** с `asyncio.gather` в experimental scraper — всички магазини се сканират едновременно вместо последователно
- **BeautifulSoup за Lilly Drogerie** — по-устойчиво HTML парсване с regex fallback ако BS4 не е наличен
- **Retry декоратор** за мрежови грешки в crawl функциите — автоматичен retry с exponential backoff
- **Подобрено съпоставяне на продукти** — нормализация на тегловни единици (kg→g, l→ml), процентен бонус (3.6%), наказание за несъвпадение на тегло, предотвратяване на дублиращи се matches
- `beautifulsoup4` добавен в requirements.txt

### Променено
- **Седмичен график:** Всички workflow-и (production, experimental, weekly) — понеделник 05:00 UTC (07:00 българско зимно време)
- `weekly-scrape.yml` вече е само за ръчно стартиране (cron премахнат)
- Production workflow преименуван от "Daily" на "Weekly"
- Experimental scraper обновен от v6.3 на v7.0

### Премахнато
- **Zoya.bg** премахнат от планираните магазини — вече не продава продукти Harmonica
- **DM България** — отложен поради 403 anti-bot защита

### Поправено
- Почистен дублиран контент в EXPERIMENTS.md

---
## v9.4.0 - 2026-02-10

### Променено
- **Седмичен график:** Всички workflow-и (production, experimental, weekly) вече се изпълняват веднъж седмично — понеделник 05:00 UTC (07:00 българско зимно време)
- Production workflow преименуван от "Daily" на "Weekly"
- Актуализирани коментари в cron schedule-ите

### Премахнато
- **Zoya.bg** премахнат от планираните магазини в EXP-003 — вече не продава продукти Harmonica

### Поправено
- Почистен дублиран контент в EXPERIMENTS.md

---
## v9.2.0 - 2026-02-05

### Добавено
- **SHEET_TAB_SUFFIX поддръжка** - Възможност за записване в отделни Google Sheets табове чрез environment variable
- Experimental workflow вече записва в "Ценови Тракер_experimental" и "История_2026_experimental" табове
- Пълна изолация между production и experimental данни

### Променено
- `update_google_sheets()` функцията вече използва динамични имена на табове
- Актуализиран `experimental.yml` с правилни credentials (SPREADSHEET_ID, GMAIL_USER, GMAIL_APP_PASSWORD)

### Поправено
- Синхронизация между main и experimental branches
- Липсващи environment variables в experimental workflow

### Технически детайли
- Нова константа: `SHEET_TAB_SUFFIX = os.environ.get("SHEET_TAB_SUFFIX", "")`
- Production използва празен suffix (оригинални табове)
- Experimental използва "_experimental" suffix


## [Unreleased]

### В разработка (experimental branch)
- 🔬 Crawl4AI интеграция — тестване като алтернатива на Playwright
- 🔬 Нови магазини — Lilly Drogerie, DM България, ХИТ Хипермаркет

---

## [9.3.1] - 2026-01-30

### Текущо състояние (Production)
- ✅ 9 магазина: eBag, Кашон Harmonica, Balev Bio Market, DM България, T-Market, Billa, Kaufland, BeFit, Metro
- ✅ 27 Harmonica продукта в референтния списък
- ✅ Двуфазен Claude AI анализ за интелигентно съпоставяне
- ✅ Автоматично изпълнение всеки ден в 06:00 UTC
- ✅ HTML имейл известия при ценови аномалии над 10%
- ✅ Google Sheets с форматиране и цветово кодиране

---

## [9.1.0] - 2026-01-12

### Добавено
- Колоната "Откл.%" показва посоката на отклонението с ↓ (по-евтино) или ↑ (по-скъпо)
- Визуална индикация в имейл нотификациите за тип отклонение
- Цветово кодиране в Google Sheets: синьо за по-евтино, червено за по-скъпо

---

## [9.0.0] - 2026-01-11

### Променено
- **BREAKING**: Средната цена вече се изчислява от реалните пазарни цени
- Статус "ВНИМАНИЕ" се задейства при отклонение над 10% от пазарната средна
- Референтните цени се запазват само за валидиране

### Добавено
- Автоматично оцветяване на клетките с ценови аномалии
- Детайлна информация за отклоненията по магазини в имейл известията

---

## [8.0.0] - 2026-01-09

### Добавено
- Разширено покритие от 3 на 9 магазина
- T-Market, Billa, Kaufland, BeFit, Metro добавени към мониторинга

---

## [7.7.0] - 2026-01-05

### Поправено
- Валутно объркване между BGN и EUR — системата третира всички цени като BGN

---

## [6.2.0] - 2025-12-31

### Добавено
- Balev Bio Market като трети магазин
- Debug функция за диагностика на HTML структури
- Увеличено скролиране за пълно зареждане на продукти

---

## [3.0.0] - 2025-12-28

### Първоначална версия
- Базова функционалност с eBag и Кашон Harmonica
- Playwright за JavaScript рендериране
- gspread за Google Sheets интеграция
- Gmail SMTP за имейл известия
