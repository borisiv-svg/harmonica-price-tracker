# Roadmap & Lessons Learned — Harmonica Price Tracker

Последна актуализация: 2026-02-16 (v10.8.0)

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

### Фаза 5: Zelen deep-dive

**Цел:** Разбиране защо Zelen връща малко продукти и стабилизиране.

**Задачи:**
- [ ] Анализ на `data/zelen_debug.md` след следващия production run
- [ ] Определяне на root cause: crawl (непълно зареждане), extract (regex miss), или match (naming mismatch)
- [ ] Fix на конкретния проблем
- [ ] Добавяне на Zelen fixture в тестовете (от Фаза 1)

**Очакван резултат:** Zelen стабилно над 20 продукта при всеки run.

---

## Текущо състояние (v10.8.0)

| Метрика | Стойност |
|---------|----------|
| Магазини | 15 (Кашон, eBag, Balev, Lilly, T-Market, Metro, Zelen, Randi, Bio-Market, BeFit, Laika, Glovo ×4) |
| Продукти | 88 в reference list |
| Runtime | ~366 секунди (production), ~30 секунди (dry-run) |
| Модули | 19 (scraper.py + config, utils, products, matching, validation, run_history, 9 extractors, 4 fetchers, 2 output) |
| Тестове | 134 (pytest), 0.86s |
| Dependencies | 10 пакета, всички pinned |
| Fallback верига | Firecrawl → Crawl4AI → curl_cffi |
| Валидация | Claude Sonnet 4.5 ценова проверка |
| Health monitoring | run_history.json + auto-alert при 0 или >50% спад |
| Schedule | Понеделник 07:00 BG time |

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
Фаза 5 (Zelen)   ━━━ ПРЕДСТОИ    debug markdown анализ
```

Следваща стъпка: Фаза 5 (Zelen deep-dive) — анализ на debug markdown и стабилизиране.
