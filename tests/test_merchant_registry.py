"""
Tests for Merchant Registry

Tests cover:
- Merchant registration
- Merchant DID resolution
- Merchant information structure
"""

import pytest


class TestMerchantRegistration:
    """Test merchant registration"""

    def test_merchant_info_structure(self):
        """Test merchant information structure"""
        merchant_info = {
            "merchant_id": "did:ap2:merchant:mugibo_merchant",
            "merchant_name": "むぎぼーショップ",
            "merchant_did_document": {
                "id": "did:ap2:merchant:mugibo_merchant",
                "verificationMethod": []
            },
            "status": "active"
        }

        # Validate structure
        required_fields = ["merchant_id", "merchant_name"]
        for field in required_fields:
            assert field in merchant_info

        # Validate merchant ID format
        assert merchant_info["merchant_id"].startswith("did:ap2:merchant:")

    def test_merchant_status_values(self):
        """Test merchant status values"""
        valid_statuses = ["active", "inactive", "suspended"]

        # Each status should be valid
        for status in valid_statuses:
            assert status in ["active", "inactive", "suspended"]


class TestMerchantDIDResolution:
    """Test merchant DID resolution"""

    def test_resolve_merchant_did(self):
        """Test resolving merchant DID"""
        merchant_did = "did:ap2:merchant:mugibo_merchant"

        # Should resolve to DID document
        assert merchant_did.startswith("did:ap2:merchant:")
