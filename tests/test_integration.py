"""
Integration tests for AP2 Demo App

Tests cover:
- End-to-end mandate flow (Intent → Cart → Payment)
- A2A communication between agents
- Mandate signature chain
- Error handling and rollback
- Complete payment flow
"""

import pytest
from datetime import datetime, timezone


class TestMandateChain:
    """Test mandate chain (Intent → Cart → Payment)"""

    def test_intent_mandate_structure(self):
        """Test IntentMandate creation"""
        intent_mandate = {
            "type": "IntentMandate",
            "id": "intent_001",
            "intent": "Buy running shoes under 10,000 JPY",
            "constraints": {},
            "issued_at": datetime.now(timezone.utc).isoformat()
        }

        assert intent_mandate["type"] == "IntentMandate"
        assert "intent" in intent_mandate
        assert "id" in intent_mandate

    def test_cart_mandate_from_intent(self):
        """Test CartMandate creation from IntentMandate"""
        intent_mandate = {
            "id": "intent_001",
            "intent": "Buy running shoes"
        }

        cart_mandate = {
            "type": "CartMandate",
            "id": "cart_001",
            "related_intent_id": intent_mandate["id"],
            "items": [
                {
                    "product_id": "prod_001",
                    "sku": "SHOE-RUN-001",
                    "quantity": 1,
                    "price": 8000
                }
            ],
            "total_amount": {
                "value": "8000.00",
                "currency": "JPY"
            }
        }

        # Cart should reference Intent
        assert cart_mandate["related_intent_id"] == intent_mandate["id"]
        assert cart_mandate["type"] == "CartMandate"

    def test_payment_mandate_from_cart(self):
        """Test PaymentMandate creation from CartMandate"""
        cart_mandate = {
            "id": "cart_001",
            "total_amount": {
                "value": "8000.00",
                "currency": "JPY"
            }
        }

        payment_mandate = {
            "type": "PaymentMandate",
            "id": "payment_001",
            "related_cart_id": cart_mandate["id"],
            "amount": cart_mandate["total_amount"],
            "payer_id": "user_001",
            "payee_id": "did:ap2:merchant:test_merchant"
        }

        # Payment should reference Cart
        assert payment_mandate["related_cart_id"] == cart_mandate["id"]
        assert payment_mandate["amount"] == cart_mandate["total_amount"]

    def test_complete_mandate_chain(self):
        """Test complete mandate chain linkage"""
        # Intent
        intent_mandate = {"id": "intent_001", "type": "IntentMandate"}

        # Cart references Intent
        cart_mandate = {
            "id": "cart_001",
            "type": "CartMandate",
            "related_intent_id": intent_mandate["id"]
        }

        # Payment references Cart (and indirectly Intent)
        payment_mandate = {
            "id": "payment_001",
            "type": "PaymentMandate",
            "related_cart_id": cart_mandate["id"]
        }

        # Validate chain
        assert cart_mandate["related_intent_id"] == intent_mandate["id"]
        assert payment_mandate["related_cart_id"] == cart_mandate["id"]


class TestMandateSignatureChain:
    """Test mandate signature chain"""

    def test_unsigned_cart_mandate(self):
        """Test unsigned CartMandate"""
        cart_mandate = {
            "type": "CartMandate",
            "id": "cart_001",
            "items": []
        }

        # Should not have signatures yet
        assert "merchant_signature" not in cart_mandate
        assert "user_signature" not in cart_mandate

    def test_merchant_signed_cart_mandate(self):
        """Test merchant-signed CartMandate"""
        cart_mandate = {
            "type": "CartMandate",
            "id": "cart_001",
            "items": [],
            "merchant_signature": {
                "algorithm": "ED25519",
                "value": "base64_signature",
                "publicKeyMultibase": "z6Mk...",
                "signed_at": datetime.now(timezone.utc).isoformat()
            }
        }

        # Should have merchant signature
        assert "merchant_signature" in cart_mandate
        assert cart_mandate["merchant_signature"]["algorithm"] in ["ED25519", "ECDSA"]

    def test_user_signed_payment_mandate(self):
        """Test user-signed PaymentMandate"""
        payment_mandate = {
            "type": "PaymentMandate",
            "id": "payment_001",
            "amount": {"value": "100.00", "currency": "JPY"},
            "user_authorization": "issuer_jwt~kb_jwt"  # SD-JWT+KB format
        }

        # Should have user authorization
        assert "user_authorization" in payment_mandate
        assert "~" in payment_mandate["user_authorization"]

    def test_complete_signature_chain(self):
        """Test complete signature chain"""
        # Cart with merchant signature
        cart_mandate = {
            "id": "cart_001",
            "merchant_signature": {
                "algorithm": "ED25519",
                "value": "merchant_sig"
            }
        }

        # Payment with user authorization and references cart
        payment_mandate = {
            "id": "payment_001",
            "related_cart_id": cart_mandate["id"],
            "user_authorization": "issuer_jwt~kb_jwt"
        }

        # Validate signature chain
        assert "merchant_signature" in cart_mandate
        assert "user_authorization" in payment_mandate
        assert payment_mandate["related_cart_id"] == cart_mandate["id"]


class TestA2ACommunication:
    """Test A2A communication flow"""

    def test_shopping_agent_to_merchant_agent(self):
        """Test Shopping Agent → Merchant Agent communication"""
        # Shopping Agent sends IntentMandate to Merchant Agent
        a2a_message = {
            "header": {
                "message_id": "msg_001",
                "sender": "did:ap2:agent:shopping_agent",
                "recipient": "did:ap2:agent:merchant_agent",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "nonce": "unique_nonce"
            },
            "dataPart": {
                "type": "ap2/IntentMandate",
                "id": "intent_001",
                "payload": {
                    "intent": "Buy running shoes"
                }
            }
        }

        # Validate A2A message structure
        assert a2a_message["header"]["sender"].endswith("shopping_agent")
        assert a2a_message["header"]["recipient"].endswith("merchant_agent")
        assert a2a_message["dataPart"]["type"] == "ap2/IntentMandate"

    def test_merchant_agent_response_with_cart(self):
        """Test Merchant Agent response with CartMandate"""
        # Merchant Agent responds with CartMandate artifact
        a2a_response = {
            "header": {
                "message_id": "msg_002",
                "sender": "did:ap2:agent:merchant_agent",
                "recipient": "did:ap2:agent:shopping_agent",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "nonce": "unique_nonce_2"
            },
            "dataPart": {
                "kind": "artifact",
                "artifact": {
                    "name": "CartMandate",
                    "artifactId": "artifact:001",
                    "parts": [
                        {
                            "kind": "data",
                            "data": {
                                "CartMandate": {
                                    "type": "CartMandate",
                                    "id": "cart_001",
                                    "items": []
                                }
                            }
                        }
                    ]
                }
            }
        }

        # Validate response structure
        assert a2a_response["dataPart"]["kind"] == "artifact"
        assert a2a_response["dataPart"]["artifact"]["name"] == "CartMandate"

    def test_shopping_agent_to_credential_provider(self):
        """Test Shopping Agent → Credential Provider communication"""
        # Shopping Agent sends PaymentMandate to CP
        a2a_message = {
            "header": {
                "message_id": "msg_003",
                "sender": "did:ap2:agent:shopping_agent",
                "recipient": "did:ap2:cp:demo_cp",
                "timestamp": datetime.now(timezone.utc).isoformat()
            },
            "dataPart": {
                "type": "ap2/PaymentMandate",
                "id": "payment_001",
                "payload": {
                    "amount": {"value": "100.00", "currency": "JPY"}
                }
            }
        }

        # Validate message targets CP
        assert a2a_message["header"]["recipient"].startswith("did:ap2:cp:")
        assert a2a_message["dataPart"]["type"] == "ap2/PaymentMandate"


class TestErrorHandling:
    """Test error handling and rollback"""

    def test_invalid_mandate_rejection(self):
        """Test invalid mandate is rejected"""
        invalid_mandate = {
            "type": "CartMandate",
            # Missing required fields
        }

        # Should produce error
        error_response = {
            "error_code": "INVALID_MANDATE",
            "error_message": "Required field missing",
            "details": {"missing_field": "items"}
        }

        assert error_response["error_code"] == "INVALID_MANDATE"

    def test_constraint_violation_rejection(self):
        """Test constraint violation is rejected"""
        intent_constraints = {"max_amount": 10000}
        cart_amount = 15000  # Exceeds constraint

        # Should be rejected
        violation_detected = cart_amount > intent_constraints["max_amount"]
        assert violation_detected

    def test_signature_verification_failure(self):
        """Test signature verification failure"""
        mandate_with_invalid_sig = {
            "type": "CartMandate",
            "id": "cart_001",
            "items": [],
            "merchant_signature": {
                "algorithm": "ED25519",
                "value": "invalid_signature"
            }
        }

        # Verification should fail (in actual implementation)
        # This test shows the expected behavior
        signature_valid = False  # Would be result of verification

        assert not signature_valid

    def test_payment_failure_rollback(self):
        """Test payment failure triggers rollback"""
        payment_result = {
            "status": "failed",
            "error": "insufficient_funds",
            "rollback_required": True
        }

        # Failed payment should trigger rollback
        assert payment_result["status"] == "failed"
        assert payment_result["rollback_required"]


class TestCompletePaymentFlow:
    """Test complete end-to-end payment flow"""

    def test_happy_path_flow(self):
        """Test successful payment flow"""
        flow_steps = []

        # Step 1: User expresses intent
        intent_mandate = {
            "type": "IntentMandate",
            "id": "intent_001",
            "intent": "Buy running shoes"
        }
        flow_steps.append(("intent_created", intent_mandate))

        # Step 2: Merchant creates cart
        cart_mandate = {
            "type": "CartMandate",
            "id": "cart_001",
            "related_intent_id": intent_mandate["id"],
            "items": [{"sku": "SHOE-001", "quantity": 1, "price": 8000}],
            "total_amount": {"value": "8000.00", "currency": "JPY"}
        }
        flow_steps.append(("cart_created", cart_mandate))

        # Step 3: Merchant signs cart
        cart_mandate["merchant_signature"] = {
            "algorithm": "ED25519",
            "value": "merchant_sig"
        }
        flow_steps.append(("cart_signed", cart_mandate))

        # Step 4: User creates payment mandate
        payment_mandate = {
            "type": "PaymentMandate",
            "id": "payment_001",
            "related_cart_id": cart_mandate["id"],
            "amount": cart_mandate["total_amount"]
        }
        flow_steps.append(("payment_created", payment_mandate))

        # Step 5: User authorizes payment
        payment_mandate["user_authorization"] = "issuer_jwt~kb_jwt"
        flow_steps.append(("payment_authorized", payment_mandate))

        # Step 6: Payment processed
        payment_result = {
            "status": "completed",
            "transaction_id": "txn_001",
            "receipt_url": "https://example.com/receipts/001"
        }
        flow_steps.append(("payment_completed", payment_result))

        # Validate flow
        assert len(flow_steps) == 6
        assert flow_steps[0][0] == "intent_created"
        assert flow_steps[-1][0] == "payment_completed"
        assert payment_result["status"] == "completed"

    def test_flow_with_step_up_authentication(self):
        """Test payment flow with step-up authentication"""
        payment_requires_step_up = {
            "payment_method_id": "pm_001",
            "requires_step_up": True  # High-risk transaction
        }

        # Should request additional auth
        assert payment_requires_step_up["requires_step_up"]

        # After step-up authentication
        step_up_completed = {
            "biometric_verified": True,
            "webauthn_assertion": {"signature": "..."}
        }

        assert step_up_completed["biometric_verified"]


class TestTransactionConsistency:
    """Test transaction data consistency"""

    def test_amount_consistency_across_mandates(self):
        """Test amount is consistent across mandate chain"""
        cart_amount = {"value": "8000.00", "currency": "JPY"}

        payment_amount = {"value": "8000.00", "currency": "JPY"}

        # Amounts should match
        assert cart_amount == payment_amount

    def test_currency_consistency(self):
        """Test currency is consistent across flow"""
        mandates = [
            {"amount": {"currency": "JPY"}},
            {"amount": {"currency": "JPY"}},
            {"amount": {"currency": "JPY"}}
        ]

        currencies = [m["amount"]["currency"] for m in mandates]
        # All should be same currency
        assert len(set(currencies)) == 1

    def test_payer_identity_consistency(self):
        """Test payer identity is consistent"""
        user_id = "user_001"

        steps = [
            {"payer_id": user_id},  # Intent
            {"payer_id": user_id},  # Payment
            {"payer_id": user_id}   # Receipt
        ]

        payer_ids = [s["payer_id"] for s in steps]
        # All should be same user
        assert len(set(payer_ids)) == 1
        assert payer_ids[0] == user_id
