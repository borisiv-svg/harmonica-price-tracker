"""
Tests for utils.py — price extraction, name cleaning, filtering.
"""

from utils import (
    extract_eur_price,
    extract_bgn_price,
    extract_price_fallback,
    clean_product_name,
    find_price_bounded,
    is_food_product,
    is_harmonica_product,
    is_price_sane,
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
        name = "A" * 70
        deduplicate_check(name, seen)
        # Different ending but same first 50 chars
        assert deduplicate_check("A" * 50 + "DIFFERENT", seen) is True

    def test_distinguishes_similar_products(self):
        """Products that differ after 30 chars should NOT be deduplicated."""
        seen = set()
        name1 = "Био Обикновени бисквити с краве масло и ванилия 150г"
        name2 = "Био Обикновени бисквити с краве масло и шоколад 150г"
        assert deduplicate_check(name1, seen) is False
        assert deduplicate_check(name2, seen) is False  # Should be different


# -- Bounded price search --

class TestFindPriceBounded:
    def test_finds_price_on_next_line(self):
        lines = [
            "Harmonica Кисело мляко 400г",
            "4.89лв",
        ]
        eur, bgn = find_price_bounded(lines, 0)
        assert bgn == 4.89

    def test_stops_at_next_product(self):
        """Should NOT grab price from the next product."""
        lines = [
            "Кисело мляко harmonica 2.0% 400г",
            "Кисело мляко harmonica 3.6% 400г",
            "5.39лв",
        ]
        eur, bgn = find_price_bounded(lines, 0)
        # Should stop at line 1 (next product) and find no price
        assert bgn is None
        assert eur is None

    def test_second_product_gets_correct_price(self):
        lines = [
            "Кисело мляко harmonica 2.0% 400г",
            "Кисело мляко harmonica 3.6% 400г",
            "5.39лв",
        ]
        eur, bgn = find_price_bounded(lines, 1)
        assert bgn == 5.39

    def test_finds_eur_price(self):
        lines = [
            "Harmonica вафла 30г",
            "0.65€",
        ]
        eur, bgn = find_price_bounded(lines, 0)
        assert eur == 0.65

    def test_empty_context(self):
        lines = ["Harmonica вафла 30г"]
        eur, bgn = find_price_bounded(lines, 0)
        assert eur is None
        assert bgn is None


# -- Price sanity check --

class TestIsPriceSane:
    def test_normal_yogurt_price(self):
        assert is_price_sane("Кисело мляко 400г", 1.40) is True

    def test_absurd_wafer_price(self):
        # 14.65€ for 30g = 48.8€/100g → insane
        assert is_price_sane("Вафла 30г", 14.65) is False

    def test_normal_wafer_price(self):
        assert is_price_sane("Вафла 30г", 0.65) is True

    def test_no_weight_returns_true(self):
        assert is_price_sane("Нещо без грамаж", 14.65) is True

    def test_no_price_returns_true(self):
        assert is_price_sane("Вафла 30г", None) is True

    def test_kg_product(self):
        # 6.14€ for 2kg = 0.307€/100g → sane
        assert is_price_sane("Кисело мляко 2кг", 6.14) is True

    def test_gr_suffix(self):
        # "гр" should be recognized as grams
        assert is_price_sane("Вафла 30гр", 14.65) is False

    def test_expensive_cheese_ok(self):
        # 7.67€ for 400g = 1.92€/100g → sane
        assert is_price_sane("Сирене 400г", 7.67) is True


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
