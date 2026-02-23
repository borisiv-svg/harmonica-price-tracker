# Roadmap & Lessons Learned — Harmonica Price Tracker

Последна актуализация: 2026-02-17 (v10.14.1)

---

## Изводи от последните сесии (v10.0 — v10.6.1)

### 1. Import грешките са най-честият production failure

| Версия | Бъг | Причина |
|--------|-----|---------|
| v10.0.1 | `Firecrawl` вместо `FirecrawlApp` | Грешно име на клас — silent `ImportError` |
| v10.0.1 | `.scrape()` → `.scrape_url()` | Firecrawl API breaking change |
| v10.6.1 | `BrowserConfig is not defined` | Star import cleanup пропусна crawl4ai класове |

**Извод:** Без тестове всяка import грешка стига до production. Silent failures (`try/except` с `AVAILABLE = False`) крият проблема с дни.

### 2. Голям refactor без тестове е рисков

Модуляризацията v10.6 (4,573 → 650 реда) беше необходима, но веднага след нея се появи v10.6.1 hotfix. При 18 нови модула и десетки пренесени функции, ръчната верификация е недостатъчна.

**Извод:** Преди следващ голям refactor — първо smoke tests.

### 3. Fallback chains са най-ценната архитектурна инвестиция

- Firecrawl → Crawl4AI → curl_cffi спасява данните при timeout/block
- `brand_page=False` retry увеличи Zelen от 1 на 32 продукта
- `unmergeCells` изолация предотврати загуба на цялото форматиране

**Извод:** Продължаваме да добавяме fallback-и, не да разчитаме на един метод.

### 4. LLM стъпките изискват defensive coding

Claude валидацията с фиксиран `max_tokens=2000` доведе до JSON truncation при повече магазини. Динамичното оразмеряване (`len(suspicious) * 150 + 500`) реши проблема.

**Извод:** Всяка LLM стъпка трябва да има: динамичен sizing, JSON repair fallback, graceful skip при грешка.

### 5. Google Sheets API batch операциите трябва да са изолирани

Един невалиден `unmergeCells` range блокира 138 форматиращи заявки. Решение: отделен `batch_update` + `try/except`.

**Извод:** Критични Sheets операции — в отделни batch-ове с независим error handling.

### 6. Еднопосочен product lifecycle води до тиха загуба на данни (v10.13.0)

Кашон (kashonharmonica.bg) е infinite scroll сайт с ~85+ продукта. Конфигурацията изисква 40 scroll-а × 3s = 120s чисто скролиране. Но:

- **Firecrawl лимити**: max 50 actions → 17/40 scrolls → вижда само горната половина
- **Crawl4AI**: прави всичките 40 scroll-а, но отнема 134s и понякога timeout-ва

При непълно зареждане на Кашон (17 вместо 40 scrolls), продукти от долната част на страницата не се виждат. Старата логика в `update_product_list_with_new()` имаше **еднопосочен lifecycle**:

```
active → removed (ако не е намерен в Кашон)
removed → ❌ НИКОГА обратно в active
```

Продуктите попадаха в `_all_loaded_products` като removed и функцията ги пропускаше, защото проверяваше срещу **всички** имена (ред 70-71). Резултат: **75 от 114 продукта** (66%) бяха неправилно деактивирани за 2 run-а (2026-02-05 и 2026-02-15).

**Fix (v10.13.0):** Двупосочен lifecycle с re-activation:

```
active → removed (ако не е в Кашон)
removed → reactivated → active (ако се появи отново)
```

Ключовата промяна: вместо `all_names_lower` (active + removed), сега се поддържа отделен `removed_map` за re-activation. Когато Кашон продукт съвпадне с removed запис: `active=True`, `status="reactivated"`, цената се обновява.

**Извод:** Всеки автоматичен процес, който маркира данни като невалидни, **трябва** да има обратен път за възстановяване. Особено когато source-ът (Кашон) е ненадежден (infinite scroll, timeout-и, непълно зареждане). Тихата загуба на продукти е по-опасна от фалшиво положителни, защото никога не генерира alert — health monitoring следи магазини, не reference list.

---

## План за действие

### Фаза 1: Тестова инфраструктура — ЗАВЪРШЕНА (v10.7.0)

**Цел:** Хващане на import/parse грешки преди production run.

**Задачи:**
- [x] Създаване на `tests/` директория с `pytest` конфигурация
- [x] `test_imports.py` — 11 теста, проверка че всички 18 модула се импортират
- [x] `test_extractors.py` — 25 теста, 6 extractors с markdown fixtures
- [x] `test_matching.py` — 22 теста, keyword matching с известни продукти
- [x] `test_utils.py` — 30 теста, price extraction, name cleaning, food filter
- [x] Добавяне на `pytest` стъпка в `production.yml` преди scrape
- [x] 6 markdown fixtures в `tests/fixtures/` (kashon, ebag, balev, metro, randi, generic)

**Резултат:** 113 теста, 0.29s runtime. Интегрирани в CI pipeline.

### Фаза 2: Dry-run режим — ЗАВЪРШЕНА (v10.7.0)

**Цел:** Бърза верификация след промени без 6-минутен production run.

**Задачи:**
- [x] `python scraper.py --dry-run` — краули Кашон + eBag + Balev
- [x] Skip Google Sheets и email
- [x] Принтира summary: брой продукти, matched по магазин, време
- [x] Exit code 0 при успех, 1 при 0 matched от eBag или Balev
- [x] `crawl_all(only_stores=...)` — параметър за селективно краулване

**Резултат:** Верификация за ~30 секунди вместо 6 минути. Glovo автоматично се пропуска.

### Фаза 3: Dependency pinning — ЗАВЪРШЕНА (v10.7.0)

**Цел:** Предотвратяване на API breaking changes от upstream библиотеки.

**Задачи:**
- [x] Pin точни версии в `requirements.txt` за всички 10 пакета
- [ ] Dependabot / Renovate за контролирани upgrades с PR (бъдещо)

**Резултат:** anthropic==0.79.0, crawl4ai==0.8.0, curl_cffi==0.14.0, capsolver==1.0.7. При upgrade — ръчна промяна + dry-run + тестове преди merge.

### Фаза 4: Store health мониторинг — ЗАВЪРШЕНА (v10.8.0)

**Цел:** Автоматично откриване на деградация по магазини.

**Задачи:**
- [x] `data/run_history.json` — запис на брой продукти по магазин при всеки run
- [x] Alert логика: ако магазин върне 0 продукта ИЛИ >50% спад спрямо предишен run
- [x] Включване на health summary в email отчета
- [x] Генерализиране на Zelen debug logging за всички магазини при anomaly

**Резултат:** `run_history.py` модул с 21 теста. Health alerts в лог + имейл. Debug markdown за всички проблемни магазини.

### Фаза 5: Zelen deep-dive — ЗАВЪРШЕНА (v10.9.0)

**Цел:** Разбиране защо Zelen връща малко продукти и стабилизиране.

**Задачи:**
- [x] Анализ на Zelen crawl + extraction pipeline
- [x] Определяне на root cause: GDPR cookie consent overlay блокира зареждането на продукти
- [x] Fix: cookie consent handling в config (`pre_js` + `firecrawl_pre_actions`)
- [x] Fix: `_normalize_image_links()` — `[![alt](img)](url)` дубликати в generic extractor
- [x] Добавяне на Zelen fixture в тестовете (16 продукта) + 5 нови теста

**Допълнителни fixes:**
- [x] `normalize_name()` decimal kg regex order bug (1.5kg → 1500г)
- [x] Version strings обновени навсякъде (scraper.py, email footer)

**Резултат:** Cookie overlay се затваря автоматично. Image-link дубликати елиминирани. 140 теста, всички минават.

---

## Текущо състояние (v10.14.1)

| Метрика | Стойност |
|---------|----------|
| Магазини | 14 (Кашон, eBag, Balev, T-Market, Metro, Zelen, Randi, Bio-Market, BeFit, Laika, Glovo ×4) |
| Продукти | 88 активни + 28 removed |
| Runtime | ~375 секунди (production), ~30 секунди (dry-run) |
| Модули | 20 (scraper.py + config, utils, products, matching, validation, run_history, price_history, 9 extractors, 4 fetchers, 2 output) |
| Тестове | 199 (pytest), ~0.7s |
| Dependencies | 10 пакета, всички pinned + Dependabot за auto-upgrade PR |
| Fallback верига | Firecrawl → Crawl4AI → curl_cffi |
| Валидация | Claude Sonnet 4.5 ценова проверка с EUR/100g нормализация |
| Health monitoring | run_history.json + auto-alert при 0 или >50% спад |
| Price history | price_history.json (local) + История_{year} tab (Sheets) |
| Schedule | Понеделник 07:00 BG time |

### Известни проблеми (от production run 2026-02-17)

| Проблем | Детайли | Приоритет |
|---------|---------|-----------|
| **Firecrawl timeouts** | 5/10 магазина timeout на 1-ви опит. Retry с 1.5× спасява 4/5. Само 2 магазина отиват на Crawl4AI fallback | Среден |
| **Zelen Firecrawl ISE** | Internal Server Error — Crawl4AI fallback OK (3s) | Нисък |
| **BeFit Firecrawl ISE** | ISE след retry — Crawl4AI fallback OK (21.5s) | Нисък |
| **Firecrawl разходи** | ~18-20 заявки/run, може да се оптимизира чрез Crawl4AI-first (вж. Предложение A) | Среден |

### Покритие по магазин (2026-02-17)

```
Кашон             ████████████████████████████████████████████████  95% (84/88)
Glovo Fantastico  █████████████████████                             43% (38/88)
BeFit             ████████████████████                              41% (36/88)
eBag              ████████████████                                  32% (28/88)
Balev Bio         ████████████                                      24% (21/88)
Bio-Market        ███████████                                       23% (20/88)
Glovo Kaufland    ██████████                                        19% (17/88)
Glovo CBA         ███████                                           15% (13/88)
Zelen             ███████                                           14% (12/88)
T-Market          ██████                                            12% (11/88)
Randi             █████                                             10% (9/88)
Glovo Billa       ████                                               9% (8/88)
Laika             ████                                               7% (6/88)
Metro             ██                                                 3% (3/88)
```

---

## Прогрес

```
Фаза 1 (тестове) ━━━ ЗАВЪРШЕНА ✓  113 теста + CI integration
       ↓
Фаза 2 (dry-run) ━━━ ЗАВЪРШЕНА ✓  --dry-run за 30s верификация
       ↓
Фаза 3 (pinning) ━━━ ЗАВЪРШЕНА ✓  всички 10 пакета pinned
       ↓
Фаза 4 (health)  ━━━ ЗАВЪРШЕНА ✓  run_history.json + auto-alert + email
       ↓
Фаза 5 (Zelen)   ━━━ ЗАВЪРШЕНА ✓  cookie consent + image-link fix + fixture
```

Всички 5 фази от оригиналния roadmap са завършени.

---

## План за действие (v11.x)

### Фаза 6: Test coverage разширяване — ЗАВЪРШЕНА (v10.10.0)

**Цел:** Покриване на нетестираните модули и премахване на дупликация.

**Задачи:**
- [x] `test_products.py` — 15 теста за `load_product_list()`, `update_product_list_with_new()`, `save_product_list()` (JSON roundtrip, new product discovery, status management)
- [x] `conftest.py` cleanup — `load_fixture()` преместен в `tests/helpers.py`, премахнат дубликат
- [x] Smoke test за `send_email_report()` — 4 теста (без credentials, с credentials, health alerts, празен вход)
- [x] Smoke test за `write_to_sheets()` — 2 теста (gspread unavailable, extract_weight import)
- [x] `test_output.py` — `extract_weight()` — 7 unit теста

**Резултат:** 168 теста (было 140), покриващи products, output, extractors, matching, utils, run_history, imports.

### Фаза 7: DM България — ОТЛОЖЕНА

**Статус:** Отложена — достатъчно магазини (15). Може да се активира в бъдеще.

### Фаза 8: CI dry-run преди production — ЗАВЪРШЕНА (v10.11.0)

**Цел:** Dry-run в CI за ранно откриване на integration проблеми.

**Задачи:**
- [x] `--dry-run` стъпка в `production.yml` (преди реалния scrape) — краулва Кашон + eBag + Balev (~30s)
- [x] Fail-fast: ако dry-run върне exit code 1, production scrape НЕ се изпълнява
- [x] GitHub Actions error annotation (`::error::`) + Step Summary при failure
- [x] `skip_dry_run` input за manual dispatch bypass
- [x] `timeout-minutes: 30` за целия job
- [x] Version strings обновени в workflow (v10.2 → v10.10)

**Резултат:** Production run стартира само след успешен dry-run. При failure — ясно съобщение в GitHub UI + инструкции за bypass.

### Фаза 9: Dependabot интеграция — ЗАВЪРШЕНА (v10.12.0)

**Цел:** Контролирани dependency upgrades с автоматични PR.

**Задачи:**
- [x] Конфигуриране на Dependabot за `requirements.txt` (weekly schedule, сряда)
- [x] Конфигуриране на Dependabot за `github-actions` (weekly schedule, сряда)
- [x] Групиране на minor/patch updates в един PR, лимит 5 отворени PR-и
- [x] Labels: `dependencies` (pip), `ci` (actions)

**Резултат:** `.github/dependabot.yml` — зависимостите се обновяват контролирано чрез автоматични PR с review + dry-run + merge цикъл.

### Фаза 10: Ценова аналитика — ЗАВЪРШЕНА (v10.12.0)

**Цел:** Исторически анализ на ценови тенденции + възстановяване на История tab.

**Задачи:**
- [x] `price_history.py` — запис на цени по магазин в `data/price_history.json` при всеки run
- [x] `get_price_trend()` — средна цена по дата за последните N седмици
- [x] Възстановяване на `append_history_to_sheets()` в `output/sheets.py` — История_{year} tab (спряно от v10.0 refactoring)
- [x] Интеграция в `scraper.py main()` — `append_history_to_sheets()` + `record_prices()`
- [x] 10 нови теста за `price_history.py` (load/save, record, trend)
- [ ] Седмичен ценови отчет: средна цена по категория, тренд ↑/↓ (бъдещо)
- [ ] Алерт при необичайно голяма ценова промяна (>20% за седмица) (бъдещо)

**Резултат:** Ценова история се записва в local JSON + Google Sheets История_{year} tab. 178 теста, всички минават.

### Фаза 10.5: Product re-activation — ЗАВЪРШЕНА (v10.13.0)

**Цел:** Предотвратяване на тиха загуба на продукти при непълно зареждане на Кашон.

**Проблем:** 75 от 114 продукта (66%) бяха неправилно деактивирани. Еднопосочният lifecycle (`active → removed`, без обратен път) означаваше, че продукти, невидими заради непълен scroll на Кашон, изчезваха завинаги от мониторинга.

**Root cause:**
- Кашон е infinite scroll сайт: 40 scrolls × 3s = 120s
- Firecrawl лимит: max 17/40 scrolls → вижда само горната половина
- Crawl4AI: 40 scrolls = 134s, но понякога timeout-ва
- `update_product_list_with_new()` проверяваше срещу **всички** имена (active + removed) → removed продукти никога не се връщаха

**Решение:**
- [x] Двупосочен product lifecycle: `removed → reactivated → active`
- [x] Отделен `removed_map` в `update_product_list_with_new()` за бързо lookup
- [x] При re-activation: `active=True`, `status="reactivated"`, цената се обновява от Кашон
- [x] Запазване на оригиналното име и `added_date`
- [x] 3 нови теста: re-activation, case-insensitive, preservation на полета

**Резултат:** 180 теста. При следващ run с пълно зареждане на Кашон, ~75 продукта ще бъдат автоматично реактивирани.

---

## Прогрес (v11.x)

```
Фаза 6 (тестове)          ━━━ ЗАВЪРШЕНА ✓  168 теста, products + output покрити
       ↓
Фаза 7 (DM)               ━━━ ОТЛОЖЕНА     достатъчно магазини
       ↓
Фаза 8 (CI dry-run)       ━━━ ЗАВЪРШЕНА ✓  fail-fast + annotation + step summary
       ↓
Фаза 9 (deps)             ━━━ ЗАВЪРШЕНА ✓  Dependabot за pip + github-actions
       ↓
Фаза 10 (analytics)       ━━━ ЗАВЪРШЕНА ✓  price_history.json + История tab възстановен
       ↓
Фаза 10.5 (re-activation) ━━━ ЗАВЪРШЕНА ✓  двупосочен product lifecycle
       ↓
Фаза 11 (extraction)      ━━━ ЗАВЪРШЕНА ✓  bounded search, price sanity, dedup 50, "гр" matching
       ↓
Фаза 12 (reliability)     ━━━ ЗАВЪРШЕНА ✓  Lilly премахнат, Firecrawl retry, Claude EUR/100g
```

Всички 13 фази от roadmap-а са завършени.

---

### Фаза 11: Подобрена извличане на цени — ЗАВЪРШЕНА (v10.14.0)

**Цел:** Отстраняване на грешни цени и подобряване на matching.

**Задачи:**
- [x] `find_price_bounded()` — bounded forward search, спира при следващ продукт (елиминира price bleed при Balev)
- [x] `is_price_sane()` — EUR/100g валидация, отхвърля абсурдни цени (>10€/100g)
- [x] Dedup key 30→50 символа — разграничава сходни продукти ("бисквити с масло и ванилия" vs "...и шоколад")
- [x] "гр" (грам) суфикс — разпознаване навсякъде в matching, extractors и utils
- [x] 19 нови теста: `TestFindPriceBounded` (5), `TestIsPriceSane` (8), dedup (2), "гр" matching (3), extractor regression (1)

**Резултат:** 199 теста. Елиминирани фалшиви цени от Balev (price bleed) и generic extractor (абсурдни EUR/100g).

### Фаза 12: Надеждност и валидация — ЗАВЪРШЕНА (v10.14.1)

**Цел:** Намаляване на Firecrawl fallback-и и подобряване на Claude валидацията.

**Задачи:**
- [x] Премахване на Lilly от списъка (15→14 магазина) — всички продукти изчерпани, ниски цени изкривяват средните стойности
- [x] Firecrawl retry при timeout — автоматичен retry с 1.5× по-дълъг timeout преди Crawl4AI fallback
- [x] Claude валидация с EUR/100g — weight-normalized данни в prompt-а за по-прецизна аномалия детекция

**Резултат от production run 2026-02-17:**
- Firecrawl retry спаси 4/5 timeout-а (было: 5 магазина на Crawl4AI, сега: 2)
- Claude откри 10 грешни цени (+ 9 флагнати) с по-информативни обяснения (EUR/100g reasoning)
- 14/14 магазина работят, 88 продукта (2 нови)

---

## Предложения за бъдещи промени

### Предложение A: Crawl4AI-first архитектура (ПРЕПОРЪЧИТЕЛНО)

**Статус:** В обсъждане

**Цел:** Намаляване на разходите и опростяване на scraping процеса чрез обръщане на архитектурата — Crawl4AI primary, Firecrawl само за Glovo.

**Контекст — защо:**

Текущата архитектура е Firecrawl-first с ~18-20 платени API заявки на run. Анализ на production данните показва:
- Firecrawl timeout rate: **50%** на първи опит (5/10 магазина)
- Crawl4AI покрива 100% от провалите (Zelen 3s, BeFit 21.5s, Kashon upgrade)
- За много магазини Crawl4AI е **по-бърз** от Firecrawl
- Run-ът е cron job (04:23 UTC) — времето не е критично

**Анализ по магазин:**

| Магазин | JS нужен? | Anti-bot? | Crawl4AI може? | Бележка |
|---------|:---------:|:---------:|:--------------:|---------|
| Кашон | Да | Не | 100% | Вече работи като upgrade (131s) |
| eBag | Да | Не | 100% | Стандартен e-commerce |
| Balev | Да | Не | 100% | Няма Cloudflare |
| Metro | Да | Не | 100% | Стандартен HTML |
| Zelen | Да | Не | 100% | По-бърз от Firecrawl (3s vs ISE!) |
| Bio-Market | Да | Не | 100% | Стандартна brand page |
| BeFit | Да | Не | 100% | По-бърз от Firecrawl (21.5s vs ISE!) |
| Laika | Да | Не | 100% | Стандартен HTML |
| Randi | Да | Не | 95% | JS-heavy, но Crawl4AI се справя |
| T-Market | Да | **Cloudflare** | 90% | curl_cffi TLS + CapSolver fallback |
| Glovo ×4 | Да (SPA) | Не | **Не** | Нужни Firecrawl search actions ИЛИ Glovo API v3 |

**Предложена нова архитектура:**

```
Обикновени магазини (10):  Crawl4AI (primary) → curl_cffi (fallback)
T-Market:                  curl_cffi TLS → Crawl4AI + CapSolver
Glovo (4):                 Firecrawl search actions → Glovo API v3 (fallback)
```

**Очакван ефект:**

| Метрика | Сега (Firecrawl-first) | След (Crawl4AI-first) |
|---------|------------------------|----------------------|
| Firecrawl заявки/run | ~18-20 | 0-4 (само Glovo) |
| Месечен разход Firecrawl | ~$15-30 | ~$3-5 |
| Време на run | ~6 мин | ~8-10 мин |
| Надеждност | 80% Firecrawl + fallback | 95%+ Crawl4AI |

**Стъпки за имплементация:**
- [ ] Промяна на `crawl_all()` — Crawl4AI primary за 10-те обикновени магазина
- [ ] Запазване на Firecrawl само за Glovo search actions
- [ ] Опростяване на `firecrawl_fetcher.py` — махане на generic fetch
- [ ] Оптимизация на Crawl4AI scroll конфигурацията за всеки магазин
- [ ] Performance тестване — сравнение на данни преди/след
- [ ] Fallback: curl_cffi за T-Market, CapSolver за Cloudflare

**Рискове:**
- Crawl4AI е по-бавен (~1.5-2×), но run-ът не е time-critical
- Нужен headless Chrome в CI (вече наличен)
- Glovo search actions остават зависими от Firecrawl (няма Crawl4AI алтернатива)

---

### Предложение B: Без Firecrawl изобщо (максимална икономия)

**Статус:** Алтернатива — обмисля се при наличие на Glovo API v3 token

**Идея:** Пълно премахване на Firecrawl dependency. За Glovo — директен Glovo API v3.

```
Обикновени магазини (10):  Crawl4AI → curl_cffi fallback
T-Market:                  curl_cffi TLS → Crawl4AI + CapSolver
Glovo (4):                 Glovo API v3 (директен JSON)
```

**Плюсове:** Нулеви scraping разходи, без външна зависимост.
**Минуси:** Glovo API token трябва refresh, ако сменят API — няма fallback.
**Предпоставка:** Стабилен Glovo API v3 token с auto-refresh.

---

### Предложение C: Хибриден подход (минимален Firecrawl)

**Статус:** Алтернатива — компромис между A и B

**Идея:** Firecrawl само за Glovo (4 заявки). Всичко друго — Crawl4AI. Запазваме Firecrawl като backup в кода, но не го ползваме за обикновени магазини.

**Очаквани Firecrawl заявки:** от ~18 → **4** на run.

---

### Други бъдещи подобрения (NICE-TO-HAVE)

#### Per-store Firecrawl timeout tuning
- [ ] Анализ на оптимални timeout стойности по магазин (базирано на исторически данни)
- [ ] Адаптивен timeout: ако магазинът е бавен 3 пъти поред → увеличаваме базовия timeout

#### Ценови тренд алерти
- [ ] Алерт при необичайно голяма ценова промяна (>20% за седмица)
- [ ] Седмичен ценови отчет: средна цена по категория, тренд ↑/↓

#### DM България
- [ ] Algolia API интеграция (кодът вече съществува в `fetchers/curl_api.py`)
- [ ] Активиране на DM магазин при нужда
