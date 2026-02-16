"""
Tests for products.py — load, update, and save the reference product list.
"""

import json
import os
import tempfile

import products as products_mod
from products import load_product_list, update_product_list_with_new, save_product_list


# -- Helpers --

def _make_products_json(product_list, path):
    """Write a minimal harmonica_products.json to the given path."""
    data = {
        "version": "2.0",
        "last_sync": "2026-01-01",
        "source": "test",
        "total_products": len(product_list),
        "products": product_list,
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _with_tmp_products(product_list):
    """Context-like helper: writes products JSON to a temp file, patches PRODUCTS_JSON_PATH, returns path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir=tempfile.gettempdir()
    )
    tmp.close()
    _make_products_json(product_list, tmp.name)
    return tmp.name


# -- LoadProductList --

class TestLoadProductList:
    def test_loads_active_products(self, monkeypatch):
        path = _with_tmp_products([
            {"name": "Кисело мляко 400g", "ref_eur": 1.4, "ref_bgn": 2.74,
             "active": True, "status": "active"},
            {"name": "Removed product", "ref_eur": 1.0, "ref_bgn": 1.96,
             "active": False, "status": "removed"},
        ])
        monkeypatch.setattr("products.PRODUCTS_JSON_PATH", path)
        result = load_product_list()
        assert len(result) == 1
        assert result[0]["name"] == "Кисело мляко 400g"
        os.unlink(path)

    def test_returns_empty_for_missing_file(self, monkeypatch):
        monkeypatch.setattr("products.PRODUCTS_JSON_PATH", "/tmp/nonexistent_12345.json")
        result = load_product_list()
        assert result == []

    def test_returns_empty_for_corrupted_json(self, monkeypatch):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write("{{{bad json")
        tmp.close()
        monkeypatch.setattr("products.PRODUCTS_JSON_PATH", tmp.name)
        result = load_product_list()
        assert result == []
        os.unlink(tmp.name)

    def test_calculates_eur_from_bgn_when_missing(self, monkeypatch):
        path = _with_tmp_products([
            {"name": "Продукт без EUR", "ref_bgn": 5.87, "active": True, "status": "active"},
        ])
        monkeypatch.setattr("products.PRODUCTS_JSON_PATH", path)
        result = load_product_list()
        assert len(result) == 1
        assert result[0]["ref_eur"] is not None
        assert result[0]["ref_eur"] > 0
        os.unlink(path)

    def test_preserves_all_fields(self, monkeypatch):
        path = _with_tmp_products([
            {"name": "Full product", "ref_eur": 2.0, "ref_bgn": 3.91,
             "url_slug": "full-product", "active": True, "status": "active",
             "added_date": "2026-01-15"},
        ])
        monkeypatch.setattr("products.PRODUCTS_JSON_PATH", path)
        result = load_product_list()
        p = result[0]
        assert p["url_slug"] == "full-product"
        assert p["added_date"] == "2026-01-15"
        assert p["status"] == "active"
        os.unlink(path)


# -- UpdateProductListWithNew --

class TestUpdateProductListWithNew:
    def test_adds_new_kashon_products(self, monkeypatch):
        path = _with_tmp_products([
            {"name": "Existing product", "ref_eur": 1.0, "ref_bgn": 1.96,
             "active": True, "status": "active"},
        ])
        monkeypatch.setattr("products.PRODUCTS_JSON_PATH", path)
        ref = load_product_list()

        kashon = [
            {"name": "Existing product", "eur": 1.0, "bgn": 1.96},
            {"name": "Brand new item 400g", "eur": 3.5, "bgn": 6.85},
        ]
        updated = update_product_list_with_new(ref, kashon)
        names = [p["name"] for p in updated]
        assert "Brand new item 400g" in names
        assert len(updated) == 2
        os.unlink(path)

    def test_new_products_marked_as_new(self, monkeypatch):
        path = _with_tmp_products([])
        monkeypatch.setattr("products.PRODUCTS_JSON_PATH", path)
        ref = load_product_list()

        kashon = [{"name": "New product 500ml", "eur": 2.0, "bgn": 3.91}]
        updated = update_product_list_with_new(ref, kashon)
        assert updated[0]["status"] == "new"
        assert updated[0]["active"] is True
        os.unlink(path)

    def test_does_not_duplicate_existing(self, monkeypatch):
        path = _with_tmp_products([
            {"name": "Кисело мляко 400g", "ref_eur": 1.4, "ref_bgn": 2.74,
             "active": True, "status": "active"},
        ])
        monkeypatch.setattr("products.PRODUCTS_JSON_PATH", path)
        ref = load_product_list()

        kashon = [{"name": "Кисело мляко 400g", "eur": 1.4, "bgn": 2.74}]
        updated = update_product_list_with_new(ref, kashon)
        assert len(updated) == 1

        os.unlink(path)

    def test_case_insensitive_duplicate_check(self, monkeypatch):
        path = _with_tmp_products([
            {"name": "Bio Wafer 30g", "ref_eur": 0.7, "ref_bgn": 1.37,
             "active": True, "status": "active"},
        ])
        monkeypatch.setattr("products.PRODUCTS_JSON_PATH", path)
        ref = load_product_list()

        kashon = [{"name": "bio wafer 30g", "eur": 0.7, "bgn": 1.37}]
        updated = update_product_list_with_new(ref, kashon)
        assert len(updated) == 1
        os.unlink(path)

    def test_does_not_readd_removed_products(self, monkeypatch):
        path = _with_tmp_products([
            {"name": "Active item", "ref_eur": 1.0, "ref_bgn": 1.96,
             "active": True, "status": "active"},
            {"name": "Removed item", "ref_eur": 2.0, "ref_bgn": 3.91,
             "active": False, "status": "removed"},
        ])
        monkeypatch.setattr("products.PRODUCTS_JSON_PATH", path)
        ref = load_product_list()  # returns only active

        kashon = [{"name": "Removed item", "eur": 2.0, "bgn": 3.91}]
        updated = update_product_list_with_new(ref, kashon)
        # "Removed item" should NOT be re-added
        assert len(updated) == 1
        os.unlink(path)


# -- SaveProductList --

class TestSaveProductList:
    def test_roundtrip_save_and_load(self, monkeypatch):
        path = _with_tmp_products([
            {"name": "Test product 200g", "ref_eur": 3.0, "ref_bgn": 5.87,
             "active": True, "status": "active", "added_date": "2026-01-01"},
        ])
        monkeypatch.setattr("products.PRODUCTS_JSON_PATH", path)
        ref = load_product_list()

        save_product_list(ref)

        # Reload and verify
        ref2 = load_product_list()
        assert len(ref2) == 1
        assert ref2[0]["name"] == "Test product 200g"
        assert ref2[0]["ref_eur"] == 3.0
        os.unlink(path)

    def test_generates_keywords(self, monkeypatch):
        path = _with_tmp_products([
            {"name": "Био вафла 30г", "ref_eur": 0.7, "ref_bgn": 1.37,
             "active": True, "status": "active"},
        ])
        monkeypatch.setattr("products.PRODUCTS_JSON_PATH", path)
        ref = load_product_list()
        save_product_list(ref)

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        p = data["products"][0]
        assert "keywords" in p
        assert "био" in p["keywords"]
        assert "вафла" in p["keywords"]
        os.unlink(path)

    def test_preserves_removed_products(self, monkeypatch):
        path = _with_tmp_products([
            {"name": "Active product", "ref_eur": 1.0, "ref_bgn": 1.96,
             "active": True, "status": "active"},
            {"name": "Old removed", "ref_eur": 2.0, "ref_bgn": 3.91,
             "active": False, "status": "removed"},
        ])
        monkeypatch.setattr("products.PRODUCTS_JSON_PATH", path)
        ref = load_product_list()  # only active

        save_product_list(ref)

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        names = [p["name"] for p in data["products"]]
        assert "Active product" in names
        assert "Old removed" in names
        os.unlink(path)

    def test_sets_version_and_metadata(self, monkeypatch):
        path = _with_tmp_products([
            {"name": "Product X", "ref_eur": 1.5, "ref_bgn": 2.93,
             "active": True, "status": "active"},
        ])
        monkeypatch.setattr("products.PRODUCTS_JSON_PATH", path)
        ref = load_product_list()
        save_product_list(ref)

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["version"] == "2.0"
        assert data["source"] == "kashonharmonica.bg"
        assert data["total_products"] == 1
        assert "last_sync" in data
        os.unlink(path)

    def test_assigns_sequential_ids(self, monkeypatch):
        path = _with_tmp_products([
            {"name": "First 100g", "ref_eur": 1.0, "ref_bgn": 1.96,
             "active": True, "status": "active"},
            {"name": "Second 200g", "ref_eur": 2.0, "ref_bgn": 3.91,
             "active": True, "status": "active"},
        ])
        monkeypatch.setattr("products.PRODUCTS_JSON_PATH", path)
        ref = load_product_list()
        save_product_list(ref)

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ids = [p["id"] for p in data["products"]]
        assert ids == [1, 2]
        os.unlink(path)
