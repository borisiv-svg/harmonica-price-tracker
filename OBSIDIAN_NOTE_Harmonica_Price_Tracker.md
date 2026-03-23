# Harmonica Price Tracker — Обзор на проекта

**Дата:** 2026-03-23
**Версия:** v10.14
**Репо:** `borisiv-svg/harmonica-price-tracker`

---

## Какво е това?

Автоматизиран уеб скрейпър, който всеки **понеделник** (07:00 BG време) събира цени на **119 продукта на Harmonica** от **14+ онлайн магазина** в България и ги записва в **Google Sheets** за ценови анализ и проследяване на тенденции.

---

## Етапи на разработка

### Етап 1: Основна архитектура
- Scraper с Crawl4AI (headless Chromium) + BeautifulSoup
- Keyword-based product matching с тегловна нормализация
- Извличане на цени (EUR/BGN) с regex
- Google Sheets интеграция (gspread)
- GitHub Actions — седмичен cron workflow

### Етап 2: Добавяне на магазини и fetcher-и
- **Firecrawl** (платен API) — за JS-heavy сайтове: Randi, T-Market, DM, Zelen, BeFit
- **curl_cffi** — TLS impersonation за Cloudflare bypass (T-Market fallback)
- **Glovo API** — 4 вериги в София (Kaufland, Billa, CBA, Fantastico)
- Архитектура: Firecrawl → Crawl4AI fallback → curl_cffi fallback

### Етап 3: Store-specific extractors
- Персонализирани парсери за всеки магазин (`extractors/`)
- Kashon, eBag, Balev, T-Market, Metro, Randi, DM и др.
- Премахване на Lilly (изчерпани продукти)

### Етап 4: AI валидация с Claude Sonnet
- Outlier detection (>50% отклонение от медианата)
- Claude оценява: ГРЕШНА / ВЯРНА / СЪМНИТЕЛНА
- EUR/100g контекст за по-точна оценка

### Етап 5: Data Quality — BGN-as-EUR проблем (март 2026)
Основен проблем: магазини показват BGN цени с EUR символ.

**4 нива на защита:**
1. **Kashon-based detection** — ако цената е >1.7× спрямо Kashon → вероятно BGN
2. **ref_eur fallback** — ако няма Kashon цена, ползва референтна цена от JSON
3. **Cross-store median** — след всички магазини, детектира цени >70% над медианата
4. **EUR/BGN cross-validation** — regex fix (`[ \t]*` вместо `\s*` за да не хваща нов ред)

**Glovo fix** — всички Glovo цени в България са BGN, винаги конвертира

### Етап 6: Data Quality Gate + Production safeguards
- **Dry-run pre-check** — тестов scrape на 3 магазина преди production run
- **Data Quality Gate** — ако <40% от магазините върнат данни → НЕ записва в Sheets
- **Monthly Product Sync** — автоматично обновяване на product list от Kashon (1-во неделя от месеца)
- **Email alerts** при грешки

---

## Технологичен стек

| Компонент | Технология |
|-----------|-----------|
| Scraping | Crawl4AI 0.8.0, Firecrawl 1.17.0, curl_cffi 0.14.0 |
| AI | Anthropic Claude Sonnet (валидация на outliers) |
| Parsing | BeautifulSoup 4.12.3 |
| Output | Google Sheets (gspread 6.1.0) |
| CI/CD | GitHub Actions (cron + workflow_dispatch) |
| Тестове | pytest (199 теста) |

---

## Магазини (14+)

Kashon (master), eBag, Balev Bio, T-Market, Metro, Zelen, Randi, Bio-Market, BeFit, Laika, DM, Glovo (Kaufland, Billa, CBA, Fantastico)

---

## ⚠️ ВАЖНО: Firecrawl кредити изтичат!

**Проблем:** Firecrawl е платен API с ограничени кредити. След ~1 месец (април 2026) кредитите ще свършат.

**Къде се ползва Firecrawl:**
- Randi (JS-heavy)
- T-Market (Cloudflare)
- DM.bg (Cloudflare + JS)
- Zelen (cookie consent overlay)
- BeFit (accessibility overlay)
- Glovo (markdown rendering)

**Нужно решение:** Безплатна алтернатива за JS rendering.

**Възможни варианти:**
1. **Crawl4AI** — вече го имаме като fallback, може да стане primary за всички
2. **Playwright директно** — headless Chromium, пълен контрол, безплатен
3. **Selenium** — класически вариант, по-бавен
4. **Self-hosted Firecrawl** — open-source версията, но изисква сървър
5. **curl_cffi** — вече работи за T-Market, може да се разшири

**Препоръка:** Преминаване към **Crawl4AI като primary** (вече е fallback) + **Playwright** за специфичните Cloudflare случаи. Тестване преди изтичане на Firecrawl кредитите.

---

## Файлова структура (ключови файлове)

```
scraper.py          — Главна оркестрация
config.py           — Конфигурация на магазини, API keys, flags
validation.py       — Claude Sonnet валидация
matching.py         — Product matching алгоритъм
utils.py            — Price extraction, BGN/EUR, retry
fetchers/           — Firecrawl, Crawl4AI, Glovo, curl_cffi
extractors/         — Store-specific парсери
output/sheets.py    — Google Sheets запис
data/               — products JSON, price history, run history
```

---

## Фиксиран курс

**1 EUR = 1.9558 BGN** (фиксиран в кода, не се обновява динамично)
