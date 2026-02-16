"""
Harmonica Price Tracker — Crawl4AI Fetchers
=============================================
Crawl4AI-based crawlers with anti-bot bypass (CapSolver) and retry logic.
"""

import os
import time

from config import CRAWL4AI_AVAILABLE, CAPSOLVER_AVAILABLE, logger

if CRAWL4AI_AVAILABLE:
    from crawl4ai import CrawlerRunConfig, CacheMode

if CAPSOLVER_AVAILABLE:
    import capsolver

from utils import retry_async, detect_cloudflare_challenge


async def solve_turnstile(website_url, website_key):
    """Решава Cloudflare Turnstile чрез CapSolver API."""
    api_key = os.environ.get('CAPSOLVER_API_KEY')
    if not api_key:
        logger.error("CAPSOLVER_API_KEY не е зададен")
        return None

    capsolver.api_key = api_key

    try:
        logger.info(f"CapSolver: решаване на Turnstile за {website_url}")
        solution = capsolver.solve({
            "type": "AntiTurnstileTaskProxyLess",
            "websiteURL": website_url,
            "websiteKey": website_key,
        })
        token = solution.get("token")
        if token:
            logger.info(f"CapSolver: Turnstile решен успешно (token: {token[:20]}...)")
        return token
    except Exception as e:
        logger.error(f"CapSolver грешка: {e}")
        return None


@retry_async(max_retries=1, backoff_base=5)
async def crawl_with_captcha_solver(crawler, store_key, store_config):
    """
    Краулва сайт с anti-bot защита. Стратегия:
    1. Опит с magic mode (симулира човешко поведение)
    2. Ако има Cloudflare challenge → CapSolver API
    3. Инжектиране на token + повторно зареждане
    """
    store_name = store_config["name"]
    url = store_config["url"]

    logger.info(f"CRAWLING (anti-bot): {store_name}")
    start = time.time()

    # Стъпка 1: Опит с magic mode
    magic_config = CrawlerRunConfig(
        magic=True,
        page_timeout=60000,
        remove_overlay_elements=True,
        cache_mode=CacheMode.BYPASS,
    )

    result = await crawler.arun(url=url, config=magic_config)

    # Проверка за DNS / мрежови грешки преди всичко
    if not result.success:
        error_msg = str(getattr(result, 'error_message', '') or '')
        elapsed = time.time() - start
        if 'ERR_NAME_NOT_RESOLVED' in error_msg:
            logger.warning(f"{store_name}: DNS грешка {elapsed:.1f}s — домейнът не е достъпен")
            return {"success": False, "error": "DNS error: domain not resolved"}
        if any(e in error_msg for e in ('ERR_CONNECTION_REFUSED', 'ERR_CONNECTION_TIMED_OUT',
                                        'ERR_NETWORK_CHANGED', 'net::ERR_')):
            logger.warning(f"{store_name}: Мрежова грешка {elapsed:.1f}s — {error_msg[:120]}")
            return {"success": False, "error": f"Network error: {error_msg[:120]}"}

    # Проверка дали magic mode е достатъчен
    if result.success and result.markdown and len(result.markdown) > 500:
        # Проверяваме дали съдържанието е реално (не Cloudflare challenge page)
        html = getattr(result, 'html', '') or ''
        is_challenge, _ = detect_cloudflare_challenge(html)
        if not is_challenge:
            elapsed = time.time() - start
            logger.info(f"{store_name}: OK (magic mode) {elapsed:.1f}s, {len(result.markdown)} chars")
            return {
                "success": True,
                "store_key": store_key,
                "elapsed": elapsed,
                "markdown": result.markdown,
                "html": html,
                "method": "magic",
            }

    # Стъпка 2: Cloudflare challenge детектиран — CapSolver
    html = getattr(result, 'html', '') or ''
    is_challenge, sitekey = detect_cloudflare_challenge(html)

    if not is_challenge:
        # Не е Cloudflare — може би друг тип блокировка
        elapsed = time.time() - start
        logger.warning(f"{store_name}: Блокиран (не е Cloudflare) {elapsed:.1f}s")
        logger.warning(f"  HTML preview: {html[:200]}")
        return {"success": False, "error": f"Blocked by non-Cloudflare protection"}

    if not CAPSOLVER_AVAILABLE:
        return {"success": False, "error": "CapSolver not installed"}

    if not sitekey:
        logger.warning(f"{store_name}: Cloudflare challenge без sitekey — опит с AntiCloudflareTask")
        # За Cloudflare Challenge (5s check) без Turnstile widget
        # Пробваме по-агресивен подход: повторно зареждане след кратко чакане
        wait_config = CrawlerRunConfig(
            magic=True,
            page_timeout=90000,
            remove_overlay_elements=True,
            cache_mode=CacheMode.BYPASS,
            wait_for="js:() => !document.querySelector('#cf-challenge-running')",
        )
        result = await crawler.arun(url=url, config=wait_config)
        html = getattr(result, 'html', '') or ''
        is_still_challenge, sitekey = detect_cloudflare_challenge(html)

        if not is_still_challenge and result.success and len(result.markdown or '') > 500:
            elapsed = time.time() - start
            logger.info(f"{store_name}: OK (wait bypass) {elapsed:.1f}s")
            return {
                "success": True,
                "store_key": store_key,
                "elapsed": elapsed,
                "markdown": result.markdown,
                "html": html,
                "method": "wait_bypass",
            }

        if not sitekey:
            return {"success": False, "error": "Cloudflare challenge: sitekey not found"}

    # Стъпка 3: CapSolver Turnstile
    token = await solve_turnstile(url, sitekey)
    if not token:
        return {"success": False, "error": "CapSolver failed to solve Turnstile"}

    # Стъпка 4: Инжектиране на token
    inject_js = f"""
    (function() {{
        var input = document.querySelector('input[name="cf-turnstile-response"]');
        if (input) {{
            input.value = '{token}';
        }}
        var hidden = document.querySelector('[name="cf-turnstile-response"]');
        if (hidden) {{
            hidden.value = '{token}';
        }}
        // Опит да submit-нем формата
        var form = document.querySelector('form');
        if (form) form.submit();
        // Или кликнем бутон
        var btn = document.querySelector('button[type="submit"], input[type="submit"]');
        if (btn) btn.click();
    }})();
    """

    inject_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        js_code=inject_js,
        js_only=True,
        page_timeout=30000,
        wait_for="js:() => document.querySelectorAll('[class*=product]').length > 0",
    )

    result = await crawler.arun(url=url, config=inject_config)
    elapsed = time.time() - start

    if result.success and result.markdown and len(result.markdown) > 300:
        logger.info(f"{store_name}: OK (CapSolver) {elapsed:.1f}s, {len(result.markdown)} chars")
        return {
            "success": True,
            "store_key": store_key,
            "elapsed": elapsed,
            "markdown": result.markdown,
            "html": getattr(result, 'html', None),
            "method": "capsolver",
        }

    logger.error(f"{store_name}: FAILED след CapSolver inject {elapsed:.1f}s")
    return {"success": False, "error": "CapSolver token injected but page didn't load"}


@retry_async(max_retries=2, backoff_base=3)
async def crawl_store(crawler, store_key, store_config):
    """Сканира един магазин с retry при грешка."""
    store_name = store_config["name"]
    url = store_config["url"]
    scroll_times = store_config.get("scroll_times", 5)
    use_magic = store_config.get("use_magic", False)

    logger.info(f"CRAWLING{'(magic)' if use_magic else ''}: {store_name}")

    scroll_delay = store_config.get("scroll_delay", 1500)
    pre_js = store_config.get("pre_js", "")
    scroll_js = ""
    if scroll_times > 0 and not use_magic:
        scroll_js = f"""
        // Pre-scroll JS (затваряне на popups и т.н.)
        {pre_js}
        await new Promise(r => setTimeout(r, 1000));

        async function scrollPage() {{
            const step = window.innerHeight || 800;
            for (let i = 0; i < {scroll_times}; i++) {{
                window.scrollBy(0, step);
                await new Promise(r => setTimeout(r, {scroll_delay}));
            }}
            // Final: scroll to absolute bottom twice to catch stragglers
            window.scrollTo(0, document.body.scrollHeight);
            await new Promise(r => setTimeout(r, {scroll_delay}));
            window.scrollTo(0, document.body.scrollHeight);
            await new Promise(r => setTimeout(r, {scroll_delay}));
        }}
        await scrollPage();
        """

    wait_for = store_config.get("wait_for")

    if use_magic:
        config = CrawlerRunConfig(
            magic=True,
            page_timeout=60000,
            remove_overlay_elements=True,
            cache_mode=CacheMode.BYPASS,
        )
    else:
        config = CrawlerRunConfig(
            page_timeout=90000,
            remove_overlay_elements=True,
            js_code=scroll_js if scroll_js else None,
            wait_for=wait_for,
        )

    start = time.time()
    result = await crawler.arun(url=url, config=config)
    elapsed = time.time() - start

    if not result.success:
        logger.error(f"{store_name}: FAILED — {result.error_message}")
        return {"success": False, "error": result.error_message}

    logger.info(f"{store_name}: OK {elapsed:.1f}s, {len(result.markdown)} chars")

    return {
        "success": True,
        "store_key": store_key,
        "elapsed": elapsed,
        "markdown": result.markdown,
        "html": getattr(result, 'html', None),
    }
