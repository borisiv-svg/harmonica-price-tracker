"""
Tests for extractor modules.

Each test loads a markdown fixture and verifies the extractor returns
the expected products with correct names and prices.
"""

import os

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), "r", encoding="utf-8") as f:
        return f.read()


from extractors import (
    extract_kashon_products,
    extract_ebag_products,
    extract_balev_products,
    _extract_generic_products,
    extract_metro_products,
    extract_randi_products,
)


# -- Helpers --

def _names(products):
    """Extract sorted list of product names."""
    return sorted(p["name"] for p in products)


def _find(products, substring):
    """Find a product by name substring."""
    for p in products:
        if substring.lower() in p["name"].lower():
            return p
    return None


# -- Kashon --

class TestKashonExtractor:
    def test_extracts_products(self):
        md = load_fixture("kashon.md")
        products = extract_kashon_products(md)
        assert len(products) >= 3

    def test_filters_logo_and_navigation(self):
        md = load_fixture("kashon.md")
        products = extract_kashon_products(md)
        names = [p["name"].lower() for p in products]
        assert not any("logo" in n for n in names)
        assert not any("нови продукти" in n for n in names)

    def test_extracts_eur_and_bgn(self):
        md = load_fixture("kashon.md")
        products = extract_kashon_products(md)
        mlyako = _find(products, "мляко")
        assert mlyako is not None
        assert mlyako["eur"] == 2.50
        assert mlyako["bgn"] == 4.89

    def test_returns_correct_structure(self):
        md = load_fixture("kashon.md")
        products = extract_kashon_products(md)
        for p in products:
            assert "name" in p
            assert "eur" in p
            assert "bgn" in p

    def test_empty_input(self):
        assert extract_kashon_products("") == []

    def test_no_kashon_links(self):
        assert extract_kashon_products("No products here, just text.") == []


# -- eBag --

class TestEbagExtractor:
    def test_extracts_harmonica_only(self):
        md = load_fixture("ebag.md")
        products = extract_ebag_products(md)
        # Should have Harmonica products, not Dove
        assert len(products) >= 2
        names = [p["name"].lower() for p in products]
        assert not any("dove" in n for n in names)

    def test_image_link_format(self):
        md = load_fixture("ebag.md")
        products = extract_ebag_products(md)
        ayran = _find(products, "айран")
        assert ayran is not None
        assert ayran["eur"] is not None

    def test_title_format(self):
        md = load_fixture("ebag.md")
        products = extract_ebag_products(md)
        sirene = _find(products, "сирене")
        assert sirene is not None
        assert sirene["eur"] == 3.50
        assert sirene["bgn"] == 6.85

    def test_empty_input(self):
        assert extract_ebag_products("") == []


# -- Balev --

class TestBalevExtractor:
    def test_extracts_food_products(self):
        md = load_fixture("balev.md")
        products = extract_balev_products(md)
        # Should find products with weight markers that are food
        assert len(products) >= 2

    def test_converts_bgn_to_eur(self):
        md = load_fixture("balev.md")
        products = extract_balev_products(md)
        for p in products:
            assert p["eur"] is not None, f"{p['name']} should have EUR price"

    def test_empty_input(self):
        assert extract_balev_products("") == []


# -- Metro --

class TestMetroExtractor:
    def test_extracts_harmonica_products(self):
        md = load_fixture("metro.md")
        products = extract_metro_products(md)
        assert len(products) >= 2

    def test_link_format(self):
        md = load_fixture("metro.md")
        products = extract_metro_products(md)
        mlyako = _find(products, "мляко")
        assert mlyako is not None
        assert mlyako["bgn"] == 4.99

    def test_link_format_sok(self):
        md = load_fixture("metro.md")
        products = extract_metro_products(md)
        sok = _find(products, "сок")
        assert sok is not None
        assert sok["bgn"] == 6.50

    def test_empty_input(self):
        assert extract_metro_products("") == []


# -- Randi --

class TestRandiExtractor:
    def test_extracts_food_products(self):
        md = load_fixture("randi.md")
        products = extract_randi_products(md)
        assert len(products) >= 2

    def test_price_extraction(self):
        md = load_fixture("randi.md")
        products = extract_randi_products(md)
        maslo = _find(products, "фъстъчено")
        assert maslo is not None
        assert maslo["bgn"] == 8.50

    def test_empty_input(self):
        assert extract_randi_products("") == []


# -- Generic --

class TestGenericExtractor:
    def test_brand_page_mode(self):
        md = load_fixture("generic.md")
        products = _extract_generic_products(md, brand_page=True)
        assert len(products) >= 2

    def test_non_brand_page_filters_non_harmonica(self):
        md = load_fixture("generic.md")
        products = _extract_generic_products(md, brand_page=False)
        for p in products:
            name_lower = p["name"].lower()
            assert "harmonica" in name_lower or "хармоника" in name_lower

    def test_empty_input(self):
        assert _extract_generic_products("", brand_page=True) == []


# -- Edge cases --

class TestExtractorEdgeCases:
    def test_all_extractors_handle_garbage_input(self):
        garbage = "🎵🎶🎵 random unicode ñ ü ö 日本語 العربية"
        assert extract_kashon_products(garbage) == []
        assert extract_ebag_products(garbage) == []
        assert extract_balev_products(garbage) == []
        assert extract_metro_products(garbage) == []
        assert extract_randi_products(garbage) == []
        assert _extract_generic_products(garbage) == []

    def test_all_extractors_handle_huge_whitespace(self):
        ws = "\n" * 1000 + " " * 1000
        assert extract_kashon_products(ws) == []
        assert extract_ebag_products(ws) == []
        assert extract_balev_products(ws) == []
        assert extract_metro_products(ws) == []
        assert extract_randi_products(ws) == []
        assert _extract_generic_products(ws) == []
