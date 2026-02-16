"""
Smoke tests: verify all modules import without errors.

This catches the class of bugs that hit production in v10.0.1 (wrong Firecrawl
class name) and v10.6.1 (missing BrowserConfig after star-import cleanup).
"""

import importlib


# -- Core modules --

def test_import_config():
    import config
    assert hasattr(config, "STORES")
    assert hasattr(config, "EUR_BGN_RATE")
    assert hasattr(config, "PRICE_RANGE_EUR")
    assert hasattr(config, "logger")


def test_import_utils():
    import utils
    assert callable(utils.extract_eur_price)
    assert callable(utils.extract_bgn_price)
    assert callable(utils.extract_price_fallback)
    assert callable(utils.is_food_product)
    assert callable(utils.is_harmonica_product)
    assert callable(utils.clean_product_name)
    assert callable(utils.deduplicate_check)


def test_import_matching():
    import matching
    assert callable(matching.normalize_name)
    assert callable(matching.extract_keywords)
    assert callable(matching.extract_weight_grams)
    assert callable(matching.match_products)


def test_import_products():
    import products
    assert callable(products.load_product_list)
    assert callable(products.update_product_list_with_new)
    assert callable(products.save_product_list)


def test_import_validation():
    import validation
    assert callable(validation.validate_prices_with_claude)


# -- Extractors package --

def test_import_extractors_package():
    import extractors
    assert callable(extractors.extract_kashon_products)
    assert callable(extractors.extract_ebag_products)
    assert callable(extractors.extract_balev_products)
    assert callable(extractors._extract_generic_products)
    assert callable(extractors.extract_metro_products)
    assert callable(extractors.extract_tmarket_products)
    assert callable(extractors.extract_lilly_products)
    assert callable(extractors.extract_dm_products)
    assert callable(extractors.extract_dm_from_curl_html)
    assert callable(extractors.extract_randi_products)


def test_import_each_extractor_module():
    modules = [
        "extractors.kashon",
        "extractors.ebag",
        "extractors.balev",
        "extractors.generic",
        "extractors.metro",
        "extractors.tmarket",
        "extractors.lilly",
        "extractors.dm",
        "extractors.randi",
    ]
    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        assert mod is not None, f"Failed to import {mod_name}"


# -- Fetchers package --

def test_import_fetchers_package():
    import fetchers
    assert fetchers is not None


def test_import_each_fetcher_module():
    modules = [
        "fetchers.crawl4ai_fetcher",
        "fetchers.curl_api",
        "fetchers.firecrawl_fetcher",
        "fetchers.glovo",
    ]
    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        assert mod is not None, f"Failed to import {mod_name}"


# -- Output package --

def test_import_output_package():
    import output
    assert output is not None


# -- Scraper entry point --

def test_import_scraper():
    import scraper
    assert callable(scraper.main)
    assert callable(scraper.crawl_all)
