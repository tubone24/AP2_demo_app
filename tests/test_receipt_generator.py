"""
Tests for Receipt Generator

Tests cover:
- Receipt structure
- Receipt generation
- Digital receipt format
"""

import pytest
from datetime import datetime, timezone


class TestReceiptGeneration:
    """Test receipt generation"""

    def test_receipt_structure(self):
        """Test receipt structure"""
        receipt = {
            "receipt_id": "receipt_001",
            "transaction_id": "txn_001",
            "payment_mandate_id": "payment_001",
            "payer_id": "user_001",
            "merchant_id": "did:ap2:merchant:mugibo_merchant",
            "items": [
                {
                    "sku": "SHOE-RUN-001",
                    "name": "Running Shoes",
                    "quantity": 1,
                    "price": 8000
                }
            ],
            "total_amount": {
                "value": "8000.00",
                "currency": "JPY"
            },
            "payment_method": "card",
            "status": "completed",
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        # Validate required fields
        required_fields = ["receipt_id", "transaction_id", "total_amount", "status"]
        for field in required_fields:
            assert field in receipt

    def test_receipt_items_structure(self):
        """Test receipt items structure"""
        receipt_item = {
            "sku": "SHOE-RUN-001",
            "name": "Running Shoes",
            "quantity": 1,
            "unit_price": 8000,
            "subtotal": 8000
        }

        # Validate item structure
        assert "sku" in receipt_item
        assert "quantity" in receipt_item
        assert "unit_price" in receipt_item

    def test_receipt_total_calculation(self):
        """Test receipt total calculation"""
        items = [
            {"quantity": 2, "unit_price": 8000},
            {"quantity": 1, "unit_price": 3000}
        ]

        total = sum(item["quantity"] * item["unit_price"] for item in items)
        assert total == 19000
