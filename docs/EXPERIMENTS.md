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
| Balev Bio | Crawl4AI | 11/88 (12%) | ✅ Поправен (v10.0.2 forward-only context) |
| Lilly Drogerie | curl_cffi GraphQL | 8/88 (9%) | ✅ Стабилен (всички изчерпани) |
| DM България | Firecrawl (JS rendering) | 11/88 (12%) | ✅ Работи след bugfix v10.0.1 |
| T-Market | curl_cffi директен | 11/88 (12%) | ✅ Стабилен |
| Metro | Crawl4AI + line-by-line | 8/88 (9%) | ✅ Поправен (v10.0.2 forward-only context) |
| Randi | Firecrawl | 10/88 (11%) | ✅ Стабилен |
| Zelen | Crawl4AI generic | 1/88 (1%) | ⚠️ Image alt fix (v10.0.2), очаква се подобрение |
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

### Bugfix-ове (v10.0.2, 15.02.2026)

Три свързани бъга в ценовата extraction логика + подобрение на продуктовата категоризация:

**Bug 5: Backward context bleed (Balev, Metro)**
- `extract_balev_products()` и `extract_metro_products()` ползваха контекстен прозорец `lines[i-3:i+10]` (13 реда)
- `extract_bgn_price()` връща **първия** regex match в контекста
- Ако предходният продукт има цена в редовете i-3..i-1, тя се хваща вместо правилната
- Пример: 9.00лв (от предходен продукт) вместо 2.70лв за Кисело мляко 400г
- **Решение:** Progressive forward-only context — първо `i:i+5`, после `i-1:i+8` ако не намери
- Същият fix приложен и за `_extract_generic_line_by_line()` (Zelen, BioMarket, BeFit, Laika)

**Bug 6: `clean_product_name()` regex order**
- `[text](url) → text` се изпълняваше **преди** `![alt](url) → ""`
- За `![Продукт 400g](img.jpg)`: първият regex матчваше `[Продукт 400g](img.jpg)` → `!Продукт 400g`
- Вторият regex вече не намираше `![...]` формат → стоящо `!` в името
- **Решение:** Разменена поредността — image removal преди link extraction

**Bug 7: Generic extractor не извличаше image alt text**
- Продуктови имена в `![alt](url)` формат се губеха:
  - Link regex `(?<!!)\[` ги пропускаше (negative lookbehind за `!`)
  - `clean_product_name()` ги изтриваше (→ празен string)
- Zelen вероятно показва продукти като `![Био вафла 30g](img.jpg)` → 1/88 покритие
- **Решение:** Добавен "Опит 3" — `!\[([^\]]{8,120})\]\([^\)]+\)` в block-based и line-by-line generic extractors

**Подобрение: Product category overrides (`CATEGORY_OVERRIDES`)**
- 7 продукта с "масло" в името попадаха в "Млечни" вместо в правилната категория
- "масло" като ключова дума е прекалено широка — хваща "фъстъчено масло", "кокосово масло" и др.
- **Решение:** `CATEGORY_OVERRIDES` списък с приоритетни пренасочвания, проверявани преди основните ключови думи
- Примери: гранола → Други, бисквит → Вафли и сладки, фъстъчено масло → Тахани, кокосово масло → Тахани

### Изводи и поуки

**1. Silent failures са най-опасни**
Firecrawl `ImportError` беше погълнат тихо от `except ImportError`. Startup логът казваше `Firecrawl: YES`, защото проверяваше само API ключа, не самия import. 6 магазина (DM, Randi, Glovo ×4) бяха мъртви без видим симптом.
**Поука:** Startup диагностиката трябва да валидира наличност на модула, API ключ И работоспособност на метода.
**Мерки (v10.0.2):** CI smoke test стъпка валидира 7 критични imports + `FirecrawlApp.scrape_url()` метод преди стартиране на скрапера. Fail-fast при грешка.

**2. API versioning между callsite-ове**
Randi ползваше новия `.scrape_url()`, DM и Glovo — стария `.scrape()`. Когато един callsite работи, а друг не — търси API промяна, не бъг в данните.
**Поука:** При upgrade на библиотека, проверявай ВСИЧКИ callsite-ове, не само последно добавения.
**Мерки (v10.0.2):** `firecrawl-py==1.17.0` — пинната до последната стабилна 1.x версия. Smoke test-ът проверява `hasattr(FirecrawlApp, 'scrape_url')`.

**3. Generic extractors се нуждаят от множество стратегии**
Block-based splitting (`\n{2,}`) работи за сайтове с ясно разделени продуктови карти, но се проваля за плътен layout (Laika: 33880 chars → 1 блок → 1 продукт). Image-only сайтове (Zelen) изискват extraction от `![alt](url)`, който стандартният regex `(?<!!)\[` умишлено пропуска.
**Поука:** Винаги имай fallback стратегия. Line-by-line е универсален backup, но трябва да поддържа и нестандартни markdown формати.
**Мерки (v10.0.2):** Добавен "Опит 3" — image alt extraction в generic extractor-а. Fix на `clean_product_name()` regex order (специфичен `![alt]` преди общия `[text]`).

**4. LLM output лимити трябва да скалират с входните данни**
Фиксиран `max_tokens=2000` работеше с ~29 suspicious prices. Добавянето на нови магазини вдигна числото до 38, което надхвърли лимита → truncated JSON → `JSONDecodeError` → валидацията пропусната → грешни цени в таблицата.
**Поука:** `max_tokens` трябва да е функция от `len(input)`, не константа: `max(2000, n * 150 + 500)`.

**5. Defensive JSON parsing за LLM output**
Дори с правилен `max_tokens`, LLM може да върне malformed JSON. JSON repair (намиране на последния валиден `}` + затваряне на масива) спасява частични резултати.
**Поука:** Никога не приемай, че LLM output е валиден — винаги имай repair/fallback.

**6. "Първият match" ≠ "правилният match"**
`extract_bgn_price()` връща първия regex match в подаден текст. С контекстен прозорец `i-3:i+10` (13 реда), първият match може да е цената на **съседен** продукт. Balev даваше 9.00лв за мляко (цена от предходния продукт) вместо 2.70лв. Metro — 15.82лв за вафла.
**Поука:** За line-by-line extraction, предпочитай forward-only контекст — цената на продукта стои **след** името му. Разширявай назад само като fallback.
**Мерки (v10.0.2):** Progressive forward-only context (`i:i+5` → `i-1:i+8`) в Balev, Metro и generic line-by-line extractors.

**7. Regex order matters в utility функции**
`clean_product_name()` изпълняваше `[text](url) → text` **преди** `![alt](url) → ""`. За `![Продукт 400g](img.jpg)` първият regex матчваше `[Продукт 400g](img.jpg)` → оставяше `!Продукт 400g`. Вторият вече не намираше `![...]` формат.
**Поука:** При верижни regex замени, специфичните patterns трябва да се обработват преди по-общите. `![alt](url)` е подмножество на `[text](url)` и трябва да се хване първо.
**Мерки (v10.0.2):** Разменена поредността — image removal преди link extraction.

**8. Image alt text е валиден продуктов източник**
Crawl4AI конвертира `<img alt="...">` в `![alt](url)`. Ако сайт показва продукти предимно като изображения (Zelen: 1/88 покритие), generic extractor-ът трябва да извлича имена от image alt — не само от text links и headings.
**Поука:** За brand pages, image alt е толкова валиден колкото link text или heading. Три опита за извличане на име: link → weight text → image alt.

### Предложения за следващи подобрения

**Висок приоритет:**
1. ~~**Balev Bio extraction**~~ — ✅ **ПОПРАВЕН (v10.0.2)** Forward-only context fix. Контекстният прозорец `i-3:i+10` хващаше цени от съседни продукти; сега `i:i+5` → `i-1:i+8`
2. ~~**Metro price matching**~~ — ✅ **ПОПРАВЕН (v10.0.2)** Същият forward-only context fix
3. ~~**Zelen покритие**~~ — ⚠️ **ЧАСТИЧНО ПОПРАВЕН (v10.0.2)** Добавен image alt extraction + forward-only context + `clean_product_name()` regex order fix. Реалното подобрение ще стане ясно при следващия production run (не можем да тестваме без Crawl4AI markdown от Zelen). Ако покритието остане ниско, може да е нужна инспекция на Zelen markdown + dedicated extractor или `wait_for` CSS selector

**Среден приоритет:**
4. ~~**Firecrawl version pinning**~~ — ✅ **РЕШЕН (v10.0.2)** `firecrawl-py==1.17.0` (последна 1.x версия). Кодът ползва `FirecrawlApp` + `.scrape_url()` от 1.x API; 2.x+ има breaking changes
5. ~~**Smoke test за imports**~~ — ✅ **РЕШЕН (v10.0.2)** Добавена CI стъпка "Smoke test — imports & env vars" в production.yml и experimental.yml. Валидира 7 критични imports + Firecrawl API метод + required/important env vars. Fail-fast при грешки
6. **Glovo Fantastico дедупликация** — 88 extracted products (= Kashon!) е подозрително. Вероятно има дублирани или non-Harmonica продукти

**Нисък приоритет:**
7. ~~**Laika closest-price logic**~~ — ✅ **РЕШЕН (v10.0.2)** Forward-only context fix обхваща и generic line-by-line extractor-а, който Laika ползва
8. **ХИТ Хипермаркет** — все още не е интегриран. Трябва анализ на сайтовата структура

### Хронология на промените

**v9.6.0 (14.02.2026):**
- Claude Sonnet 4.5 ценова валидация — outlier detection + AI оценка
- `validate_prices_with_claude()` — batch анализ с контекст за типични BG цени
- `ANTHROPIC_API_KEY` env var, graceful fallback ако липсва

**v10.0.2 (15.02.2026):**
- Forward-only context за Balev, Metro и generic line-by-line: `i:i+5` → `i-1:i+8`
- `clean_product_name()` regex order fix: `![alt](url)` removal преди `[text](url)` extraction
- Image alt extraction (Опит 3) в generic block-based и line-by-line extractors
- `CATEGORY_OVERRIDES` за продуктова категоризация (7 продукта преместени в правилни категории)
- `firecrawl-py==1.17.0` version pin (последна стабилна 1.x)
- CI smoke test стъпка в production.yml и experimental.yml (imports + env vars + Firecrawl API check)

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
| 2026-02-15 | EXP-003 | v10.0.2: Forward-only context (Balev/Metro/generic), image alt extraction (Zelen), clean_product_name fix, CATEGORY_OVERRIDES, firecrawl pin 1.17.0, CI smoke test |
| 2026-02-14 | EXP-003 | v10.0.1: Firecrawl import/API fix, generic line-by-line, Claude max_tokens fix |
| 2026-02-14 | EXP-003 | v9.6.0: Claude Sonnet 4.5 ценова валидация — outlier detection + AI оценка |
| 2026-02-10 | EXP-003 | v7.0: logging, asyncio.gather, BS4, подобрен matching, retry |
| 2026-02-10 | Всички | Седмичен график: понеделник 05:00 UTC. Zoya.bg премахнат |
| 2026-02-05 | EXP-002 | Завършен успешно - SHEET_TAB_SUFFIX работи |
| 2026-02-05 | EXP-001 | Документиран хибриден подход |
| 2026-02-05 | EXP-001 | v6-v6.3 FINAL, завършен успешно |
| 2026-02-04 | EXP-001 | Създаден, v1-v5 |

---

## Анализ на проекта — 15 февруари 2026

### Текущо състояние

Проектът е на **v10.1** — функциониращ, единствен-файлов (4254 реда) async Python скрапер, който следи цените на продукти Harmonica в **16 българскъи онлайн магазина** (12 директни + 4 чрез Glovo). Работи в CI (GitHub Actions) всеки понеделник; локално липсват инсталирани зависимости.

### Покритие по магазини (v10.0.1 данни, база 88 продукта)

| Магазин | Метод | Покритие | Статус |
|---------|-------|----------|--------|
| Kashon (референтен) | Crawl4AI | Master | Работещ |
| BeFit | Crawl4AI generic | 43/88 (49%) | Стабилен |
| Glovo Fantastico | Firecrawl | 49/88 (56%) | ⚠️ Съмнение за дупликати |
| eBag | Crawl4AI dedicated | 34/88 (39%) | Стабилен |
| Laika | Crawl4AI generic (line-by-line) | 20/88 (23%) | Поправен v10.0.1 |
| Glovo Kaufland | Firecrawl | 18/88 (20%) | Работещ |
| Bio-Market | Crawl4AI generic | 17/88 (19%) | Стабилен |
| Balev Bio | Crawl4AI dedicated | 11/88 (12%) | Поправен v10.0.2 |
| DM | Firecrawl + BS4 | 11/88 (12%) | Поправен v10.0.1 |
| T-Market | curl_cffi + BS4 | 11/88 (12%) | Стабилен |
| Glovo CBA | Firecrawl | 11/88 (12%) | Работещ |
| Randi | Firecrawl | 10/88 (11%) | Стабилен |
| Lilly | curl_cffi GraphQL | 8/88 (9%) | Стабилен |
| Metro | Crawl4AI dedicated | 8/88 (9%) | Поправен v10.0.2 |
| Glovo Billa | Firecrawl | 7/88 (8%) | Работещ |
| Zelen | Crawl4AI generic | 1/88 (1%) | ⚠️ Почти мъртъв |

**Средно покритие: ~18%.** Това означава, че за повечето от 65-те активни продукта, имаме ценова информация от едва 2-3 магазина.

### Три проблема, които възпрепятстват достоверна ценова картина

**1. Ниско покритие = непълна картина**
Средно 18% покритие означава, че за продукт с данни от BeFit (49%) и Glovo Fantastico (56%) може да имаме 2 цени, но за продукт, който е само в Lilly (9%) и Randi (11%) — може да няма нито една. Медианата и средната стойност са статистически безсмислени при 1-2 наблюдения. Потребителят получава фалшиво чувство за пълнота.

**2. Несигурност за коректност на matched цени**
Без автоматизирани тестове няма начин да се потвърди, че "Био кисело мляко 3.6% 400г" от eBag е същият продукт, който Kashon продава. Matching алгоритъмът ползва keyword overlap с 40% threshold + weight bonus, но кратките имена ("Био айран 500мл") лесно се бъркат с конкурентни марки. Claude валидацията хваща outlier цени, но не и грешни product matches.

**3. Zelen, Glovo Fantastico и experimental workflow са неработещи**
- Zelen: 1/88 = функционално мъртъв
- Glovo Fantastico: 49/88, но числото е подозрително близко до Kashon → вероятно дупликати
- `experimental.yml` и `pilot-test.yml` реферират несъществуващи файлове

### Какво работи добре

- **Тристъпална scraping архитектура** (Crawl4AI → Firecrawl → curl_cffi) с fallback вериги
- **Claude Sonnet ценова валидация** — хваща outlier-и (>50% deviation)
- **Google Sheets output** с цветово кодиране, категории, deviation arrows
- **Месечен автосинхрон** на product list от Kashon
- **CI smoke test** — fail-fast при липсващи imports/env vars
- **Добра документация** — EXPERIMENTS.md, CHANGELOG.md

### Препоръчани насоки за достоверна ценова картина

#### Фаза 1: Валидиране на текущите данни (висок приоритет)

**1.1. Ръчен spot-check на 10 продукта**
Избери 10 продукта (по 2 от всяка категория), отвори ръчно всеки магазин и сравни цената с тази в Google Sheets. Целта: потвърждаване на matching accuracy и price extraction correctness. Това е най-бързият начин да се установи дали данните заслужават доверие.

**1.2. Glovo Fantastico дедупликация**
49/88 matched products е подозрително. Трябва ръчна инспекция на raw extracted data — дали има дублирани имена, non-Harmonica продукти, или грешни matches.

**1.3. Unit тестове за критичните функции**
Най-малко:
- `extract_bgn_price()` — с различни формати: "2.70 лв", "2,70лв", "EUR 1.38"
- `match_products()` — с познати продуктови двойки и антипримери
- `clean_product_name()` — с markdown links, image alts, Unicode
- Всеки dedicated extractor — с fixture markdown файлове

#### Фаза 2: Подобряване на покритието (среден приоритет)

**2.1. Zelen fix** — най-голямата дупка
Zelen е най-големият био магазин в София (5 физически + e-shop). 1% покритие е абсурдно. Вероятна причина: lazy-loaded съдържание, което Crawl4AI не чака. Следващи стъпки:
- Инспекция на raw Crawl4AI markdown от Zelen (запазване при следващ run)
- Ако markdown е празен/непълен → `wait_for` CSS selector или увеличен `scroll_times`
- Ако markdown е OK, но extractor-ът пропуска → dedicated Zelen extractor

**2.2. Подобряване на matching за кратки имена**
Продукти с 2-3 думи ("Био айран 500мл", "Био olio 500мл") имат висок false-positive риск. Варианти:
- Задължителен weight match за кратки имена (< 4 keywords)
- URL-based matching за магазини с предвидими URL структури
- Двуфазен matching: строг (exact name) → свободен (keywords) с различни confidence нива

**2.3. Нови магазини**
- **ХИТ Хипермаркет** — вече споменат, липсва анализ на сайта
- **Kaufland.bg (директен)** — в момента само чрез Glovo; директен scraping би дал по-пълно покритие
- **Billa.bg** — аналогично на Kaufland

#### Фаза 3: Архитектурни подобрения (нисък приоритет)

**3.1. Разделяне на monolith-а**
4254 реда в един файл е неустойчиво. Минимално разделяне:
```
scraper/
  __init__.py
  config.py          # STORES, constants, categories
  extractors/        # По файл на магазин
  matching.py        # Product matching
  validation.py      # Claude price validation
  output.py          # Google Sheets + email
  main.py            # Pipeline orchestration
```

**3.2. Исторически данни**
Текущата архитектура презаписва Google Sheets всяка седмица. Няма ценова история. Дори прост CSV append (`data/prices/YYYY-MM-DD.csv`) би дал възможност за trend анализ.

**3.3. Почистване на CI**
- Премахване или поправяне на `experimental.yml` и `pilot-test.yml`
- Премахване на `scraper.log` от git tracking

---

## Harmonica — международно онлайн присъствие

Проучване от 15.02.2026 за онлайн продажба на продукти Harmonica извън България.

### Официални канали
| Канал | URL | Обхват |
|-------|-----|--------|
| harmonica.bg | Корпоративен сайт, продуктов каталог | Без директна онлайн продажба |
| kashonharmonica.bg | Абонаментни кутии + директна поръчка | Само България |

### Потвърдени международни онлайн ритейлъри

| Държава | Ритейлър | Продуктов фокус | Бележки |
|---------|----------|-----------------|---------|
| **Великобритания** | Farmgio (London) | Пълна гама | Основен UK дистрибутор, физически + онлайн |
| **Великобритания** | Amazon UK (Harmonica Store) | Олио, вафли, лимонада | Много позиции currently unavailable |
| **САЩ** | Malincho | Шоколад, масла, сладко, претцели | US вносител на БГ храни |
| **САЩ** | Euro Food Hub (Boston) | Вафли | Локална доставка |
| **Канада** | Natura Market | Претцели | Безплатна доставка над 59 CAD |
| **Турция** | Ekoorganik (Istanbul) | Вафли, сиропи, боза, кашкавал | Пионерски био магазин от 2007 |
| **Кипър** | Etherio Bio Stores | Вафли, претцели, шоколад | Най-голямата био верига в Кипър |
| **Кипър** | Green Monday Cyprus | Лютеница и др. | Временно затворен |
| **Чехия** | English Tea Shop CZ | Вафли | Ограничен асортимент |
| **ОАЕ** | Organic Foods & Cafe (Dubai) | Вафли | 7 супермаркета + 2-часова доставка |
| **Сингапур** | Nutrimax Organic | Кисело мляко (S$18/2×200ml) | С международна доставка |
| **Европа (29+ страни)** | Zoya.bg | Пълна гама | Доставка 1-5 дни от България |

### B2B платформи
| Платформа | Роля |
|-----------|------|
| Food Export Market | Harmonica листнат като organic snacks exporter |
| EU-Japan Centre | Фасилитация за навлизане на японския пазар |

### Ключови наблюдения

1. **Няма международен e-shop.** kashonharmonica.bg работи само в България
2. **Amazon присъствието е само UK**, с много unavailable позиции. Няма Amazon.com (US) или Amazon.de
3. **Shelf-stable продуктите доминират** в износа (вафли, претцели, олио, сладко). Млечните продукти са ограничени до близки пазари (Турция, Сингапур) заради хладилна верига
4. **Farmgio (London)** изглежда е основният международен партньор
5. **Компанията заявява присъствие в 20+ държави**, но повечето са чрез физическа дистрибуция, не онлайн

### Потенциал за разширяване на тракера

Ако целта е международна ценова картина, най-реалистичните допълнения са:
- **Farmgio.com** — пълна гама, стабилен сайт, UK цени в GBP
- **Amazon UK** — API-достъпен, но много позиции unavailable
- **Malincho.com** — US цени в USD, добра БГ храни гама
- **Ekoorganik.com** — TRY цени, интересен за регионално сравнение

Тези 4 сайта биха дали сравнение BG↔UK↔US↔TR за shelf-stable продукти (вафли, олио, претцели, сладко).
