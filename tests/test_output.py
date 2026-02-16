"""
Tests for output modules — email_report.py and sheets.py.

Smoke tests verify the code runs without errors, without actual SMTP/Sheets calls.
"""

import os
from unittest.mock import patch, MagicMock

from output.email_report import send_email_report
from output.sheets import write_to_sheets, extract_weight


# =============================================================================
# extract_weight
# =============================================================================

class TestExtractWeight:
    def test_grams_cyrillic(self):
        assert extract_weight("Био вафла 30г") == "30г"

    def test_grams_latin(self):
        assert extract_weight("Wafer 30g") == "30g"

    def test_ml_cyrillic(self):
        assert extract_weight("Сок 750мл") == "750мл"

    def test_ml_latin(self):
        assert extract_weight("Juice 330ml") == "330ml"

    def test_kg(self):
        assert extract_weight("Ориз 1kg") == "1kg"

    def test_decimal_weight(self):
        assert extract_weight("Мляко 1.5л") == "1.5л"

    def test_no_weight(self):
        assert extract_weight("Продукт без грамаж") == ""


# =============================================================================
# send_email_report — smoke tests (no SMTP)
# =============================================================================

class TestSendEmailReport:
    def _make_products(self, count=3):
        """Create minimal final_products list."""
        products = []
        for i in range(count):
            products.append({
                "name": f"Test Product {i} 400g",
                "kashon": {"eur": 1.5 + i * 0.1, "bgn": 2.93 + i * 0.2},
                "status": "active",
            })
        return products

    def test_skips_without_credentials(self):
        """No error when Gmail credentials are missing."""
        with patch.dict(os.environ, {}, clear=True):
            # Should return None silently (no error)
            send_email_report(self._make_products(), {})

    def test_html_generation_with_credentials(self):
        """HTML is generated and SMTP is called when credentials exist."""
        env = {
            "GMAIL_USER": "test@gmail.com",
            "GMAIL_APP_PASSWORD": "fake-password",
            "ALERT_EMAIL": "recipient@gmail.com",
            "SPREADSHEET_ID": "fake-id-123",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("output.email_report.smtplib") as mock_smtp:
                mock_server = MagicMock()
                mock_smtp.SMTP.return_value.__enter__ = MagicMock(return_value=mock_server)
                mock_smtp.SMTP.return_value.__exit__ = MagicMock(return_value=False)

                send_email_report(self._make_products(), {})

                # SMTP was called
                mock_smtp.SMTP.assert_called_once_with("smtp.gmail.com", 587)

    def test_html_with_health_alerts(self):
        """Health alerts section renders without error."""
        env = {
            "GMAIL_USER": "test@gmail.com",
            "GMAIL_APP_PASSWORD": "fake-password",
            "ALERT_EMAIL": "recipient@gmail.com",
        }
        health_alerts = [
            {"store": "zelen", "type": "zero", "previous": 15},
            {"store": "ebag", "type": "drop", "current": 5, "previous": 20, "drop_pct": 75},
        ]
        with patch.dict(os.environ, env, clear=False):
            with patch("output.email_report.smtplib") as mock_smtp:
                mock_server = MagicMock()
                mock_smtp.SMTP.return_value.__enter__ = MagicMock(return_value=mock_server)
                mock_smtp.SMTP.return_value.__exit__ = MagicMock(return_value=False)

                send_email_report(self._make_products(), {}, health_alerts=health_alerts)

    def test_empty_products(self):
        """No error with zero products."""
        env = {
            "GMAIL_USER": "test@gmail.com",
            "GMAIL_APP_PASSWORD": "fake-password",
            "ALERT_EMAIL": "recipient@gmail.com",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("output.email_report.smtplib") as mock_smtp:
                mock_server = MagicMock()
                mock_smtp.SMTP.return_value.__enter__ = MagicMock(return_value=mock_server)
                mock_smtp.SMTP.return_value.__exit__ = MagicMock(return_value=False)

                send_email_report([], {})


# =============================================================================
# write_to_sheets — smoke tests (mock gspread)
# =============================================================================

class TestWriteToSheets:
    def test_skips_when_gspread_unavailable(self, monkeypatch):
        """Returns False when gspread is not available."""
        monkeypatch.setattr("output.sheets.GSPREAD_AVAILABLE", False)
        result = write_to_sheets([], {})
        assert result is False

    def test_extract_weight_used_in_sheets(self):
        """Verify extract_weight is importable from output package."""
        from output import extract_weight as ew
        assert ew("Сок 1л") == "1л"
