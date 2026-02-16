# Changelog — Harmonica Price Tracker

Всички значими промени в проекта се документират тук.

Форматът е базиран на [Keep a Changelog](https://keepachangelog.com/bg/1.0.0/).

---
## v10.13.0 - 2026-02-16

### Добавено
- **Product re-activation** — `update_product_list_with_new()` реактивира removed продукти, намерени отново в Кашон:
  - Ако продукт с `active: false` се появи в Кашон crawl, се маркира `status: "reactivated"` и `active: true`
  - Актуализира референтната цена с текущата от Кашон
  - Запазва оригиналното име и `added_date`
  - Предпазва от загуба на продукти при непълно зареждане на Кашон (infinite scroll timeout)
- **3 нови теста** в `test_products.py` — re-activation, case-insensitive re-activation, preservation на оригинални полета
- Общо тестове: **180** (было 178)

### Поправено
- **75 removed продукта** бяха неправилно деактивирани от предишни run-ове с непълно зареждане на Кашон. При следващ run с пълно зареждане ще бъдат автоматично реактивирани

---
## v10.12.1 - 2026-02-16

### Поправено
- **Version strings** — обновени от v10.8 на v10.12 в scraper.py (header + JSON output) и email footer

### Документация
- **ROADMAP.md** — актуализирано текущо състояние:
  - Продукти: 39 активни + 75 removed (беше 88)
  - Runtime: ~330s (беше ~366s)
  - Fallback верига: добавена бележка за Lilly GraphQL
- **Известни проблеми** — нова секция с 6 открити проблема от production run 2026-02-16:
  - T-Market Cloudflare (0/39) — блокиран по всички 3 канала
  - Glovo Kaufland (0/39) — Firecrawl actions fail
  - Firecrawl масови timeouts (5/11 магазина) — Crawl4AI fallback компенсира
  - BeFit Firecrawl actions "Element not found"
  - Lilly Firecrawl (1 продукт vs 11 от GraphQL)
- **Покритие по магазин** — визуална таблица с bar chart за всеки магазин
- **Следващи стъпки (v11.x)** — Фази 11-13: T-Market нов подход, Glovo Kaufland, сутрешен benchmark

---
## v10.12.0 - 2026-02-16

### Добавено
- **Dependabot интеграция (Фаза 9)** — `.github/dependabot.yml`:
  - Weekly проверка за `pip` и `github-actions` зависимости (сряда)
  - Групиране на minor/patch updates в един PR
  - Лимит от 5 едновременно отворени PR-и
  - Labels: `dependencies` (pip), `ci` (actions)
- **Ценова история — local JSON (Фаза 10)** — `price_history.py`:
  - `record_prices()` — записва ценови snapshot от всеки run в `data/price_history.json`
  - `get_price_trend()` — връща средна цена по дата за последните N седмици
  - `load_history()` / `save_history()` — JSON persistence с лимит от 6000 записа
  - 10 нови теста в `tests/test_price_history.py`
- **Възстановяване на История_{year} tab** — `append_history_to_sheets()` в `output/sheets.py`:
  - Записва редове за всеки продукт с цени от всички магазини + средна/мин/макс EUR
  - Автоматично създава таб с зелен header + freeze row 1 ако липсва
  - Интегрирано в `scraper.py main()` — записва след `write_to_sheets()`
  - `data/price_history.json` се commit-ва автоматично от CI

---
## v10.11.0 - 2026-02-16

### Добавено
- **CI dry-run pre-check (Фаза 8)** — `production.yml` вече изпълнява `--dry-run` преди production scrape:
  - Краулва Кашон + eBag + Balev (~30s) и проверява дали всеки магазин връща >0 matched продукта
  - **Fail-fast** — ако dry-run върне exit code 1, production scrape НЕ се изпълнява
  - **GitHub Actions error annotation** — `::error::` маркер при dry-run failure, видим директно в PR/workflow UI
  - **Step Summary** — markdown summary с резултат (pass/fail) и next steps при failure
  - `skip_dry_run` input за manual dispatch — позволява bypass при debugging
  - `timeout-minutes: 30` за целия job (преди: без лимит)
  - Version strings обновени в workflow header и Environment info step

---
## v10.10.0 - 2026-02-16

### Добавено
- **Test coverage разширяване (Фаза 6)** — 28 нови теста (140 → 168):
  - `test_products.py` — 15 теста: load (active filtering, missing file, corrupted JSON, EUR calculation, field preservation), update (new products, duplicates, case-insensitive, removed re-add prevention), save (roundtrip, keywords, removed preservation, metadata, sequential IDs)
  - `test_output.py` — 13 теста: `extract_weight()` (7 cases), `send_email_report()` smoke tests (no credentials, with credentials, health alerts, empty products), `write_to_sheets()` smoke tests (gspread unavailable, import check)

### Променено
- **conftest.py cleanup** — `load_fixture()` преместен в `tests/helpers.py` (споделен helper), премахнат дубликат от `test_extractors.py`
- `conftest.py` добавя `tests/` dir в `sys.path` за достъп до `helpers.py`

---
## v10.9.0 - 2026-02-16

### Добавено
- **Zelen deep-dive (Фаза 5)** — стабилизиране на Zelen extraction:
  - Cookie consent handling в Zelen config (`pre_js` + `firecrawl_pre_actions`) — основна причина за малко продукти
  - `_normalize_image_links()` в generic extractor — `[![alt](img)](url)` → `[alt](url)`, елиминира дубликати
  - Zelen fixture (`tests/fixtures/zelen.md`) с 16 продукта от реалната структура на сайта
  - 5 нови теста за Zelen extraction + image-link normalization

### Поправено
- **`normalize_name()` decimal kg bug** — `"Product 1.5kg"` връщаше `"product 1 5000г"` вместо `"product 1500г"`. Decimal kg regex (`1.5kg` → `1500г`) сега се прилага преди integer kg regex (`5kg` → `5000г`)
- **Version strings** — обновени от v10.3/v10.5/v10.6 на v10.8 в scraper.py и email footer

---
## v10.8.0 - 2026-02-16

### Добавено
- **Store health мониторинг** — автоматично откриване на деградация по магазини:
  - `run_history.py` — нов модул за запис на `data/run_history.json` с брой продукти по магазин при всеки run
  - Alert логика: 0 продукта от магазин ИЛИ >50% спад спрямо предишен run
  - Health summary в логовете: `HEALTH CHECK` секция при всяко изпълнение
  - Health alerts в имейл отчета — оранжева секция с детайли за проблемни магазини
  - Генерализиран debug markdown save — при аномалия суровият markdown на всеки проблемен магазин се записва в `data/{store}_debug.md`
- **21 нови теста** за `run_history.py` — load/save, build entry, health checks, alerts, integration
- **Import smoke test** за `run_history` модула
- `data/run_history.json` се commit-ва автоматично от CI (заедно с `harmonica_products.json`)

### Променено
- Zelen-only debug markdown save заменен с генерализиран debug save за всички магазини при health alert
- `send_email_report()` приема нов `health_alerts` параметър
- `production.yml` commit step обновен да включва `data/run_history.json`

---
## v10.7.0 - 2026-02-16

### Добавено
- **Тестова инфраструктура (pytest)** — 113 теста в 4 модула:
  - `test_imports.py` — smoke import на всички 18 модула (хваща BrowserConfig/Firecrawl бъгове)
  - `test_extractors.py` — 6 extractors с markdown fixtures (kashon, ebag, balev, metro, randi, generic)
  - `test_utils.py` — EUR/BGN/fallback цени, name cleaning, food/harmonica филтри, категории, Cloudflare detection
  - `test_matching.py` — name normalization, keyword extraction, weight parsing, matching engine scoring
  - 6 markdown fixtures в `tests/fixtures/` за реалистични тестови данни
- **`--dry-run` режим** — `python scraper.py --dry-run` краули само Кашон + eBag + Balev, пропуска Sheets/email, принтира summary, exit code 1 при 0 matched
- **`crawl_all(only_stores=...)` параметър** — селективно краулване на подмножество магазини
- **pytest стъпка в `production.yml`** — тестовете се изпълняват преди smoke test и scraper

### Променено
- **Dependency pinning** — всички 10 пакета с точни версии:
  - `anthropic==0.79.0` (беше `>=0.40.0,<1.0.0`)
  - `crawl4ai==0.8.0` (беше `>=0.4.0,<1.0.0`)
  - `curl_cffi==0.14.0` (беше `>=0.7.0,<1.0.0`)
  - `capsolver==1.0.7` (беше `>=1.0.0,<2.0.0`)
  - `pytest==9.0.2` добавен в requirements.txt

### Документация
- **ROADMAP.md** — изводи от последните сесии, 5-фазен план за действие

---
## v10.6.1 - 2026-02-16

### Поправено
- **NameError: `BrowserConfig` is not defined** — при cleanup на star imports (`from config import *` → explicit imports) в scraper.py, `BrowserConfig` и `AsyncWebCrawler` от crawl4ai не бяха включени. Добавен conditional import: `if CRAWL4AI_AVAILABLE: from crawl4ai import AsyncWebCrawler, BrowserConfig`
- **Generic `brand_page=False` fallback** — BeFit-specific retry заменен с универсален fallback за всички магазини с ≤5 продукта. Ако `brand_page=True` връща малко резултати, автоматично се пробва `brand_page=False` и се ползва по-добрият резултат

### Добавено
- **Zelen debug markdown** — при ≤5 продукта, суровият markdown от Zelen се записва в `data/zelen_debug.md` за диагностика

### Потвърдено
- Production Weekly Scraper: 15 магазина, 88 продукта, 366 секунди — без грешки

---
## v10.6.0 - 2026-02-16

### Променено
- **Модуляризация на scraper.py** — монолитният файл (4,573 реда, 57 функции) е разделен на 18 модула:
  - `config.py` — константи, магазинни конфигурации, feature flags, logger
  - `utils.py` — извличане на цени, почистване на имена, food филтриране, retry декоратор
  - `products.py` — управление на продуктовия списък (load/update/save JSON)
  - `matching.py` — keyword-based matching engine с тежести
  - `validation.py` — Claude Sonnet ценова валидация
  - `extractors/` пакет (9 модула) — по един за всеки магазин + generic
  - `fetchers/` пакет (4 модула) — Firecrawl, Crawl4AI, curl_cffi, Glovo
  - `output/` пакет (2 модула) — Google Sheets + имейл отчети
- **scraper.py** остава entry point с `crawl_all()` + `main()` — 642 реда (86% редукция)
- Версия обновена от v10.5 на v10.6

### Поправено
- **Zelen покритие** — добавен `brand_page=False` fallback (аналогично на BeFit), увеличен `scroll_times` от 10 на 15, добавена диагностика за запис на markdown при малко продукти

### Премахнато
- **experimental.yml** — workflow реферираше несъществуващ `experimental/scraper_experimental.py`
- **pilot-test.yml** — workflow реферираше несъществуващ `experimental/crawl4ai_pilot.py`

### Технически детайли
- Import hierarchy е DAG (без circular imports): config → utils → products → extractors → fetchers → output → scraper
- Нулева промяна на логиката — чист refactor, запазено точно поведение
- `production.yml` и `monthly-product-sync.yml` не са засегнати
- `scripts/monthly_product_sync.py` е standalone и не се влияе

---
## v10.5.1 - 2026-02-15

### Поправено
- **Google Sheets форматиране** — `unmergeCells` грешка блокираше **целия** formatting batch (138+ заявки — цветове, ширини, freeze, deviation highlighting). Причина: `sheet.clear()` изчиства само данни, но не разлепва merge-нати клетки от предишен run. При различен брой колони между run-ове, `unmergeCells` range-ът частично покриваше стария merge → API грешка → нито едно форматиране не се прилагаше. Fix: `unmergeCells` е изнесен в отделен `batch_update` с `sheet.row_count × sheet.col_count` (пълен sheet range), обвит в `try/except`, така че дори да гърми — основното форматиране продължава.
- **T-Market Crawl4AI Cloudflare bypass** — `crawl_with_captcha_solver()` беше написана и T-Market имаше `needs_captcha_solver: True`, но Crawl4AI fallback-ът **никога не я извикваше** — винаги ползваше обикновения `crawl_store()`, който не може да bypass-не Cloudflare. Резултат: когато Firecrawl timeout-ваше, T-Market връщаше "Performing security verification" → 0 продукта. Fix: Crawl4AI fallback проверява `needs_captcha_solver` и dispatch-ва към `crawl_with_captcha_solver()`.

### Резултати (преди → след)
| Проблем | Преди | След |
|---------|-------|------|
| Sheet форматиране | `APIError [400] unmergeCells` → 0 formatting | 138 заявки успешно |
| T-Market (Firecrawl timeout) | 0/88 (Cloudflare block) | 11-13/88 (captcha solver fallback) |

### Потвърдено от 3 последователни run-a (2026-02-15)
- **15 магазина** работещи: Кашон, eBag, Balev Bio, Lilly, T-Market, Metro, Zelen, Randi, Bio-Market, BeFit, Laika, Glovo Kaufland/Billa/CBA/Fantastico
- **88 продукта** в референтния списък
- **Claude валидация** стабилна: 8 премахнати, 2 флагнати, 13 потвърдени
- **Тройна fallback верига** работи: Firecrawl → Crawl4AI → curl_cffi (GraphQL за Lilly)
- **Пълно форматиране** в Google Sheets: категории, цветове, freeze, deviation highlighting

---
## v10.1.0 - 2026-02-15

### Добавено
- **Продуктов списък от JSON** — `harmonica_products.json` е master list; Кашон се краули само за цени, не за списък продукти
- `load_product_list()` — зарежда активни продукти от `data/products/harmonica_products.json`
- `update_product_list_with_new()` — открива нови продукти от Кашон и ги маркира с `status: "new"`
- `save_product_list()` — записва обновения списък обратно в JSON с актуални Кашон цени
- **Цветово кодиране по статус** в Google Sheets:
  - Светлозелен фон за нови продукти (добавени при последен sync)
  - Жълт фон + зачертан текст за отпаднали продукти
- `status` поле в `harmonica_products.json` — `active`, `new`, `removed`

### Променено
- **EUR-only цени** — external магазини записват само EUR; BGN се пази единствено за Кашон
- **Claude валидация** — outlier detection и prompt context преминаха от BGN на EUR
- Версия обновена от v10.0 на v10.1
- `harmonica_products.json` — всички `ref_eur: null` стойности изчислени от `ref_bgn / EUR_BGN_RATE`
- Примерни продукти в лога показват EUR вместо BGN
- `match_products()` вече matchва спрямо reference list (от JSON), не Кашон crawl

### Технически детайли
- `PRODUCTS_JSON_PATH` — абсолютен път до `data/products/harmonica_products.json`
- При всяко изпълнение: JSON → load → crawl Кашон → match prices → discover new → save JSON
- Fallback: ако JSON липсва, Кашон crawl генерира нов
- Claude prompt: типични цени конвертирани в EUR (1 EUR = 1.9558 BGN)
- Store entries: `product["ebag"] = {"eur": X}` вместо `{"eur": X, "bgn": Y}`
- Kashon entries: `product["kashon"] = {"eur": X, "bgn": Y}` (запазва и двете)

---
## v10.0.1 - 2026-02-14

### Поправено
- **Firecrawl import** — `from firecrawl import Firecrawl` е грешно; класът се казва `FirecrawlApp`. Тихо `ImportError` → `FIRECRAWL_AVAILABLE = False`, което блокираше DM, Randi и всички 4 Glovo магазина
- **Firecrawl API промяна** — `.scrape()` е премахнат в по-новите версии на `firecrawl-py`; правилният метод е `.scrape_url(url, params={...})`. DM и Glovo ползваха стария API, Randi вече беше на новия
- **Generic extractor за Laika** — block-based разделяне по `\n{2,}` не работеше за сайтове с единични нови редове между продуктите. Цялата страница ставаше един блок → само 1 продукт. Нов `_extract_generic_line_by_line()` fallback решава проблема
- **Claude валидация JSON truncation** — фиксиран `max_tokens=2000` беше недостатъчен при 38+ съмнителни цени (повече магазини = повече outlier-и). JSON-ът се отрязваше → `JSONDecodeError` → валидацията се пропускаше изцяло
- **Startup диагностика** — `Firecrawl: YES` проверяваше само `FIRECRAWL_API_KEY`, не `FIRECRAWL_AVAILABLE`. Сега предупреждава ако ключът е зададен, но import-ът е неуспешен

### Променено
- `max_tokens` за Claude валидация е динамичен: `max(2000, len(suspicious) * 150 + 500)`
- JSON repair fallback: ако Sonnet върне truncated JSON, парсва частичните verdict-и вместо да пропуска всичко
- Generic extractor е рефакториран в три функции: `_extract_generic_products()` (orchestrator), `_extract_generic_block_based()`, `_extract_generic_line_by_line()`
- Context window за line-by-line price extraction стеснен от ±3-8 на ±2-5 реда

### Резултати (преди → след)
| Магазин | Преди | След |
|---------|-------|------|
| DM | 0/88 (0%) | 11/88 (12%) |
| BeFit | 0/88 (timeout) | 43/88 (49%) |
| Laika | 0/88 (0%) | 20/88 (23%) |
| Glovo Kaufland | 0 | 18/88 (20%) |
| Glovo Billa | 0 | 7/88 (8%) |
| Glovo CBA | 0 | 11/88 (12%) |
| Glovo Fantastico | 0 | 49/88 (56%) |
| Claude валидация | JSON грешка | 16 премахнати, 10 флагнати, 12 OK |

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
