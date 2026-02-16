# Roadmap & Lessons Learned — Harmonica Price Tracker

Последна актуализация: 2026-02-16 (v10.13.0)

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

## Текущо състояние (v10.13.0)

| Метрика | Стойност |
|---------|----------|
| Магазини | 15 (Кашон, eBag, Balev, Lilly, T-Market, Metro, Zelen, Randi, Bio-Market, BeFit, Laika, Glovo ×4) |
| Продукти | 39 активни + 75 removed (очаква се ~114 активни след re-activation при следващ пълен Кашон crawl) |
| Runtime | ~330 секунди (production), ~30 секунди (dry-run) |
| Модули | 20 (scraper.py + config, utils, products, matching, validation, run_history, price_history, 9 extractors, 4 fetchers, 2 output) |
| Тестове | 180 (pytest), ~0.7s |
| Dependencies | 10 пакета, всички pinned + Dependabot за auto-upgrade PR |
| Fallback верига | Firecrawl → Crawl4AI → curl_cffi (GraphQL за Lilly) |
| Валидация | Claude Sonnet 4.5 ценова проверка |
| Health monitoring | run_history.json + auto-alert при 0 или >50% спад |
| Price history | price_history.json (local) + История_{year} tab (Sheets) |
| Schedule | Понеделник 07:00 BG time |

### Известни проблеми (от production run 2026-02-16)

| Проблем | Детайли | Приоритет |
|---------|---------|-----------|
| **T-Market Cloudflare** | Блокиран напълно — Firecrawl timeout + Crawl4AI captcha fail + curl_cffi 403. 0/39 продукта | Висок |
| **Glovo Kaufland** | Firecrawl actions fail: "All scraping engines failed". 0/39 продукта | Среден |
| **Firecrawl масови timeouts** | 5/11 магазина timeout (T-Market, eBag, Balev, Zelen, Bio-Market). Crawl4AI fallback спасява 4/5 | Нисък (fallback работи) |
| **BeFit Firecrawl actions** | "Element not found" — selector проблем. Crawl4AI fallback OK | Нисък |
| **Lilly Firecrawl** | Firecrawl+BS4 дава само 1 продукт, GraphQL дава 11 (всички изчерпани) | Нисък (GraphQL работи) |
| **Version string** | Показваше v10.8 вместо v10.12 — фикснато | Фикснато |

### Покритие по магазин (2026-02-16)

```
Кашон             ████████████████████████████████████████████████  97% (38/39)
Glovo Fantastico  ████████████████████████                          49% (19/39)
eBag              ██████████████████████                            44% (17/39)
BeFit             ██████████████████                                36% (14/39)
Balev Bio         ██████████████                                    28% (11/39)
Bio-Market        ██████████████                                    28% (11/39)
Zelen             ████████████                                      23% (9/39)
Glovo CBA         ████████                                          15% (6/39)
Randi             █████                                             10% (4/39)
Lilly             █████                                             10% (4/39) — изчерпани
Glovo Billa       █████                                             10% (4/39)
Metro             ███                                                5% (2/39)
Laika             ███                                                5% (2/39)
T-Market          ░                                                  0% (0/39) — Cloudflare
Glovo Kaufland    ░                                                  0% (0/39) — scrape fail
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
Фаза 6 (тестове)       ━━━ ЗАВЪРШЕНА ✓  168 теста, products + output покрити
       ↓
Фаза 7 (DM)            ━━━ ОТЛОЖЕНА     достатъчно магазини (15)
       ↓
Фаза 8 (CI dry-run)    ━━━ ЗАВЪРШЕНА ✓  fail-fast + annotation + step summary
       ↓
Фаза 9 (deps)          ━━━ ЗАВЪРШЕНА ✓  Dependabot за pip + github-actions
       ↓
Фаза 10 (analytics)    ━━━ ЗАВЪРШЕНА ✓  price_history.json + История tab възстановен
       ↓
Фаза 10.5 (re-activation) ━━━ ЗАВЪРШЕНА ✓  двупосочен product lifecycle, 75 продукта ще се възстановят
```

Всички 11 фази от roadmap-а са завършени.

---

## Следващи стъпки

### Фаза 11: T-Market — нов scraping подход

**Статус:** Планирана

**Проблем:** Cloudflare блокира всички три fallback метода (Firecrawl timeout, Crawl4AI captcha fail, curl_cffi 403).

**Възможни решения:**
- [ ] Намиране на T-Market REST/GraphQL API (подобно на Lilly)
- [ ] Cloudflare bypass с managed browser (capsolver integration подобрение)
- [ ] Премахване от мониторинга ако остане нерешим

### Фаза 12: Glovo Kaufland stabilization

**Статус:** Планирана

**Проблем:** Firecrawl search-actions fail: "All scraping engines failed".

**Възможни решения:**
- [ ] Debug на Firecrawl actions sequence за Kaufland
- [ ] Glovo REST API директен достъп (подобно на Lilly GraphQL)

### Фаза 13: Сутрешен vs вечерен benchmark

**Статус:** В ход — сравнителен run планиран за 2026-02-17 сутринта

**Цел:** Определяне дали Firecrawl timeout-ите (5/11 = 45%) са свързани с натовареност или системен проблем.
