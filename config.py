"""
Harmonica Price Tracker — Configuration
========================================
Constants, store configs, environment variables, feature flags, logger setup.
"""

import os
import logging

# =============================================================================
# LOGGING SETUP
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('scraper.log', encoding='utf-8'),
    ]
)
logger = logging.getLogger('harmonica')

# =============================================================================
# OPTIONAL DEPENDENCIES — feature flags
# =============================================================================

try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
    CRAWL4AI_AVAILABLE = True
except ImportError:
    CRAWL4AI_AVAILABLE = False
    logger.error("Crawl4AI not installed")

try:
    import capsolver
    CAPSOLVER_AVAILABLE = True
except ImportError:
    CAPSOLVER_AVAILABLE = False
    logger.warning("capsolver not installed — anti-bot bypass disabled")

try:
    import gspread
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False
    logger.warning("gspread not installed — Sheets write disabled")

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    logger.warning("beautifulsoup4 not installed — using regex fallback for Lilly")

try:
    from curl_cffi.requests import AsyncSession as CurlAsyncSession
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False
    logger.warning("curl_cffi not installed — TLS impersonation disabled")

try:
    from firecrawl import FirecrawlApp
    FIRECRAWL_AVAILABLE = True
except ImportError:
    FIRECRAWL_AVAILABLE = False
    logger.warning("firecrawl not installed — Glovo JS rendering disabled")

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    logger.warning("anthropic not installed — Claude price validation disabled")


# =============================================================================
# CONSTANTS
# =============================================================================

EUR_BGN_RATE = 1.9558  # Фиксиран курс
GLOVO_AUTH_TOKEN = os.environ.get("GLOVO_AUTH_TOKEN")  # Optional: Glovo Bearer token
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY")  # Optional: Firecrawl API key
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")  # Optional: Claude API key за валидация

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_JSON_PATH = os.path.join(PROJECT_ROOT, "data", "products", "harmonica_products.json")

# Ценови граници
PRICE_RANGE_EUR = (0.20, 100)
PRICE_RANGE_BGN = (0.40, 200)


# =============================================================================
# STORES
# =============================================================================

STORES = {
    "kashon": {
        "name": "Кашон",
        "url": "https://kashonharmonica.bg/bg/products/field_producer/harmonica-144",
        "scroll_times": 40,
        "scroll_delay": 3000,
        "is_master": True,
    },
    "ebag": {
        "name": "eBag",
        "url": "https://www.ebag.bg/search/?products%5BrefinementList%5D%5Bbrand_name_bg%5D%5B0%5D=%D0%A5%D0%B0%D1%80%D0%BC%D0%BE%D0%BD%D0%B8%D0%BA%D0%B0",
        "scroll_times": 12,
    },
    "balev": {
        "name": "Balev Bio",
        "url": "https://balevbiomarket.com/productBrands/harmonica",
        "scroll_times": 8,
    },
    "lilly": {
        "name": "Lilly",
        "url": "https://lillydrogerie.bg/brands/harmonica",
        "scroll_times": 4,
        "brand_page": True,
        "use_magic": True,
    },
    "tmarket": {
        "name": "T-Market",
        "url": "https://tmarketonline.bg/vendor/harmonica-1881705916",
        "scroll_times": 8,
        "brand_page": True,
        "needs_captcha_solver": True,
    },
    "metro": {
        "name": "Metro",
        "url": "https://shop.metro.bg/shop/search?q=%D1%85%D0%B0%D1%80%D0%BC%D0%BE%D0%BD%D0%B8%D0%BA%D0%B0",
        "scroll_times": 15,
    },
    "zelen": {
        "name": "Zelen",
        "url": "https://zelen.bg/brand/94/harmonica",
        "scroll_times": 15,
        "brand_page": True,
        # Cookie consent overlay блокира зареждането на продукти
        "pre_js": """
            // Затваряме GDPR cookie consent popup
            document.querySelectorAll(
                '[class*="cookie"] button, [class*="Cookie"] button, '
                '[class*="consent"] button, [id*="cookie"] button, '
                'button[class*="accept"], button[class*="Accept"], '
                '.cc-btn.cc-dismiss, .cc-allow, '
                '[data-action="accept"], [aria-label="Accept"]'
            ).forEach(el => {
                if (el.textContent.match(/accept|приемам|съгласен|разбрах|okay|ok/i)) {
                    el.click();
                }
            });
            // Премахваме overlay елементи
            document.querySelectorAll(
                '[class*="cookie-banner"], [class*="cookie-consent"], '
                '[class*="CookieConsent"], [id*="cookie"], '
                '.cc-window, .cc-banner'
            ).forEach(el => el.remove());
        """,
        "firecrawl_pre_actions": [
            {"type": "wait", "milliseconds": 2000},
            {"type": "click", "selector": "button[class*='accept'], button[class*='Accept'], .cc-allow, [data-action='accept']"},
            {"type": "wait", "milliseconds": 1000},
        ],
    },
    "randi": {
        "name": "Randi",
        "url": "https://randi.bg/search?search=harmonica",
        "scroll_times": 10,
    },
    "biomarket": {
        "name": "Bio-Market",
        "url": "https://bio-market.bg/brand/harmonica",
        "scroll_times": 10,
        "brand_page": True,
    },
    "befit": {
        "name": "BeFit",
        "url": "https://befit.bg/brands/harmonica",
        "scroll_times": 10,
        "brand_page": True,
        # Accessibility popup трябва да се затвори преди скролиране
        "pre_js": """
            // Затваряме accessibility popup (UserWay/EqualWeb widget)
            document.querySelectorAll('[aria-label="Close"], .close-popup, .acsb-close, [class*="close"]')
                .forEach(el => el.click());
            // Премахваме overlay елементи
            document.querySelectorAll('[class*="acsb"], [class*="accessibility"], [id*="acsb"]')
                .forEach(el => el.remove());
        """,
        # Firecrawl: затваряне на accessibility overlay преди scroll
        "firecrawl_pre_actions": [
            {"type": "click", "selector": ".acsb-close"},
            {"type": "click", "selector": "[aria-label='Close']"},
            {"type": "wait", "milliseconds": 1000},
        ],
    },
    "laika": {
        "name": "Laika",
        "url": "https://laika.bg/harmonica-bio-bulgaria-proizvodstvo-magi-maleeva-shoko-ghi-kefir-boza-koze-sirene-ovche-izvara-bulgarska-tzena-kade-da-kupia-magazin-online",
        "scroll_times": 10,
        "brand_page": True,
    },
}

# Glovo магазини в София — ще се сканират чрез Glovo API
GLOVO_STORES = {
    "glovo_kaufland": {
        "name": "Kaufland",
        "slug": "kaufland-sof",
        "city_code": "SOF",
    },
    "glovo_billa": {
        "name": "Billa",
        "slug": "billa-sof1",
        "city_code": "SOF",
    },
    "glovo_cba": {
        "name": "CBA",
        "slug": "cba-supermarket-cherni-vruh-sof",
        "city_code": "SOF",
    },
    "glovo_fantastico": {
        "name": "Fantastico",
        "slug": "coca-cola-real-magic-sof",
        "city_code": "SOF",
    },
}

GLOVO_API_BASE = "https://api.glovoapp.com/v3"
