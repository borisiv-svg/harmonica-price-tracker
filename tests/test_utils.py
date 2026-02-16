"""
Tests for utils.py — price extraction, name cleaning, filtering.
"""

from utils import (
    extract_eur_price,
    extract_bgn_price,
    extract_price_fallback,
    clean_product_name,
    is_food_product,
    is_harmonica_product,
    deduplicate_check,
    categorize_product,
    detect_cloudflare_challenge,
)


# -- EUR price extraction --

class TestExtractEurPrice:
    def test_standard_format(self):
        assert extract_eur_price("2.50€") == 2.50

    def test_comma_format(self):
        assert extract_eur_price("2,50€") == 2.50

    def test_with_space(self):
        assert extract_eur_price("2.50 €") == 2.50

    def test_euro_prefix(self):
        assert extract_eur_price("€2.50") == 2.50

    def test_euro_prefix_with_space(self):
        assert extract_eur_price("€ 2.50") == 2.50

    def test_single_decimal(self):
        # "2.5€" -> decimals "5" padded to "50" -> 2.50
        assert extract_eur_price("2.5€") == 2.50

    def test_no_price(self):
        assert extract_eur_price("no price here") is None

    def test_out_of_range_too_high(self):
        assert extract_eur_price("500.00€") is None

    def test_out_of_range_too_low(self):
        assert extract_eur_price("0.01€") is None

    def test_in_context(self):
        text = "Продукт Harmonica мляко 400г цена: 2.50€ в наличност"
        assert extract_eur_price(text) == 2.50


# -- BGN price extraction --

class TestExtractBgnPrice:
    def test_standard_format(self):
        assert extract_bgn_price("4.89лв") == 4.89

    def test_comma_format(self):
        assert extract_bgn_price("4,89лв") == 4.89

    def test_with_space(self):
        assert extract_bgn_price("4.89 лв") == 4.89

    def test_no_price(self):
        assert extract_bgn_price("no price here") is None

    def test_out_of_range(self):
        assert extract_bgn_price("999.99лв") is None

    def test_single_decimal(self):
        assert extract_bgn_price("4.8лв") == 4.80


# -- Fallback price extraction --

class TestExtractPriceFallback:
    def test_plain_number(self):
        assert extract_price_fallback(" 4.89 ") == 4.89

    def test_ignores_grams(self):
        assert extract_price_fallback("400.00г") is None

    def test_ignores_ml(self):
        assert extract_price_fallback("500.00мл") is None

    def test_ignores_percent(self):
        assert extract_price_fallback("3.60%") is None

    def test_finds_price_after_weight(self):
        text = "Мляко 400г 4.89"
        # Should skip 400г but there's no "400.00г" pattern, then find 4.89
        result = extract_price_fallback(text)
        assert result == 4.89

    def test_no_match(self):
        assert extract_price_fallback("no numbers") is None


# -- Name cleaning --

class TestCleanProductName:
    def test_removes_markdown_link(self):
        assert clean_product_name("[Product](https://example.com)") == "Product"

    def test_removes_image(self):
        result = clean_product_name("![alt](https://img.jpg) Product")
        assert "alt" not in result
        assert "img.jpg" not in result

    def test_removes_bold(self):
        assert clean_product_name("**Bold Name**") == "Bold Name"

    def test_removes_markdown_prefixes(self):
        assert clean_product_name("## Heading") == "Heading"
        assert clean_product_name("- List item") == "List item"
        assert clean_product_name("> Quote") == "Quote"

    def test_collapses_whitespace(self):
        assert clean_product_name("too   many   spaces") == "too many spaces"

    def test_strips(self):
        assert clean_product_name("  padded  ") == "padded"


# -- Food filtering --

class TestIsFoodProduct:
    def test_food_keyword(self):
        assert is_food_product("Кисело мляко 400г") is True

    def test_non_food_keyword(self):
        assert is_food_product("Крем за ръце с шампоан") is False

    def test_product_with_weight(self):
        assert is_food_product("Нещо 400г") is True

    def test_generic_name(self):
        # No food keyword, no weight → default True
        assert is_food_product("Something random") is True

    def test_clothing(self):
        assert is_food_product("Детска тениска XL") is False


# -- Harmonica detection --

class TestIsHarmonicaProduct:
    def test_latin(self):
        assert is_harmonica_product("Harmonica BIO Yogurt 400g") is True

    def test_cyrillic(self):
        assert is_harmonica_product("Хармоника БИО Кисело мляко") is True

    def test_case_insensitive(self):
        assert is_harmonica_product("HARMONICA Айран") is True

    def test_not_harmonica(self):
        assert is_harmonica_product("Верея Кисело мляко 400г") is False


# -- Deduplication --

class TestDeduplicateCheck:
    def test_first_occurrence_not_duplicate(self):
        seen = set()
        assert deduplicate_check("Product Name", seen) is False

    def test_second_occurrence_is_duplicate(self):
        seen = set()
        deduplicate_check("Product Name", seen)
        assert deduplicate_check("Product Name", seen) is True

    def test_case_insensitive(self):
        seen = set()
        deduplicate_check("Product Name", seen)
        assert deduplicate_check("product name", seen) is True

    def test_truncates_to_key_length(self):
        seen = set()
        name = "A" * 50
        deduplicate_check(name, seen)
        # Different ending but same first 30 chars
        assert deduplicate_check("A" * 30 + "DIFFERENT", seen) is True


# -- Categorization --

class TestCategorizeProduct:
    def test_dairy(self):
        idx, cat = categorize_product("Кисело мляко 3.6%")
        assert cat == "Млечни продукти"

    def test_sweets(self):
        idx, cat = categorize_product("Бисквити с шоколад")
        assert cat == "Вафли и сладки"

    def test_peanut_butter_override(self):
        # "фъстъчено масло" should NOT go to "Млечни" (which has "масло")
        idx, cat = categorize_product("Фъстъчено масло 300г")
        assert cat == "Тахани, ядки и бобови"

    def test_unknown_product(self):
        idx, cat = categorize_product("Unknown product XYZ")
        assert cat == "Други"

    def test_drinks(self):
        idx, cat = categorize_product("Сок от ябълка 1л")
        assert cat == "Напитки"


# -- Cloudflare detection --

class TestDetectCloudflareChallenge:
    def test_normal_html(self):
        is_cf, sitekey = detect_cloudflare_challenge("<html><body>Normal page</body></html>")
        assert is_cf is False
        assert sitekey is None

    def test_cloudflare_html(self):
        html = '<html><body>Just a moment<div class="cf-turnstile" data-sitekey="0x4AAA"></div></body></html>'
        is_cf, sitekey = detect_cloudflare_challenge(html)
        assert is_cf is True
        assert sitekey == "0x4AAA"

    def test_empty_input(self):
        is_cf, sitekey = detect_cloudflare_challenge("")
        assert is_cf is False

    def test_none_input(self):
        is_cf, sitekey = detect_cloudflare_challenge(None)
        assert is_cf is False
