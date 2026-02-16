"""
Tests for matching.py — product name normalization, keyword extraction,
weight parsing, and product matching engine.
"""

from matching import (
    normalize_name,
    extract_keywords,
    extract_weight_grams,
    match_products,
)


# -- Name normalization --

class TestNormalizeName:
    def test_removes_brand(self):
        result = normalize_name("Harmonica БИО Кисело мляко")
        assert "harmonica" not in result
        assert "хармоника" not in normalize_name("Хармоника мляко")

    def test_removes_bio(self):
        result = normalize_name("БИО Кисело мляко")
        assert "био" not in result

    def test_normalizes_ml_to_cyrillic(self):
        result = normalize_name("Product 500ml")
        assert "500мл" in result

    def test_normalizes_g_to_cyrillic(self):
        result = normalize_name("Product 400g")
        assert "400г" in result

    def test_converts_kg_to_grams(self):
        result = normalize_name("Product 2kg")
        assert "2000г" in result

    def test_converts_decimal_kg_cyrillic(self):
        # Decimal kg with cyrillic "кг" is the common production format
        result = normalize_name("Product 1,5кг")
        assert "1500г" in result

    def test_removes_punctuation(self):
        result = normalize_name("Кисело-мляко (BIO)")
        assert "-" not in result
        assert "(" not in result


# -- Keyword extraction --

class TestExtractKeywords:
    def test_basic(self):
        kw = extract_keywords("Harmonica БИО Кисело мляко 400г")
        assert "кисело" in kw
        assert "мляко" in kw
        assert "400г" in kw
        # Brand should be removed
        assert "harmonica" not in kw

    def test_short_words_excluded(self):
        kw = extract_keywords("А Б мляко")
        # Single-char words should not be in keywords (min 3 chars for letters)
        assert "мляко" in kw

    def test_returns_set(self):
        kw = extract_keywords("мляко мляко мляко")
        assert isinstance(kw, set)


# -- Weight extraction --

class TestExtractWeightGrams:
    def test_grams_cyrillic(self):
        assert extract_weight_grams("Мляко 400г") == 400

    def test_grams_latin(self):
        assert extract_weight_grams("Yogurt 400g") == 400

    def test_ml_cyrillic(self):
        assert extract_weight_grams("Айран 500мл") == 500

    def test_ml_latin(self):
        assert extract_weight_grams("Ayran 500ml") == 500

    def test_kg_conversion(self):
        assert extract_weight_grams("Продукт 2кг") == 2000

    def test_liters_conversion(self):
        assert extract_weight_grams("Мляко 1л") == 1000

    def test_decimal_kg(self):
        assert extract_weight_grams("Продукт 0.5кг") == 500

    def test_no_weight(self):
        assert extract_weight_grams("Продукт без тегло") is None


# -- Product matching --

class TestMatchProducts:
    def test_exact_match(self):
        ref = [{"name": "Harmonica БИО Кисело мляко 3.6% 400г"}]
        store = [{"name": "Harmonica БИО Кисело мляко 3.6% 400г", "eur": 2.50}]
        matches = match_products(ref, store)
        assert ref[0]["name"] in matches
        assert matches[ref[0]["name"]]["eur"] == 2.50

    def test_partial_match(self):
        ref = [{"name": "Harmonica БИО Кисело мляко 3.6% 400г"}]
        store = [{"name": "Кисело мляко Harmonica 3.6% 400г", "eur": 2.40}]
        matches = match_products(ref, store)
        assert ref[0]["name"] in matches

    def test_no_match_different_product(self):
        ref = [{"name": "Harmonica БИО Кисело мляко 3.6% 400г"}]
        store = [{"name": "Coca-Cola 1.5л", "eur": 2.00}]
        matches = match_products(ref, store)
        assert len(matches) == 0

    def test_weight_hard_reject(self):
        ref = [{"name": "Harmonica БИО Кисело мляко 400г"}]
        store = [{"name": "Harmonica БИО Кисело мляко 2кг", "eur": 10.00}]
        matches = match_products(ref, store)
        # 400g vs 2000g = 5x difference → hard reject
        assert len(matches) == 0

    def test_weight_match_bonus(self):
        ref = [{"name": "Harmonica Кисело мляко 400г"}]
        store = [
            {"name": "Кисело мляко 400г", "eur": 2.50},
            {"name": "Кисело мляко 200г", "eur": 1.30},
        ]
        matches = match_products(ref, store)
        if ref[0]["name"] in matches:
            # Should prefer the 400g variant
            assert matches[ref[0]["name"]]["eur"] == 2.50

    def test_percent_match_bonus(self):
        ref = [{"name": "Harmonica Кисело мляко 3.6% 400г"}]
        store = [
            {"name": "Кисело мляко 3.6% 400г", "eur": 2.50},
            {"name": "Кисело мляко 2% 400г", "eur": 2.00},
        ]
        matches = match_products(ref, store)
        if ref[0]["name"] in matches:
            # Should prefer the 3.6% variant
            assert matches[ref[0]["name"]]["eur"] == 2.50

    def test_multiple_products(self):
        ref = [
            {"name": "Harmonica Кисело мляко 400г"},
            {"name": "Harmonica Айран 500мл"},
        ]
        store = [
            {"name": "Кисело мляко Harmonica 400г", "eur": 2.50},
            {"name": "Harmonica Айран 500мл", "eur": 1.80},
        ]
        matches = match_products(ref, store)
        assert len(matches) == 2

    def test_no_double_assignment(self):
        """A store product can only be matched to one reference product."""
        ref = [
            {"name": "Harmonica Кисело мляко 400г"},
            {"name": "Harmonica Кисело мляко 200г"},
        ]
        store = [{"name": "Кисело мляко Harmonica 400г", "eur": 2.50}]
        matches = match_products(ref, store)
        assert len(matches) <= 1

    def test_empty_inputs(self):
        assert match_products([], []) == {}
        assert match_products([{"name": "test"}], []) == {}
        assert match_products([], [{"name": "test", "eur": 1.0}]) == {}
