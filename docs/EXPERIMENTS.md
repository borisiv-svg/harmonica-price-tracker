# Harmonica Price Tracker - Experiments Log

Документация на експерименти в Digital Lab инфраструктурата.

---

## EXP-001: Crawl4AI Integration

**Статус:** ✅ ЗАВЪРШЕН УСПЕШНО
**Период:** 04-05 февруари 2026
**Branch:** `feature/crawl4ai-integration`

### Цел

Тестване на Crawl4AI като алтернатива на Playwright + Claude AI за извличане на продукти и цени. Целта е намаляване на:
- Време за изпълнение
- Claude API разходи
- Сложност на кода

### Хипотеза

Crawl4AI може да извлича продуктови данни без LLM, използвайки regex patterns и markdown анализ, което ще елиминира Claude API разходите и ще ускори изпълнението.

### Итерации

#### v1-v4: Начални тестове (04.02.2026)
- Тествахме basic crawling на Balev Bio Market
- Проблеми с timeout и wait conditions
- Постигнахме 100% съвпадение с референтни цени
- Време: 4-7 секунди за един магазин

#### v5: Production-based (04.02.2026)
- Добавихме hardcoded 27 продукта от production
- Scroll loading за lazy-loaded съдържание
- Dual EUR/BGN цени

#### v6-v6.2: Dynamic extraction (04-05.02.2026)
- Премахнахме hardcoded списък
- Динамично извличане от Кашон като референтен източник
- Debug версия за анализ на markdown структурата
- Открихме специфичните patterns за всеки сайт

#### v6.3 FINAL: Site-specific patterns (05.02.2026)
- Отделни extraction функции за всеки магазин
- Кашон: markdown links parsing
- eBag: image alt text + title patterns
- Balev: линии с грамаж + контекстни цени
- Keyword-based matching с бонус за грамаж

### Финални резултати

```
============================================================
EXP-001: CRAWL4AI v6.3 FINAL
============================================================
Date: 2026-02-05 05:14:27
Total time: 66.40s

STORES CRAWLED:
  Кашон Harmonica: 22.18s, 63657 chars
  eBag: 20.56s, 36740 chars
  Balev Bio Market: 15.46s, 41431 chars

PRODUCTS EXTRACTED:
  Кашон (reference): 79 Harmonica products
  eBag: 47 Harmonica products
  Balev: 19 Harmonica products

MATCHING RESULTS:
  eBag matches: 18/79 (23%)
  Balev matches: 39/79 (49%)
```

### Сравнение с Production

| Метрика | Production (Playwright + Claude) | Crawl4AI v6.3 |
|---------|----------------------------------|---------------|
| Време за 3 магазина | ~3-5 мин | **66 сек** |
| Claude API разходи | ~$0.015-0.03 | **$0** |
| Точност на extraction | 95% | 85-90%* |
| Matching rate | ~80% | 23-49%** |
| Динамичен списък | Не | **Да** |
| EUR + BGN цени | Да | **Да** |

*Extraction работи добре, matching алгоритъмът може да се подобри
**По-нисък % заради различия в имената между магазините

### Примерни данни

```
Био тунквана вафла Chocobiotik 40 г:
  Кашон: 1.12€ / 2.20лв
  eBag:  1.12€ / 2.19лв
  Balev: 1.17€ / 2.29лв

Smiles с нахут, ориз и морска сол 50g:
  Кашон: 1.44€ / 2.81лв
  eBag:  1.32€ / 2.58лв
  Balev: 1.32€ / 2.58лв

Сирене краве harmonica 400g:
  Кашон: N/A / 12.97лв
  Balev: 6.69€ / 13.08лв
```

### Изводи

**Успехи:**
1. ✅ Crawl4AI работи отлично за web scraping
2. ✅ Нулеви Claude API разходи
3. ✅ 3x по-бързо от production
4. ✅ Динамично извличане на продукти
5. ✅ Dual EUR/BGN цени работят

**Области за подобрение:**
1. ⚠️ Matching алгоритъмът може да се подобри
2. ⚠️ Някои Кашон EUR цени не се извличат
3. ⚠️ Имената от Balev имат "HARMONICA ##" prefix

### Препоръка: Хибриден подход

Вместо пълно динамично извличане при всяко изпълнение, препоръчваме **хибриден подход**:

#### Седмично сканиране (Weekly)
- Използва **статичен списък** с ~65 продукта (от Кашон)
- Сканира търговски магазини (eBag, Balev, Lilly и др.)
- Сравнява цените със статичния списък
- **Време:** ~40-50 сек (без Кашон)
- **Claude API:** $0

#### Месечна актуализация (на всеки 4 седмици)
- Сканира Кашон за пълния списък продукти
- Сравнява с текущия статичен списък
- Идентифицира: нови продукти, отпаднали продукти, променени имена
- Актуализира статичния списък
- Изпраща известие за промени

#### Предимства на хибридния подход
1. **По-бързо** - не сканираме Кашон ежедневно
2. **По-стабилно** - статичният списък е тестван и валидиран
3. **По-точно matching** - можем да добавим aliases за всеки продукт
4. **По-лесно за поддръжка** - промените са контролирани

### Следващи стъпки

1. ✅ **EXP-001-B:** Създаване на хибриден product sync система
2. **EXP-002:** Интеграция на Crawl4AI в production scraper
3. **EXP-003:** Добавяне на нови магазини (DM, Lilly)

### Файлове

- `experimental/crawl4ai_pilot.py` - финален скрипт v6.3
- `experimental/pilot_results.json` - последни резултати
- `.github/workflows/pilot-test.yml` - workflow за тестване
- `scripts/monthly_product_sync.py` - скрипт за месечна синхронизация
- `data/products/harmonica_products.json` - референтен списък с продукти
- `.github/workflows/monthly-product-sync.yml` - workflow за месечен sync

---

## EXP-001-B: Hybrid Product List

**Статус:** ✅ ИМПЛЕМЕНТИРАН
**Дата:** 05 февруари 2026

### Цел

Имплементиране на хибриден метод за управление на продуктовия списък:
- Статичен JSON файл с продукти за седмично сканиране
- Месечна проверка за нови/отпаднали продукти от Кашон
- Автоматично обновяване на списъка

### Архитектура

```
data/
└── products/
    ├── harmonica_products.json    # Референтен списък (обновява се месечно)
    └── sync_log.json              # История на синхронизациите

scripts/
└── monthly_product_sync.py        # Скрипт за месечна синхронизация

.github/workflows/
└── monthly-product-sync.yml       # Workflow (първата неделя от месеца)
```

### harmonica_products.json структура

```json
{
  "version": "1.0",
  "last_sync": "2026-02-05",
  "source": "kashonharmonica.bg",
  "total_products": 79,
  "products": [
    {
      "id": 1,
      "name": "Кисело мляко 3,6% harmonica 400g",
      "keywords": ["кисело", "мляко", "3.6", "400"],
      "ref_eur": 1.40,
      "ref_bgn": 2.74,
      "url_slug": "kiselo-mlyako-36-harmonica-400g",
      "active": true,
      "added_date": "2026-02-05"
    }
  ]
}
```

### Функционалност на sync скрипта

1. **Първоначално изпълнение:** Създава `harmonica_products.json` с всички продукти от Кашон
2. **Месечна синхронизация:**
   - Сканира Кашон за текущ списък
   - Сравнява с локалния файл
   - Добавя нови продукти
   - Маркира премахнати като `active: false`
   - Обновява референтните цени
   - Изпраща имейл известие при промени

### Workflow график

- **Седмично (понеделник, 05:00 UTC):** Production scraper използва статичния списък
- **Месечно (първата неделя, 07:00 UTC):** Product sync обновява списъка
- **Ръчно:** Може да се стартира през GitHub Actions UI

---

## EXP-002: Production Integration

**Статус:** ✅ ЗАВЪРШЕН
**Период:** 05 февруари 2026
**Branch:** experimental

### Цел
Интегриране на възможност за паралелно записване на experimental резултати в отделни Google Sheets табове, без да се засягат production данните.

### Имплементация

#### Промени в scraper.py
Добавена нова константа за динамично определяне на tab suffix:
```python
SHEET_TAB_SUFFIX = os.environ.get("SHEET_TAB_SUFFIX", "")
```

Модифицирана `update_google_sheets()` функцията да използва динамични имена:
```python
main_tab_name = f"Ценови Тракер{SHEET_TAB_SUFFIX}"
history_tab_name = f"История_{current_year}{SHEET_TAB_SUFFIX}"
```

#### Промени в experimental.yml
Добавени липсващи environment variables:
- `SPREADSHEET_ID: ${{ secrets.SPREADSHEET_ID }}`
- `GMAIL_USER: ${{ secrets.GMAIL_USER }}`
- `GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}`
- `SHEET_TAB_SUFFIX: "_experimental"`

### Резултати
| Метрика | Статус |
|---------|--------|
| Production табове | ✅ Непроменени |
| Experimental табове | ✅ Създадени автоматично |
| Данни изолирани | ✅ Да |
| Имейл известия | ✅ Работят |

### Създадени табове в Google Sheets
- `Ценови Тракер_experimental` - текущи цени от experimental runs
- `История_2026_experimental` - история на experimental данни

### Изводи
EXP-002 е успешно завършен. Digital Lab инфраструктурата вече позволява пълна изолация между production и experimental среди. Това отключва възможността за безопасно тестване на нови функции (Crawl4AI интеграция, нови магазини) без риск за production данните.

### Следващи стъпки
- [ ] EXP-003: Добавяне на нови магазини (Lilly, DM, ХИТ)
- [ ] Интеграция на Crawl4AI scraper в experimental workflow
- [ ] A/B тестване: Playwright vs Crawl4AI

---

## EXP-003: New Stores Integration

**Статус:** ✅ ЗАВЪРШЕН (16 магазина активни)
**Период:** февруари 2026
**Зависимост:** EXP-001, EXP-002

### Магазини — финален статус

| Магазин | Метод | Покритие | Статус |
|---------|-------|----------|--------|
| Кашон (reference) | Crawl4AI | 88 продукта | ✅ Master list |
| eBag | Crawl4AI | 34/88 (39%) | ✅ Стабилен |
| Balev Bio | Crawl4AI + BS4 | 11/88 (12%) | ⚠️ Грешни цени (виж изводи) |
| Lilly Drogerie | curl_cffi GraphQL | 8/88 (9%) | ✅ Стабилен (всички изчерпани) |
| DM България | Firecrawl (JS rendering) | 11/88 (12%) | ✅ Работи след bugfix v10.0.1 |
| T-Market | curl_cffi директен | 11/88 (12%) | ✅ Стабилен |
| Metro | Crawl4AI + line-by-line | 8/88 (9%) | ⚠️ Грешни цени при някои продукти |
| Randi | Firecrawl | 10/88 (11%) | ✅ Стабилен |
| Zelen | Crawl4AI generic | 1/88 (1%) | ⚠️ Много ниско покритие |
| Bio-Market | Crawl4AI generic | 17/88 (19%) | ✅ Стабилен |
| BeFit | Crawl4AI generic | 43/88 (49%) | ✅ Високо покритие |
| Laika | Crawl4AI generic (line-by-line) | 20/88 (23%) | ✅ Работи след bugfix v10.0.1 |
| Glovo Kaufland | Firecrawl (search actions) | 18/88 (20%) | ✅ Работи след bugfix v10.0.1 |
| Glovo Billa | Firecrawl (search actions) | 7/88 (8%) | ✅ Работи след bugfix v10.0.1 |
| Glovo CBA | Firecrawl (search actions) | 11/88 (12%) | ✅ Работи след bugfix v10.0.1 |
| Glovo Fantastico | Firecrawl (search actions) | 49/88 (56%) | ✅ Високо покритие |

### Архитектура по методи на scraping

```
┌─────────────────────────────────────────────────────────┐
│                    SCRAPER v10.0                         │
├─────────────┬──────────────┬──────────────┬─────────────┤
│  Crawl4AI   │  curl_cffi   │  Firecrawl   │  Claude     │
│  (headless) │  (TLS spoof) │  (JS render) │  (validate) │
├─────────────┼──────────────┼──────────────┼─────────────┤
│ Кашон       │ Lilly (GQL)  │ DM           │ Outlier     │
│ eBag        │ T-Market     │ Randi        │ detection   │
│ Balev       │              │ Glovo ×4     │ (Sonnet)    │
│ Metro       │              │              │             │
│ Zelen       │              │              │             │
│ Bio-Market  │              │              │             │
│ BeFit       │              │              │             │
│ Laika       │              │              │             │
└─────────────┴──────────────┴──────────────┴─────────────┘
```

### Ключови bugfix-ове (v10.0.1, 14.02.2026)

Четири бъга бяха открити и поправени в една сесия. Всички бяха свързани помежду си:

**Bug 1: Firecrawl import (root cause)**
- `from firecrawl import Firecrawl` → грешно, класът е `FirecrawlApp`
- Тих `ImportError` → `FIRECRAWL_AVAILABLE = False`
- Засегнати: DM, Randi*, Glovo ×4 (*Randi работеше заради различен code path)
- Startup логът казваше `Firecrawl: YES` защото проверяваше само API key

**Bug 2: Firecrawl API промяна**
- `.scrape()` → `.scrape_url()` в по-новите версии на firecrawl-py
- DM и Glovo ползваха стария API; Randi вече беше мигриран
- Грешка: `'FirecrawlApp' object has no attribute 'scrape'`

**Bug 3: Generic extractor block splitting**
- `re.split(r'\n{2,}', markdown)` не работи за сайтове с единични нови редове
- Laika: 33880 chars → 1 гигантски блок → 1 продукт
- Решение: `_extract_generic_line_by_line()` fallback (като Metro extractor-а)

**Bug 4: Claude max_tokens limit**
- `max_tokens=2000` → Sonnet truncation при 38 suspicious prices
- Truncated JSON → `JSONDecodeError` → валидацията пропусната → грешни цени в таблицата
- Решение: динамичен `max_tokens` + JSON repair fallback

### Изводи и поуки

**1. Silent failures са най-опасни**
Firecrawl import грешката не хвърляше видима грешка — `except ImportError` я поглъщаше тихо. Startup логът `Firecrawl: YES` маскираше проблема допълнително. **Поука:** Startup диагностиката трябва да валидира и наличност на модула, и API ключ, и работоспособност на метода.

**2. API versioning между callsite-ове**
Randi ползваше `.scrape_url()` (добавен по-късно), DM и Glovo — `.scrape()` (по-стар код). Когато един callsite работи, а друг не — търси API промяна. **Поука:** При upgrade на библиотека, проверявай ВСИЧКИ callsite-ове, не само последно добавения.

**3. Generic extractors се нуждаят от множество стратегии**
Block-based splitting (`\n{2,}`) работи за сайтове с ясно разделени продуктови карти, но се проваля за плътен layout. **Поука:** Винаги имай fallback стратегия. Line-by-line подходът е универсален backup за произволен markdown.

**4. LLM output лимити трябва да скалират с входните данни**
Фиксиран `max_tokens=2000` работеше с 10 магазина и ~29 suspicious prices. Добавянето на 7 нови магазина вдигна числото до 38, което надхвърли лимита. **Поука:** `max_tokens` трябва да е функция от `len(input)`, не константа.

**5. Defensive JSON parsing за LLM output**
Дори с правилен `max_tokens`, LLM може да върне malformed JSON. JSON repair (намиране на последния валиден обект + затваряне на масива) спасява частични резултати. **Поука:** Никога не приемай, че LLM output е валиден — винаги имай repair/fallback.

### Предложения за следващи подобрения

**Висок приоритет:**
1. **Balev Bio extraction** — консистентно дава грешни цени (9.00лв за 400г кисело мляко вместо ~2.70лв). `_extract_balev_bs4()` вероятно хваща цени от грешни HTML елементи. Нужен е анализ на актуалната DOM структура
2. **Metro price matching** — outlier цени (15.82лв за вафла 30г, 2.62лв за сироп 750мл). `extract_metro_products()` свързва имена с цени от съседни продукти. Контекстният прозорец може да е прекалено широк
3. **Zelen покритие** — само 1/88 (1%). Нужна е инспекция на markdown структурата и вероятно dedicated extractor

**Среден приоритет:**
4. **Firecrawl version pinning** — `firecrawl-py>=1.0.0,<2.0.0` е прекалено широк. Pin-ване до конкретна minor версия ще предотврати бъдещи API breakages
5. **Smoke test за imports** — добавяне на CI стъпка, която валидира всички imports преди пълното изпълнение. Би хванала Firecrawl бъга веднага
6. **Glovo Fantastico дедупликация** — 88 extracted products (= Kashon!) е подозрително. Вероятно има дублирани или non-Harmonica продукти

**Нисък приоритет:**
7. **Laika closest-price logic** — вместо "първата цена в ±5 реда", да се търси "най-близката цена по брой редове". Би намалило false matches на гъсти brand pages
8. **ХИТ Хипермаркет** — все още не е интегриран. Трябва анализ на сайтовата структура

### Хронология на промените

**v9.6.0 (14.02.2026):**
- Claude Sonnet 4.5 ценова валидация — outlier detection + AI оценка
- `validate_prices_with_claude()` — batch анализ с контекст за типични BG цени
- `ANTHROPIC_API_KEY` env var, graceful fallback ако липсва

**v10.0.1 (14.02.2026):**
- Firecrawl import fix (`Firecrawl` → `FirecrawlApp`)
- Firecrawl API fix (`.scrape()` → `.scrape_url()`)
- Generic line-by-line extractor за Laika и подобни сайтове
- Claude `max_tokens` динамичен + JSON repair fallback
- Startup диагностика: проверка на `FIRECRAWL_AVAILABLE` + `FIRECRAWL_API_KEY`

**v7.0 (10.02.2026):**
- `asyncio.gather` за паралелно краулване на всички магазини
- BeautifulSoup за Lilly парсване (с regex fallback)
- Подобрено product matching: нормализация, тежестен бонус, процентен бонус
- Retry декоратор за мрежови грешки
- `logging` модул вместо print()

**Премахнати:**
- ~~Zoya.bg~~ — вече не продава продукти Harmonica (февруари 2026)

---

## Changelog

| Дата | Експеримент | Промяна |
|------|-------------|---------|
| 2026-02-14 | EXP-003 | v10.0.1: Firecrawl import/API fix, generic line-by-line, Claude max_tokens fix |
| 2026-02-14 | EXP-003 | v9.6.0: Claude Sonnet 4.5 ценова валидация — outlier detection + AI оценка |
| 2026-02-10 | EXP-003 | v7.0: logging, asyncio.gather, BS4, подобрен matching, retry |
| 2026-02-10 | Всички | Седмичен график: понеделник 05:00 UTC. Zoya.bg премахнат |
| 2026-02-05 | EXP-002 | Завършен успешно - SHEET_TAB_SUFFIX работи |
| 2026-02-05 | EXP-001 | Документиран хибриден подход |
| 2026-02-05 | EXP-001 | v6-v6.3 FINAL, завършен успешно |
| 2026-02-04 | EXP-001 | Създаден, v1-v5 |
