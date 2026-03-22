# Проучване: Инструменти за уеб скрейпинг (Март 2026)

> Артефакт от проучване, проведено на 22.03.2026. За бъдеща референция при подобряване на скрейпъра.

## Текущ стек

- **Crawl4AI v0.8.0** — последна стабилна версия (18.03.2026). Вече сме up to date.

## Нови възможности в Crawl4AI v0.8.0

- `prefetch=True` — 5-10x по-бързо URL discovery (полезно за Кашон)
- Deep crawl crash recovery с `resume_state` и `on_state_change` callbacks
- Security fixes за Docker API

## Anti-detect браузъри

### Camoufox
- Custom Firefox build — модифицира fingerprint на C++ ниво (не чрез JS injection)
- 0% detection score при тестове
- Съвместим с Playwright — само сменяш browser init-а
- GitHub: https://github.com/daijro/camoufox
- **Кога да ползваме:** Ако BeFit/Randi продължават с timeout/rate limit

### Nodriver (наследник на undetected-chromedriver)
- Пълно пренаписване: async, без Selenium, custom CDP
- Стартира истински Chrome (без `navigator.webdriver` флаг)
- GitHub: https://github.com/ultrafunkamsterdam/nodriver

### Patchright
- Друга алтернатива в anti-detect пространството за 2026

## AI-Powered извличане

### ScrapeGraphAI (MIT, v1.74.0)
- LLM + graph logic pipelines
- Поддържа OpenAI, Groq, Gemini, локални Ollama модели
- Адаптира се към промени в layout без ъпдейт на selectors
- GitHub: https://github.com/ScrapeGraphAI/Scrapegraph-ai
- **Кога да ползваме:** За проблемни магазини с чести промени в HTML

### Jina Reader
- Prefix `https://r.jina.ai/URL` → instant Markdown
- Безплатно до 1M tokens, без акаунт
- ReaderLM-v2 (1.5B params), 29 езика
- **Кога да ползваме:** Бърз backup за Firecrawl/Crawl4AI

### Parsera
- Конкурент на ScrapeGraphAI с по-добра accuracy
- Добра n8n интеграция

## Ценово извличане

### Zyte price-parser
- Специализирана Python библиотека за парсване на ценови стрингове
- От екипа зад Scrapy, безплатна
- **Кога да ползваме:** За нормализиране на цени от различни формати

## Workflow автоматизация

### n8n (self-hosted, безплатен)
- Визуален pipeline: Schedule → Scrape → Sheets → Telegram alerts
- Може да замени GitHub Actions за scheduling
- **Кога да ползваме:** Ако искаме по-гъвкав scheduling с UI

## Cloudflare 2026 — Важно!

- Cloudflare генерира **фалшиви AI-написани страници като honeypots** вместо да блокира
- `puppeteer-stealth` е deprecated (февруари 2025)
- TLS fingerprinting и behavioral analysis са основните методи за детекция
- Най-добри подходи: Camoufox или Nodriver + rotating residential proxies

## Firecrawl алтернативи (ако трябва да сменим)

| Инструмент | Лиценз | Ключова разлика |
|---|---|---|
| Crawl4AI | Apache-2.0 | Вече ползваме. LLM-ready Markdown, офлайн. |
| Jina Reader | Free tier | `r.jina.ai/URL` prefix, instant Markdown |
| ScrapeGraphAI | MIT | AI extraction, адаптивен |
| Crawlee (Apify) | Apache-2.0 | Auto fingerprint rotation, proxy rotation |

## Приоритетни действия (TODO)

- [ ] Опитай `prefetch=True` в Crawl4AI за Кашон
- [ ] Тествай Camoufox ако BeFit/Randi продължават с проблеми
- [ ] Оцени ScrapeGraphAI + Ollama за адаптивно извличане
- [ ] Разгледай Zyte price-parser за по-добро нормализиране на цени
- [ ] Провери Jina Reader като fallback за проблемни URL-и
