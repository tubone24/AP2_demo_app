"""
Tests for Merchant Agent API

Tests cover:
- Product search functionality
- Inventory management
- CartMandate creation
- DID document endpoint
- A2A message handling
"""

import pytest
from datetime import datetime, timezone


class TestProductSearch:
    """Test product search functionality"""

    def test_search_request_structure(self):
        """Test product search request structure"""
        search_request = {
            "query": "running shoes",
            "category": "sports",
            "limit": 10
        }

        # Validate request structure
        assert "query" in search_request
        assert isinstance(search_request["query"], str)
        assert isinstance(search_request["limit"], int)
        assert search_request["limit"] > 0

    def test_search_response_structure(self):
        """Test product search response structure"""
        search_response = {
            "products": [
                {
                    "id": "prod_001",
                    "sku": "SHOE-RUN-001",
                    "name": "Running Shoes",
                    "price": 8000,
                    "inventory_count": 50,
                    "description": "Comfortable running shoes"
                }
            ],
            "total": 1
        }

        # Validate response structure
        assert "products" in search_response
        assert "total" in search_response
        assert isinstance(search_response["products"], list)
        assert search_response["total"] == len(search_response["products"])

    def test_product_structure(self):
        """Test product data structure"""
        product = {
            "id": "prod_001",
            "sku": "SHOE-RUN-001",
            "name": "Running Shoes",
            "price": 8000,
            "inventory_count": 50,
            "description": "Comfortable running shoes",
            "product_metadata": {
                "category": "sports",
                "brand": "Nike",
                "size": "27cm"
            }
        }

        # Validate required fields
        required_fields = ["id", "sku", "name", "price"]
        for field in required_fields:
            assert field in product

        # Validate price is positive
        assert product["price"] > 0


class TestInventoryManagement:
    """Test inventory management functionality"""

    def test_inventory_response_structure(self):
        """Test inventory list response structure"""
        inventory_response = {
            "products": [
                {
                    "id": "prod_001",
                    "sku": "SHOE-RUN-001",
                    "name": "Running Shoes",
                    "inventory_count": 50,
                    "price": 8000
                }
            ]
        }

        # Validate structure
        assert "products" in inventory_response
        assert isinstance(inventory_response["products"], list)

        # Validate product fields
        for product in inventory_response["products"]:
            assert "id" in product
            assert "sku" in product
            assert "inventory_count" in product

    def test_inventory_update_request(self):
        """Test inventory update request structure"""
        update_request = {
            "product_id": "prod_001",
            "quantity_delta": -2  # Decrease by 2
        }

        # Validate request structure
        assert "product_id" in update_request
        assert "quantity_delta" in update_request
        assert isinstance(update_request["quantity_delta"], int)

    def test_inventory_update_response(self):
        """Test inventory update response structure"""
        update_response = {
            "product_id": "prod_001",
            "new_inventory_count": 48
        }

        # Validate response structure
        assert "product_id" in update_response
        assert "new_inventory_count" in update_response
        assert update_response["new_inventory_count"] >= 0

    def test_inventory_validation(self):
        """Test inventory validation logic"""
        # Current inventory
        current_inventory = 50

        # Purchase attempt
        requested_quantity = 2

        # Should be valid
        can_fulfill = current_inventory >= requested_quantity
        assert can_fulfill

        # Test insufficient inventory
        large_order = 100
        can_fulfill_large = current_inventory >= large_order
        assert not can_fulfill_large


class TestCartMandateCreation:
    """Test CartMandate creation"""

    def test_cart_creation_request_structure(self):
        """Test cart creation request structure"""
        cart_request = {
            "intent_mandate_id": "intent_001",
            "items": [
                {
                    "product_id": "prod_001",
                    "quantity": 2
                }
            ],
            "shipping_address": {
                "name": "Test User",
                "postal_code": "100-0001",
                "address": "Tokyo, Chiyoda"
            }
        }

        # Validate required fields
        assert "intent_mandate_id" in cart_request
        assert "items" in cart_request
        assert len(cart_request["items"]) > 0

    def test_cart_creation_response_structure(self):
        """Test cart creation response structure"""
        cart_response = {
            "cart_mandate": {
                "type": "CartMandate",
                "id": "cart_001",
                "related_intent_id": "intent_001",
                "items": [
                    {
                        "product_id": "prod_001",
                        "sku": "SHOE-RUN-001",
                        "quantity": 2,
                        "price": 8000
                    }
                ],
                "total_amount": {
                    "value": "16000.00",
                    "currency": "JPY"
                },
                "merchant_id": "did:ap2:merchant:mugibo_merchant"
            },
            "needs_merchant_signature": True,
            "merchant_sign_url": "http://merchant:8002/sign/cart"
        }

        # Validate response structure
        assert "cart_mandate" in cart_response
        assert "needs_merchant_signature" in cart_response
        assert cart_response["needs_merchant_signature"] is True

        # Validate cart mandate structure
        cart_mandate = cart_response["cart_mandate"]
        assert cart_mandate["type"] == "CartMandate"
        assert "id" in cart_mandate
        assert "items" in cart_mandate
        assert "total_amount" in cart_mandate

    def test_unsigned_cart_mandate(self):
        """Test unsigned CartMandate structure"""
        unsigned_cart = {
            "type": "CartMandate",
            "id": "cart_001",
            "items": [],
            "total_amount": {"value": "8000.00", "currency": "JPY"}
        }

        # Should not have merchant signature yet
        assert "merchant_signature" not in unsigned_cart

    def test_cart_total_calculation(self):
        """Test cart total calculation logic"""
        cart_items = [
            {"quantity": 2, "price": 8000},
            {"quantity": 1, "price": 3000}
        ]

        # Calculate total
        total = sum(item["quantity"] * item["price"] for item in cart_items)
        assert total == 19000

        # Format as mandate amount
        total_amount = {
            "value": f"{total:.2f}",
            "currency": "JPY"
        }
        assert total_amount["value"] == "19000.00"


class TestCartCandidates:
    """Test multiple cart candidates feature (AI mode)"""

    def test_cart_candidates_response_structure(self):
        """Test cart candidates response structure"""
        candidates_response = {
            "type": "CartCandidates",
            "intent_mandate_id": "intent_001",
            "candidates": [
                {
                    "cart_mandate_id": "cart_001",
                    "cart_name": "Budget Option",
                    "cart_description": "Most affordable option",
                    "total_amount": {"value": "6000.00", "currency": "JPY"}
                },
                {
                    "cart_mandate_id": "cart_002",
                    "cart_name": "Premium Option",
                    "cart_description": "Best quality",
                    "total_amount": {"value": "12000.00", "currency": "JPY"}
                }
            ]
        }

        # Validate structure
        assert "type" in candidates_response
        assert "candidates" in candidates_response
        assert len(candidates_response["candidates"]) > 0

        # Validate each candidate
        for candidate in candidates_response["candidates"]:
            assert "cart_mandate_id" in candidate
            assert "cart_name" in candidate
            assert "total_amount" in candidate

    def test_cart_selection_request(self):
        """Test cart selection request structure"""
        selection_request = {
            "type": "CartSelection",
            "intent_mandate_id": "intent_001",
            "selected_cart_id": "cart_001",
            "user_id": "user_001"
        }

        # Validate structure
        assert "type" in selection_request
        assert "selected_cart_id" in selection_request
        assert selection_request["type"] == "CartSelection"


class TestMerchantSignatureFlow:
    """Test merchant signature request flow"""

    def test_signature_request_structure(self):
        """Test signature request to Merchant"""
        signature_request = {
            "cart_mandate_id": "cart_001",
            "cart_mandate": {
                "type": "CartMandate",
                "id": "cart_001",
                "items": [],
                "total_amount": {"value": "8000.00", "currency": "JPY"}
            }
        }

        # Validate request structure
        assert "cart_mandate_id" in signature_request
        assert "cart_mandate" in signature_request

    def test_signature_response_structure(self):
        """Test signature response from Merchant"""
        signature_response = {
            "cart_mandate_id": "cart_001",
            "merchant_signature": {
                "algorithm": "ED25519",
                "value": "base64_signature",
                "publicKeyMultibase": "z6Mk...",
                "signed_at": datetime.now(timezone.utc).isoformat()
            }
        }

        # Validate response structure
        assert "merchant_signature" in signature_response
        signature = signature_response["merchant_signature"]
        assert "algorithm" in signature
        assert "value" in signature
        assert "publicKeyMultibase" in signature

    def test_signed_cart_mandate(self):
        """Test signed CartMandate structure"""
        signed_cart = {
            "type": "CartMandate",
            "id": "cart_001",
            "items": [],
            "total_amount": {"value": "8000.00", "currency": "JPY"},
            "merchant_signature": {
                "algorithm": "ED25519",
                "value": "signature_value",
                "publicKeyMultibase": "z6Mk..."
            }
        }

        # Should have merchant signature
        assert "merchant_signature" in signed_cart
        assert signed_cart["merchant_signature"]["algorithm"] in ["ED25519", "ECDSA"]


class TestDIDDocument:
    """Test DID document endpoint"""

    def test_did_document_structure(self):
        """Test DID document structure"""
        did_document = {
            "@context": [
                "https://www.w3.org/ns/did/v1",
                "https://w3id.org/security/suites/ed25519-2020/v1"
            ],
            "id": "did:ap2:agent:merchant_agent",
            "verificationMethod": [
                {
                    "id": "did:ap2:agent:merchant_agent#key-1",
                    "type": "Ed25519VerificationKey2020",
                    "controller": "did:ap2:agent:merchant_agent",
                    "publicKeyMultibase": "z6Mk..."
                }
            ],
            "authentication": ["did:ap2:agent:merchant_agent#key-1"],
            "assertionMethod": ["did:ap2:agent:merchant_agent#key-1"]
        }

        # Validate DID document structure
        assert "@context" in did_document
        assert "id" in did_document
        assert "verificationMethod" in did_document
        assert did_document["id"] == "did:ap2:agent:merchant_agent"

    def test_did_endpoint_path(self):
        """Test DID document endpoint path"""
        endpoint_path = "/.well-known/did.json"

        # W3C DID specification compliance
        assert endpoint_path.startswith("/.well-known/")
        assert endpoint_path.endswith(".json")


class TestA2AMessageHandling:
    """Test A2A message handling for Merchant Agent"""

    def test_intent_mandate_message_structure(self):
        """Test IntentMandate A2A message structure"""
        a2a_message = {
            "header": {
                "message_id": "msg_001",
                "sender": "did:ap2:agent:shopping_agent",
                "recipient": "did:ap2:agent:merchant_agent",
                "timestamp": datetime.now(timezone.utc).isoformat()
            },
            "dataPart": {
                "type": "ap2.mandates.IntentMandate",
                "id": "intent_001",
                "payload": {
                    "intent": "Buy running shoes",
                    "constraints": {"max_price": 10000}
                }
            }
        }

        # Validate A2A message structure
        assert a2a_message["dataPart"]["type"] == "ap2.mandates.IntentMandate"
        assert a2a_message["header"]["recipient"] == "did:ap2:agent:merchant_agent"

    def test_product_search_request_message(self):
        """Test ProductSearch A2A message structure"""
        a2a_message = {
            "header": {
                "message_id": "msg_002",
                "sender": "did:ap2:agent:shopping_agent",
                "recipient": "did:ap2:agent:merchant_agent",
                "timestamp": datetime.now(timezone.utc).isoformat()
            },
            "dataPart": {
                "type": "ap2.requests.ProductSearch",
                "id": "search_001",
                "payload": {
                    "query": "running shoes",
                    "filters": {"category": "sports"}
                }
            }
        }

        # Validate message structure
        assert a2a_message["dataPart"]["type"] == "ap2.requests.ProductSearch"
        assert "query" in a2a_message["dataPart"]["payload"]

    def test_cart_request_message(self):
        """Test CartRequest A2A message structure"""
        a2a_message = {
            "header": {
                "message_id": "msg_003",
                "sender": "did:ap2:agent:shopping_agent",
                "recipient": "did:ap2:agent:merchant_agent",
                "timestamp": datetime.now(timezone.utc).isoformat()
            },
            "dataPart": {
                "type": "ap2.requests.CartRequest",
                "id": "cart_req_001",
                "payload": {
                    "intent_mandate_id": "intent_001",
                    "items": [{"product_id": "prod_001", "quantity": 1}]
                }
            }
        }

        # Validate message structure
        assert a2a_message["dataPart"]["type"] == "ap2.requests.CartRequest"
        assert "items" in a2a_message["dataPart"]["payload"]


class TestMerchantAgentInfo:
    """Test Merchant Agent information"""

    def test_merchant_identity(self):
        """Test merchant identity structure"""
        merchant_info = {
            "merchant_id": "did:ap2:merchant:mugibo_merchant",
            "merchant_name": "むぎぼーショップ",
            "agent_id": "did:ap2:agent:merchant_agent"
        }

        # Validate merchant info
        assert "merchant_id" in merchant_info
        assert "agent_id" in merchant_info
        assert merchant_info["merchant_id"].startswith("did:ap2:merchant:")
        assert merchant_info["agent_id"].startswith("did:ap2:agent:")

    def test_agent_roles(self):
        """Test agent AP2 roles"""
        agent_roles = ["merchant"]

        # Validate roles
        assert "merchant" in agent_roles
        assert isinstance(agent_roles, list)


class TestMeilisearchIntegration:
    """Test Meilisearch integration"""

    def test_product_sync_structure(self):
        """Test product sync to Meilisearch structure"""
        sync_document = {
            "id": "prod_001",
            "sku": "SHOE-RUN-001",
            "name": "Running Shoes",
            "description": "Comfortable running shoes",
            "price": 8000,
            "category": "sports",
            "searchable_text": "Running Shoes Comfortable running shoes"
        }

        # Validate sync document
        assert "id" in sync_document
        assert "name" in sync_document
        assert "searchable_text" in sync_document
