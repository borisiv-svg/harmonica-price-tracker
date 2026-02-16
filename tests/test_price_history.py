"""
Tests for price_history.py — local JSON price snapshot storage.
"""

import json
import os
import tempfile

import price_history as ph_mod
from price_history import load_history, save_history, record_prices, get_price_trend


# -- Helpers --

def _with_tmp_history(entries=None):
    """Create a temp file, patch HISTORY_PATH, return path."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    if entries is not None:
        json.dump(entries, tmp, ensure_ascii=False)
    tmp.close()
    return tmp.name


def _make_final_products():
    """Create minimal final_products list."""
    return [
        {
            "name": "Кисело мляко 400g",
            "kashon": {"eur": 1.4, "bgn": 2.74},
            "ebag": {"eur": 1.5},
            "balev": {"eur": 1.45},
            "status": "active",
        },
        {
            "name": "Био вафла 30г",
            "kashon": {"eur": 0.65, "bgn": 1.27},
            "ebag": None,
            "balev": {"eur": 0.70},
            "status": "active",
        },
        {
            "name": "Продукт без цени",
            "kashon": None,
            "ebag": None,
            "balev": None,
            "status": "active",
        },
    ]


# -- LoadSaveHistory --

class TestLoadSaveHistory:
    def test_load_empty(self, monkeypatch):
        monkeypatch.setattr(ph_mod, "HISTORY_PATH", "/tmp/nonexistent_ph_12345.json")
        result = load_history()
        assert result == []

    def test_load_corrupted(self, monkeypatch):
        path = _with_tmp_history()
        with open(path, "w") as f:
            f.write("{{{bad")
        monkeypatch.setattr(ph_mod, "HISTORY_PATH", path)
        result = load_history()
        assert result == []
        os.unlink(path)

    def test_save_and_load_roundtrip(self, monkeypatch):
        path = _with_tmp_history([])
        monkeypatch.setattr(ph_mod, "HISTORY_PATH", path)

        entries = [
            {"date": "2026-02-10", "time": "07:00", "product": "Test", "prices": {"ebag": 1.5}},
        ]
        save_history(entries)

        loaded = load_history()
        assert len(loaded) == 1
        assert loaded[0]["product"] == "Test"
        os.unlink(path)

    def test_save_trims_to_max(self, monkeypatch):
        path = _with_tmp_history([])
        monkeypatch.setattr(ph_mod, "HISTORY_PATH", path)
        monkeypatch.setattr(ph_mod, "MAX_ENTRIES", 5)

        entries = [{"date": f"2026-01-{i:02d}", "time": "07:00", "product": "X", "prices": {"e": 1}}
                   for i in range(1, 11)]  # 10 entries
        save_history(entries)

        loaded = load_history()
        assert len(loaded) == 5
        # Should keep the last 5
        assert loaded[0]["date"] == "2026-01-06"
        os.unlink(path)


# -- RecordPrices --

class TestRecordPrices:
    def test_records_products_with_prices(self, monkeypatch):
        path = _with_tmp_history([])
        monkeypatch.setattr(ph_mod, "HISTORY_PATH", path)

        count = record_prices(_make_final_products())
        # 2 products have prices, 1 doesn't
        assert count == 2

        loaded = load_history()
        assert len(loaded) == 2
        names = [e["product"] for e in loaded]
        assert "Кисело мляко 400g" in names
        assert "Био вафла 30г" in names
        assert "Продукт без цени" not in names
        os.unlink(path)

    def test_records_store_prices(self, monkeypatch):
        path = _with_tmp_history([])
        monkeypatch.setattr(ph_mod, "HISTORY_PATH", path)

        record_prices(_make_final_products())
        loaded = load_history()

        mlyako = [e for e in loaded if e["product"] == "Кисело мляко 400g"][0]
        assert mlyako["prices"]["kashon"] == 1.4
        assert mlyako["prices"]["ebag"] == 1.5
        os.unlink(path)

    def test_appends_to_existing(self, monkeypatch):
        existing = [
            {"date": "2026-02-01", "time": "07:00", "product": "Old", "prices": {"ebag": 1.0}},
        ]
        path = _with_tmp_history(existing)
        monkeypatch.setattr(ph_mod, "HISTORY_PATH", path)

        record_prices(_make_final_products())
        loaded = load_history()
        assert len(loaded) == 3  # 1 existing + 2 new
        os.unlink(path)


# -- GetPriceTrend --

class TestGetPriceTrend:
    def test_returns_trend(self, monkeypatch):
        entries = [
            {"date": "2026-02-01", "time": "07:00", "product": "Test 400g",
             "prices": {"ebag": 1.5, "balev": 1.6}},
            {"date": "2026-02-08", "time": "07:00", "product": "Test 400g",
             "prices": {"ebag": 1.55, "balev": 1.65}},
            {"date": "2026-02-15", "time": "07:00", "product": "Test 400g",
             "prices": {"ebag": 1.6}},
        ]
        path = _with_tmp_history(entries)
        monkeypatch.setattr(ph_mod, "HISTORY_PATH", path)

        trend = get_price_trend("Test 400g")
        assert len(trend) == 3
        assert trend[0]["date"] == "2026-02-01"
        assert trend[2]["date"] == "2026-02-15"
        # Prices should be averages
        assert trend[0]["avg_eur"] == 1.55  # (1.5 + 1.6) / 2
        os.unlink(path)

    def test_returns_empty_for_unknown(self, monkeypatch):
        path = _with_tmp_history([])
        monkeypatch.setattr(ph_mod, "HISTORY_PATH", path)
        assert get_price_trend("Nonexistent") == []
        os.unlink(path)

    def test_last_n_weeks(self, monkeypatch):
        entries = [
            {"date": f"2026-02-{i:02d}", "time": "07:00", "product": "X",
             "prices": {"e": 1.0 + i * 0.01}}
            for i in range(1, 11)
        ]
        path = _with_tmp_history(entries)
        monkeypatch.setattr(ph_mod, "HISTORY_PATH", path)

        trend = get_price_trend("X", last_n_weeks=3)
        assert len(trend) == 3
        assert trend[0]["date"] == "2026-02-08"
        os.unlink(path)
