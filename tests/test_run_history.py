"""
Tests for run_history.py — run history recording, health checks, and alerts.
"""

import json
import os
import tempfile

import run_history
from run_history import (
    load_history,
    save_history,
    build_run_entry,
    check_health,
    format_health_summary,
    record_run,
    get_store_display_name,
    MAX_HISTORY_ENTRIES,
)


# -- Fixtures --

def _sample_store_counts():
    return {
        "ebag": 25,
        "balev": 18,
        "lilly": 12,
        "tmarket": 8,
        "metro": 15,
        "randi": 10,
        "zelen": 30,
        "biomarket": 5,
        "befit": 3,
        "laika": 7,
        "glovo_kaufland": 4,
        "glovo_billa": 3,
        "glovo_cba": 2,
        "glovo_fantastico": 5,
    }


def _sample_entry(overrides=None):
    entry = build_run_entry(_sample_store_counts(), total_ref=88, total_time=360.5)
    if overrides:
        entry["stores"].update(overrides)
    return entry


# -- load_history / save_history --

class TestLoadSaveHistory:
    def test_load_empty_file(self, tmp_path):
        path = tmp_path / "history.json"
        original = run_history.HISTORY_PATH
        run_history.HISTORY_PATH = str(path)
        try:
            assert load_history() == []
        finally:
            run_history.HISTORY_PATH = original

    def test_save_and_load_roundtrip(self, tmp_path):
        path = tmp_path / "history.json"
        original = run_history.HISTORY_PATH
        run_history.HISTORY_PATH = str(path)
        try:
            entries = [_sample_entry(), _sample_entry()]
            save_history(entries)
            loaded = load_history()
            assert len(loaded) == 2
            assert loaded[0]["total_ref"] == 88
        finally:
            run_history.HISTORY_PATH = original

    def test_save_trims_old_entries(self, tmp_path):
        path = tmp_path / "history.json"
        original = run_history.HISTORY_PATH
        run_history.HISTORY_PATH = str(path)
        try:
            entries = [_sample_entry() for _ in range(MAX_HISTORY_ENTRIES + 20)]
            save_history(entries)
            loaded = load_history()
            assert len(loaded) == MAX_HISTORY_ENTRIES
        finally:
            run_history.HISTORY_PATH = original

    def test_load_corrupted_json(self, tmp_path):
        path = tmp_path / "history.json"
        path.write_text("not valid json!!!")
        original = run_history.HISTORY_PATH
        run_history.HISTORY_PATH = str(path)
        try:
            result = load_history()
            assert result == []
        finally:
            run_history.HISTORY_PATH = original


# -- build_run_entry --

class TestBuildRunEntry:
    def test_basic_entry(self):
        counts = {"ebag": 25, "balev": 18}
        entry = build_run_entry(counts, total_ref=88, total_time=360.123)
        assert entry["total_ref"] == 88
        assert entry["total_time"] == 360.1
        assert entry["stores"]["ebag"] == 25
        assert entry["stores"]["balev"] == 18
        assert "date" in entry

    def test_empty_counts(self):
        entry = build_run_entry({}, total_ref=0, total_time=0)
        assert entry["stores"] == {}
        assert entry["total_ref"] == 0


# -- check_health --

class TestCheckHealth:
    def test_no_alerts_when_healthy(self):
        current = _sample_entry()
        previous = _sample_entry()
        alerts = check_health(current, [previous])
        assert len(alerts) == 0

    def test_zero_products_alert(self):
        current = _sample_entry({"ebag": 0})
        previous = _sample_entry()
        alerts = check_health(current, [previous])
        zero_alerts = [a for a in alerts if a["store"] == "ebag"]
        assert len(zero_alerts) == 1
        assert zero_alerts[0]["type"] == "zero"
        assert zero_alerts[0]["current"] == 0
        assert zero_alerts[0]["previous"] == 25

    def test_drop_over_50_percent(self):
        current = _sample_entry({"ebag": 10})  # 25 → 10 = 60% drop
        previous = _sample_entry()
        alerts = check_health(current, [previous])
        drop_alerts = [a for a in alerts if a["store"] == "ebag" and a["type"] == "drop"]
        assert len(drop_alerts) == 1
        assert drop_alerts[0]["drop_pct"] == 60.0

    def test_no_alert_for_small_drop(self):
        current = _sample_entry({"ebag": 20})  # 25 → 20 = 20% drop
        previous = _sample_entry()
        alerts = check_health(current, [previous])
        drop_alerts = [a for a in alerts if a["store"] == "ebag"]
        assert len(drop_alerts) == 0

    def test_no_alert_without_history(self):
        current = _sample_entry({"ebag": 0})
        alerts = check_health(current, [])
        # Still alerts for zero, but no drop since no previous
        zero_alerts = [a for a in alerts if a["type"] == "zero"]
        assert len(zero_alerts) >= 1
        # No drop alerts since no history
        drop_alerts = [a for a in alerts if a["type"] == "drop"]
        assert len(drop_alerts) == 0

    def test_multiple_alerts(self):
        current = _sample_entry({"ebag": 0, "balev": 5})  # 18 → 5 = 72% drop
        previous = _sample_entry()
        alerts = check_health(current, [previous])
        assert len(alerts) >= 2
        stores = {a["store"] for a in alerts}
        assert "ebag" in stores
        assert "balev" in stores

    def test_kashon_not_checked(self):
        """Kashon is master store, should not trigger alerts."""
        counts = _sample_store_counts()
        counts["kashon"] = 0
        current = build_run_entry(counts, 88, 360)
        previous = _sample_entry()
        alerts = check_health(current, [previous])
        kashon_alerts = [a for a in alerts if a["store"] == "kashon"]
        assert len(kashon_alerts) == 0

    def test_exact_50_percent_no_alert(self):
        """Exactly 50% drop should NOT trigger (>50% required)."""
        current = _sample_entry({"randi": 5})  # 10 → 5 = 50% drop
        previous = _sample_entry()
        alerts = check_health(current, [previous])
        randi_alerts = [a for a in alerts if a["store"] == "randi"]
        assert len(randi_alerts) == 0


# -- format_health_summary --

class TestFormatHealthSummary:
    def test_no_alerts(self):
        entry = _sample_entry()
        summary = format_health_summary([], entry)
        assert "Health OK" in summary
        assert "без аномалии" in summary

    def test_with_alerts(self):
        alerts = [
            {"store": "ebag", "type": "zero", "current": 0, "previous": 25},
            {"store": "balev", "type": "drop", "current": 5, "previous": 18, "drop_pct": 72.2},
        ]
        entry = _sample_entry()
        summary = format_health_summary(alerts, entry)
        assert "HEALTH ALERTS" in summary
        assert "2 проблема" in summary
        assert "eBag" in summary
        assert "Balev" in summary


# -- get_store_display_name --

class TestGetStoreDisplayName:
    def test_regular_store(self):
        assert get_store_display_name("ebag") == "eBag"

    def test_glovo_store(self):
        name = get_store_display_name("glovo_kaufland")
        assert "Glovo" in name
        assert "Kaufland" in name

    def test_unknown_store(self):
        assert get_store_display_name("unknown_store") == "unknown_store"


# -- record_run (integration) --

class TestRecordRun:
    def test_record_and_check(self, tmp_path):
        path = tmp_path / "history.json"
        original = run_history.HISTORY_PATH
        run_history.HISTORY_PATH = str(path)
        try:
            # First run — no previous, no drop alerts
            alerts1, summary1 = record_run(_sample_store_counts(), 88, 360)
            # Zero-count stores may still alert, but no drops
            drop_alerts1 = [a for a in alerts1 if a["type"] == "drop"]
            assert len(drop_alerts1) == 0

            # Second run — same counts, should be healthy
            alerts2, summary2 = record_run(_sample_store_counts(), 88, 355)
            assert len(alerts2) == 0
            assert "Health OK" in summary2

            # Third run — ebag drops to 0
            bad_counts = _sample_store_counts()
            bad_counts["ebag"] = 0
            alerts3, summary3 = record_run(bad_counts, 88, 340)
            assert any(a["store"] == "ebag" for a in alerts3)
            assert "HEALTH ALERTS" in summary3

            # Verify history has 3 entries
            history = load_history()
            assert len(history) == 3
        finally:
            run_history.HISTORY_PATH = original
