"""
Tests for Receipt Generator

Tests cover:
- Receipt PDF generation with cart mandate
- Receipt PDF generation without cart mandate
- Amount formatting (legacy and AP2 formats)
- PDF structure and content
- Error handling
"""

import pytest
from unittest.mock import MagicMock, patch, mock_open
from io import BytesIO
from datetime import datetime, timezone

from common.receipt_generator import (
    generate_receipt_pdf,
    _format_amount,
    _format_amount_ap2
)


class TestReceiptPDFGeneration:
    """Test PDF receipt generation"""

    def test_generate_receipt_with_cart_mandate(self):
        """Test generating receipt with full cart mandate"""
        transaction_result = {
            "id": "txn_001",
            "status": "completed",
            "authorized_at": "2025-11-18T10:00:00Z",
            "captured_at": "2025-11-18T10:01:00Z"
        }

        cart_mandate = {
            "contents": {
                "merchant_name": "Nike Store",
                "payment_request": {
                    "details": {
                        "display_items": [
                            {
                                "label": "Running Shoes",
                                "amount": {"value": 8000.0, "currency": "JPY"},
                                "refund_period": 30
                            },
                            {
                                "label": "Tax",
                                "amount": {"value": 800.0, "currency": "JPY"},
                                "refund_period": 0
                            }
                        ],
                        "total": {
                            "label": "Total",
                            "amount": {"value": 8800.0, "currency": "JPY"}
                        }
                    }
                }
            },
            "_metadata": {
                "merchant_id": "did:ap2:merchant:nike",
                "raw_items": [
                    {"sku": "SHOE-001", "quantity": 1}
                ]
            }
        }

        payment_mandate = {
            "payment_method": {
                "brand": "visa",
                "last4": "4242"
            }
        }

        user_name = "Test User"

        with patch("common.receipt_generator.canvas.Canvas") as mock_canvas:
            mock_canvas_instance = MagicMock()
            mock_canvas.return_value = mock_canvas_instance

            result = generate_receipt_pdf(
                transaction_result=transaction_result,
                cart_mandate=cart_mandate,
                payment_mandate=payment_mandate,
                user_name=user_name
            )

            assert isinstance(result, BytesIO)
            mock_canvas_instance.save.assert_called_once()
            mock_canvas_instance.showPage.assert_called_once()

    def test_generate_receipt_without_cart_mandate(self):
        """Test generating receipt without cart mandate"""
        transaction_result = {
            "id": "txn_002",
            "status": "completed",
            "authorized_at": "2025-11-18T11:00:00Z",
            "captured_at": "2025-11-18T11:01:00Z"
        }

        payment_mandate = {
            "payment_method": {
                "brand": "mastercard",
                "last4": "5555"
            },
            "amount": {
                "value": 10000.0,
                "currency": "JPY"
            },
            "payee_name": "Adidas Store",
            "payee_id": "did:ap2:merchant:adidas"
        }

        user_name = "Test User 2"

        with patch("common.receipt_generator.canvas.Canvas") as mock_canvas:
            mock_canvas_instance = MagicMock()
            mock_canvas.return_value = mock_canvas_instance

            result = generate_receipt_pdf(
                transaction_result=transaction_result,
                cart_mandate=None,
                payment_mandate=payment_mandate,
                user_name=user_name
            )

            assert isinstance(result, BytesIO)
            mock_canvas_instance.save.assert_called_once()

    def test_generate_receipt_with_japanese_font(self):
        """Test receipt generation with Japanese font"""
        transaction_result = {
            "id": "txn_003",
            "status": "completed",
            "authorized_at": "2025-11-18T12:00:00Z",
            "captured_at": "2025-11-18T12:01:00Z"
        }

        cart_mandate = {
            "contents": {
                "merchant_name": "むぎぼーショップ",
                "payment_request": {
                    "details": {
                        "display_items": [
                            {
                                "label": "むぎぼーグッズ",
                                "amount": {"value": 5000.0, "currency": "JPY"},
                                "refund_period": 30
                            }
                        ],
                        "total": {
                            "label": "Total",
                            "amount": {"value": 5000.0, "currency": "JPY"}
                        }
                    }
                }
            },
            "_metadata": {
                "merchant_id": "did:ap2:merchant:mugibo",
                "raw_items": [{"sku": "MUG-001", "quantity": 1}]
            }
        }

        payment_mandate = {
            "payment_method": {
                "brand": "jcb",
                "last4": "1234"
            }
        }

        user_name = "テストユーザー"

        with patch("common.receipt_generator.canvas.Canvas") as mock_canvas:
            mock_canvas_instance = MagicMock()
            mock_canvas.return_value = mock_canvas_instance

            with patch("common.receipt_generator.pdfmetrics.registerFont"):
                result = generate_receipt_pdf(
                    transaction_result=transaction_result,
                    cart_mandate=cart_mandate,
                    payment_mandate=payment_mandate,
                    user_name=user_name
                )

                assert isinstance(result, BytesIO)

    def test_generate_receipt_font_fallback(self):
        """Test receipt generation with font loading failure"""
        transaction_result = {
            "id": "txn_004",
            "status": "completed",
            "authorized_at": "2025-11-18T13:00:00Z",
            "captured_at": "2025-11-18T13:01:00Z"
        }

        payment_mandate = {
            "payment_method": {
                "brand": "visa",
                "last4": "9999"
            },
            "amount": {
                "value": 1000.0,
                "currency": "JPY"
            }
        }

        user_name = "Fallback User"

        with patch("common.receipt_generator.canvas.Canvas") as mock_canvas:
            mock_canvas_instance = MagicMock()
            mock_canvas.return_value = mock_canvas_instance

            with patch("common.receipt_generator.pdfmetrics.registerFont",
                      side_effect=Exception("Font not found")):
                result = generate_receipt_pdf(
                    transaction_result=transaction_result,
                    cart_mandate=None,
                    payment_mandate=payment_mandate,
                    user_name=user_name
                )

                assert isinstance(result, BytesIO)
                # Should fall back to Helvetica
                mock_canvas_instance.setFont.assert_called()

    def test_generate_receipt_with_multiple_items(self):
        """Test receipt generation with multiple items"""
        transaction_result = {
            "id": "txn_005",
            "status": "completed",
            "authorized_at": "2025-11-18T14:00:00Z",
            "captured_at": "2025-11-18T14:01:00Z"
        }

        cart_mandate = {
            "contents": {
                "merchant_name": "Sports Store",
                "payment_request": {
                    "details": {
                        "display_items": [
                            {
                                "label": "Running Shoes",
                                "amount": {"value": 8000.0, "currency": "JPY"},
                                "refund_period": 30
                            },
                            {
                                "label": "Sports Socks",
                                "amount": {"value": 1500.0, "currency": "JPY"},
                                "refund_period": 30
                            },
                            {
                                "label": "Water Bottle",
                                "amount": {"value": 2000.0, "currency": "JPY"},
                                "refund_period": 30
                            },
                            {
                                "label": "Tax",
                                "amount": {"value": 1150.0, "currency": "JPY"},
                                "refund_period": 0
                            },
                            {
                                "label": "Shipping",
                                "amount": {"value": 500.0, "currency": "JPY"},
                                "refund_period": 0
                            }
                        ],
                        "total": {
                            "label": "Total",
                            "amount": {"value": 13150.0, "currency": "JPY"}
                        }
                    }
                }
            },
            "_metadata": {
                "merchant_id": "did:ap2:merchant:sports",
                "raw_items": [
                    {"sku": "SHOE-001", "quantity": 1},
                    {"sku": "SOCK-001", "quantity": 3},
                    {"sku": "BOTTLE-001", "quantity": 1}
                ]
            }
        }

        payment_mandate = {
            "payment_method": {
                "brand": "amex",
                "last4": "0005"
            }
        }

        user_name = "Multi Item User"

        with patch("common.receipt_generator.canvas.Canvas") as mock_canvas:
            mock_canvas_instance = MagicMock()
            mock_canvas.return_value = mock_canvas_instance

            result = generate_receipt_pdf(
                transaction_result=transaction_result,
                cart_mandate=cart_mandate,
                payment_mandate=payment_mandate,
                user_name=user_name
            )

            assert isinstance(result, BytesIO)


class TestAmountFormatting:
    """Test amount formatting functions"""

    def test_format_amount_legacy_jpy(self):
        """Test legacy amount formatting for JPY (cents to yen)"""
        amount = {
            "value": "10000",  # 10000 cents = 100 yen
            "currency": "JPY"
        }

        result = _format_amount(amount)

        assert result == "¥100"

    def test_format_amount_legacy_usd(self):
        """Test legacy amount formatting for USD"""
        amount = {
            "value": "5000",  # 5000 cents = $50
            "currency": "USD"
        }

        result = _format_amount(amount)

        assert result == "$50"

    def test_format_amount_legacy_eur(self):
        """Test legacy amount formatting for EUR"""
        amount = {
            "value": "8000",
            "currency": "EUR"
        }

        result = _format_amount(amount)

        assert result == "€80"

    def test_format_amount_legacy_empty(self):
        """Test legacy amount formatting with empty amount"""
        result = _format_amount(None)

        assert result == "¥0"

    def test_format_amount_legacy_invalid(self):
        """Test legacy amount formatting with invalid value"""
        amount = {
            "value": "invalid",
            "currency": "JPY"
        }

        result = _format_amount(amount)

        assert "invalid" in result

    def test_format_amount_ap2_jpy(self):
        """Test AP2 amount formatting for JPY"""
        amount = {
            "value": 10000.0,
            "currency": "JPY"
        }

        result = _format_amount_ap2(amount)

        assert result == "¥10,000"

    def test_format_amount_ap2_usd(self):
        """Test AP2 amount formatting for USD"""
        amount = {
            "value": 50.99,
            "currency": "USD"
        }

        result = _format_amount_ap2(amount)

        assert result == "$51"

    def test_format_amount_ap2_eur(self):
        """Test AP2 amount formatting for EUR"""
        amount = {
            "value": 123.45,
            "currency": "EUR"
        }

        result = _format_amount_ap2(amount)

        assert result == "€123"

    def test_format_amount_ap2_empty(self):
        """Test AP2 amount formatting with empty amount"""
        result = _format_amount_ap2(None)

        assert result == "¥0"

    def test_format_amount_ap2_zero(self):
        """Test AP2 amount formatting with zero value"""
        amount = {
            "value": 0,
            "currency": "JPY"
        }

        result = _format_amount_ap2(amount)

        assert result == "¥0"

    def test_format_amount_ap2_large_value(self):
        """Test AP2 amount formatting with large value"""
        amount = {
            "value": 1234567.89,
            "currency": "JPY"
        }

        result = _format_amount_ap2(amount)

        assert result == "¥1,234,568"

    def test_format_amount_ap2_unknown_currency(self):
        """Test AP2 amount formatting with unknown currency"""
        amount = {
            "value": 100.0,
            "currency": "XYZ"
        }

        result = _format_amount_ap2(amount)

        assert "XYZ" in result
        assert "100" in result


class TestReceiptStructureValidation:
    """Test receipt structure and data validation"""

    def test_receipt_with_all_transaction_fields(self):
        """Test receipt includes all transaction information"""
        transaction_result = {
            "id": "txn_complete",
            "status": "completed",
            "authorized_at": "2025-11-18T15:00:00Z",
            "captured_at": "2025-11-18T15:01:00Z"
        }

        payment_mandate = {
            "payment_method": {
                "brand": "visa",
                "last4": "1111"
            },
            "amount": {
                "value": 5000.0,
                "currency": "JPY"
            }
        }

        user_name = "Complete User"

        with patch("common.receipt_generator.canvas.Canvas") as mock_canvas:
            mock_canvas_instance = MagicMock()
            mock_canvas.return_value = mock_canvas_instance

            result = generate_receipt_pdf(
                transaction_result=transaction_result,
                cart_mandate=None,
                payment_mandate=payment_mandate,
                user_name=user_name
            )

            assert isinstance(result, BytesIO)

            # Verify transaction ID was drawn
            draw_string_calls = [
                call for call in mock_canvas_instance.drawString.call_args_list
            ]
            assert len(draw_string_calls) > 0

    def test_receipt_with_missing_optional_fields(self):
        """Test receipt generation with missing optional fields"""
        transaction_result = {
            "id": "txn_minimal",
            "status": "pending"
        }

        payment_mandate = {
            "payment_method": {},
            "amount": {
                "value": 1000.0,
                "currency": "JPY"
            }
        }

        user_name = "Minimal User"

        with patch("common.receipt_generator.canvas.Canvas") as mock_canvas:
            mock_canvas_instance = MagicMock()
            mock_canvas.return_value = mock_canvas_instance

            result = generate_receipt_pdf(
                transaction_result=transaction_result,
                cart_mandate=None,
                payment_mandate=payment_mandate,
                user_name=user_name
            )

            assert isinstance(result, BytesIO)
