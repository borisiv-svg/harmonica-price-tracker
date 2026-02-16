# Roadmap & Lessons Learned — Harmonica Price Tracker

Последна актуализация: 2026-02-16 (v10.6.1)

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

### Фаза 1: Тестова инфраструктура (приоритет: КРИТИЧЕН)

**Цел:** Хващане на import/parse грешки преди production run.

**Задачи:**
- [ ] Създаване на `tests/` директория с `pytest` конфигурация
- [ ] `test_imports.py` — проверка че всички 18 модула се импортират
- [ ] `test_extractors.py` — всеки extractor парсва markdown fixture от `tests/fixtures/`
- [ ] `test_matching.py` — keyword matching с известни продукти
- [ ] `test_utils.py` — `extract_price()`, `clean_product_name()`, food filter
- [ ] Добавяне на `pytest` стъпка в `production.yml` преди scrape
- [ ] Markdown fixtures: по 1 примерен файл за всеки магазин (от реални crawl-ове)

**Очакван резултат:** 4 от последните 6 бъга щяха да бъдат хванати преди deploy.

### Фаза 2: Dry-run режим

**Цел:** Бърза верификация след промени без 6-минутен production run.

**Задачи:**
- [ ] `python scraper.py --dry-run` — краули 2-3 магазина (Кашон + eBag + 1 generic)
- [ ] Skip Google Sheets и email
- [ ] Принтира summary: брой продукти, matched, валидирани
- [ ] Exit code 0 при успех, 1 при 0 продукта от някой магазин

**Очакван резултат:** Верификация за 30-60 секунди вместо 6 минути.

### Фаза 3: Dependency pinning

**Цел:** Предотвратяване на API breaking changes от upstream библиотеки.

**Задачи:**
- [ ] Pin точни версии в `requirements.txt` (firecrawl-py==X.Y.Z, crawl4ai==X.Y.Z)
- [ ] `pip freeze > requirements.lock` генериран от CI при успешен run
- [ ] Dependabot / Renovate за контролирани upgrades с PR

**Очакван резултат:** Firecrawl няма да се счупи тихо при нова версия.

### Фаза 4: Store health мониторинг

**Цел:** Автоматично откриване на деградация по магазини.

**Задачи:**
- [ ] `data/run_history.json` — запис на брой продукти по магазин при всеки run
- [ ] Alert логика: ако магазин върне 0 продукта ИЛИ >50% спад спрямо предишен run
- [ ] Включване на health summary в email отчета
- [ ] Генерализиране на Zelen debug logging за всички магазини при anomaly

**Очакван резултат:** Проблеми с конкретен магазин се виждат веднага, не при ръчна проверка на Sheet-а.

### Фаза 5: Zelen deep-dive

**Цел:** Разбиране защо Zelen връща малко продукти и стабилизиране.

**Задачи:**
- [ ] Анализ на `data/zelen_debug.md` след следващия production run
- [ ] Определяне на root cause: crawl (непълно зареждане), extract (regex miss), или match (naming mismatch)
- [ ] Fix на конкретния проблем
- [ ] Добавяне на Zelen fixture в тестовете (от Фаза 1)

**Очакван резултат:** Zelen стабилно над 20 продукта при всеки run.

---

## Текущо състояние (v10.6.1)

| Метрика | Стойност |
|---------|----------|
| Магазини | 15 (Кашон, eBag, Balev, Lilly, T-Market, Metro, Zelen, Randi, Bio-Market, BeFit, Laika, Glovo ×4) |
| Продукти | 88 в reference list |
| Runtime | ~366 секунди |
| Модули | 18 (scraper.py + config, utils, products, matching, validation, 9 extractors, 4 fetchers, 2 output) |
| Fallback верига | Firecrawl → Crawl4AI → curl_cffi |
| Валидация | Claude Sonnet 4.5 ценова проверка |
| Schedule | Понеделник 07:00 BG time |

---

## Приоритетен ред

```
Фаза 1 (тестове) ━━━ отключва безопасни промени
       ↓
Фаза 2 (dry-run) ━━━ ускорява development цикъла
       ↓
Фаза 3 (pinning) ━━━ стабилизира dependencies
       ↓
Фаза 4 (health)  ━━━ проактивен мониторинг
       ↓
Фаза 5 (Zelen)   ━━━ конкретен store fix
```

Фаза 1 е prerequisite за всичко останало — без тестове всяка промяна е blind deploy.
