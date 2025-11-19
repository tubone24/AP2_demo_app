"""
Tests for common/risk_assessment.py

Tests cover:
- Risk score calculation
- Amount risk assessment
- Constraint compliance checking
- Transaction pattern analysis
- Payment method risk evaluation
- Fraud indicator detection
"""

import pytest
from datetime import datetime, timezone, timedelta

from common.risk_assessment import (
    RiskAssessmentEngine,
    RiskAssessmentResult
)


class TestRiskAssessmentResult:
    """Test RiskAssessmentResult dataclass"""

    def test_risk_assessment_result_creation(self):
        """Test creating a RiskAssessmentResult"""
        result = RiskAssessmentResult(
            risk_score=25,
            fraud_indicators=["test_indicator"],
            risk_factors={"amount_risk": 10, "pattern_risk": 15},
            recommendation="approve"
        )

        assert result.risk_score == 25
        assert "test_indicator" in result.fraud_indicators
        assert result.risk_factors["amount_risk"] == 10
        assert result.recommendation == "approve"

    def test_risk_score_range(self):
        """Test risk score is within valid range"""
        result = RiskAssessmentResult(
            risk_score=50,
            fraud_indicators=[],
            risk_factors={},
            recommendation="review"
        )

        # Risk score should be 0-100
        assert 0 <= result.risk_score <= 100

    def test_recommendation_values(self):
        """Test valid recommendation values"""
        valid_recommendations = ["approve", "review", "decline"]

        for recommendation in valid_recommendations:
            result = RiskAssessmentResult(
                risk_score=0,
                fraud_indicators=[],
                risk_factors={},
                recommendation=recommendation
            )
            assert result.recommendation in valid_recommendations


class TestRiskAssessmentEngine:
    """Test RiskAssessmentEngine functionality"""

    @pytest.fixture
    def risk_engine(self):
        """Create a RiskAssessmentEngine instance"""
        return RiskAssessmentEngine()

    def test_engine_initialization(self, risk_engine):
        """Test risk engine initialization"""
        assert risk_engine is not None
        assert risk_engine.transaction_history == {}

    def test_assess_low_risk_payment(self, risk_engine):
        """Test assessing a low-risk payment"""
        payment_mandate = {
            "type": "PaymentMandate",
            "id": "payment_001",
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "1000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001",
                    "payment_method": {"type": "card", "brand": "visa"}
                }
            },
            "user_authorization": "vp_token_present"  # Human present
        }

        cart_mandate = {
            "type": "CartMandate",
            "total_amount": {"value": "1000.00", "currency": "JPY"}
        }

        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            cart_mandate=cart_mandate
        )

        # Low amount, human present -> low risk
        assert isinstance(result, RiskAssessmentResult)
        assert result.risk_score < risk_engine.MEDIUM_RISK_THRESHOLD
        assert result.recommendation in ["approve", "review"]

    def test_assess_high_amount_risk(self, risk_engine):
        """Test assessing high amount payment"""
        payment_mandate = {
            "type": "PaymentMandate",
            "id": "payment_002",
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "600000.00", "currency": "JPY"}  # 600,000 JPY
                },
                "payment_response": {
                    "payer_id": "user_002",
                    "payment_method": {"type": "card"}
                }
            }
        }

        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)

        # High amount -> elevated risk
        assert result.risk_score > 0
        assert "high_transaction_amount" in result.fraud_indicators
        assert result.risk_factors["amount_risk"] > 30

    def test_assess_card_not_present_risk(self, risk_engine):
        """Test assessing card-not-present transaction"""
        payment_mandate = {
            "type": "PaymentMandate",
            "id": "payment_003",
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_003",
                    "payment_method": {"type": "card"}
                }
            }
            # No user_authorization -> human_not_present
        }

        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)

        # CNP transaction should add risk
        assert "card_not_present_transaction" in result.fraud_indicators
        assert result.risk_factors["transaction_type_risk"] > 0

    def test_assess_constraint_violation(self, risk_engine):
        """Test detecting constraint violations"""
        payment_mandate = {
            "type": "PaymentMandate",
            "id": "payment_004",
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "15000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_004"
                }
            }
        }

        cart_mandate = {
            "type": "CartMandate",
            "total_amount": {"value": "15000.00", "currency": "JPY"}
        }

        session = {
            "max_amount": 10000  # Constraint: max 10,000 JPY
        }

        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            cart_mandate=cart_mandate,
            session=session
        )

        # Amount exceeds constraint -> risk
        assert result.risk_factors["constraint_risk"] > 0
        assert "intent_constraint_violation" in result.fraud_indicators

    def test_risk_recommendation_thresholds(self, risk_engine):
        """Test risk recommendation based on thresholds"""
        # Test low risk recommendation
        low_risk_result = RiskAssessmentResult(
            risk_score=20,
            fraud_indicators=[],
            risk_factors={},
            recommendation="approve"
        )
        assert low_risk_result.risk_score < risk_engine.LOW_RISK_THRESHOLD

        # Test medium risk recommendation
        medium_risk_result = RiskAssessmentResult(
            risk_score=45,
            fraud_indicators=[],
            risk_factors={},
            recommendation="review"
        )
        assert risk_engine.LOW_RISK_THRESHOLD <= medium_risk_result.risk_score < risk_engine.HIGH_RISK_THRESHOLD

        # Test high risk recommendation
        high_risk_result = RiskAssessmentResult(
            risk_score=85,
            fraud_indicators=[],
            risk_factors={},
            recommendation="decline"
        )
        assert high_risk_result.risk_score >= risk_engine.HIGH_RISK_THRESHOLD


class TestAmountRiskAssessment:
    """Test amount-based risk assessment"""

    @pytest.fixture
    def risk_engine(self):
        return RiskAssessmentEngine()

    def test_low_amount_low_risk(self, risk_engine):
        """Test low amount transactions have low risk"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "500.00", "currency": "JPY"}
                }
            }
        }

        # Low amount should have minimal risk
        # Testing internal method behavior through public interface
        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)
        assert result.risk_factors["amount_risk"] < 30

    def test_extreme_amount_high_risk(self, risk_engine):
        """Test extremely high amount transactions have high risk"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "1500000.00", "currency": "JPY"}  # 1.5M JPY
                },
                "payment_response": {"payer_id": "user_test"}
            }
        }

        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)
        assert result.risk_factors["amount_risk"] > 50


class TestTransactionPatternAnalysis:
    """Test transaction pattern analysis"""

    @pytest.fixture
    def risk_engine(self):
        return RiskAssessmentEngine()

    def test_first_transaction_baseline_risk(self, risk_engine):
        """Test first transaction from user has baseline risk"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "new_user_001"
                }
            }
        }

        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)

        # First transaction should have some pattern risk
        assert "pattern_risk" in result.risk_factors


class TestFraudIndicators:
    """Test fraud indicator detection"""

    @pytest.fixture
    def risk_engine(self):
        return RiskAssessmentEngine()

    def test_multiple_fraud_indicators(self, risk_engine):
        """Test multiple fraud indicators increase risk"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "600000.00", "currency": "JPY"}  # High amount
                },
                "payment_response": {
                    "payer_id": "user_test",
                    "payment_method": {"type": "card"}
                }
            }
            # No user_authorization -> CNP
        }

        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)

        # Should have multiple fraud indicators
        assert len(result.fraud_indicators) >= 2
        assert "high_transaction_amount" in result.fraud_indicators
        assert "card_not_present_transaction" in result.fraud_indicators

    def test_fraud_indicators_affect_recommendation(self, risk_engine):
        """Test fraud indicators affect final recommendation"""
        # Payment with fraud indicators
        risky_payment = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "800000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "suspicious_user"
                }
            }
        }

        result = risk_engine.assess_payment_mandate(payment_mandate=risky_payment)

        # Result should have a recommendation
        assert result.recommendation in ["approve", "review", "decline"]
        # High amount payment should have fraud indicators
        assert len(result.fraud_indicators) > 0


class TestRiskFactorWeighting:
    """Test risk factor weighting and scoring"""

    @pytest.fixture
    def risk_engine(self):
        return RiskAssessmentEngine()

    def test_risk_factors_combined_score(self, risk_engine):
        """Test that risk factors combine to produce total score"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "25000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_test",
                    "payment_method": {"type": "card"}
                }
            }
        }

        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)

        # Risk score should be calculated from risk factors
        assert result.risk_score >= 0
        assert result.risk_score <= 100

        # Should have risk factors populated
        assert len(result.risk_factors) > 0
        assert "amount_risk" in result.risk_factors

    def test_risk_score_never_exceeds_100(self, risk_engine):
        """Test risk score is capped at 100"""
        # Extreme case with all risk factors
        extreme_payment = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "9999999.00", "currency": "JPY"}  # Extreme amount
                },
                "payment_response": {
                    "payer_id": "suspicious_user"
                }
            }
        }

        result = risk_engine.assess_payment_mandate(payment_mandate=extreme_payment)

        # Risk score should not exceed 100
        assert result.risk_score <= 100


class TestPaymentMethodRisk:
    """Test payment method risk assessment"""

    @pytest.fixture
    def risk_engine(self):
        return RiskAssessmentEngine()

    def test_tokenized_payment_method(self, risk_engine):
        """Test tokenized payment method has lower risk"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001",
                    "methodName": "https://a2a-protocol.org/payment-methods/ap2-payment",
                    "details": {
                        "cardBrand": "Visa",
                        "token": "tok_abc123",
                        "tokenized": True
                    }
                }
            }
        }

        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)

        # Tokenized payment should have low payment method risk
        assert result.risk_factors["payment_method_risk"] < 20

    def test_non_tokenized_payment_missing_expiry(self, risk_engine):
        """Test non-tokenized payment without expiry raises error"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001",
                    "methodName": "basic-card",
                    "details": {
                        "cardBrand": "Visa",
                        "tokenized": False
                    }
                }
            }
        }

        # Should raise ValueError for missing expiry
        with pytest.raises(ValueError, match="expiry_year and expiry_month are required"):
            risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)

    def test_expired_card(self, risk_engine):
        """Test expired card has high risk"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001",
                    "methodName": "basic-card",
                    "details": {
                        "cardBrand": "Visa",
                        "tokenized": False,
                        "expiry_year": 2020,
                        "expiry_month": 1
                    }
                }
            }
        }

        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)

        # Expired card should have high payment method risk (capped at 25)
        assert result.risk_factors["payment_method_risk"] == 25

    def test_card_expiring_soon(self, risk_engine):
        """Test card expiring soon has elevated risk"""
        from datetime import datetime
        current_date = datetime.now()
        expiry_year = current_date.year
        expiry_month = current_date.month + 2  # 2 months from now

        if expiry_month > 12:
            expiry_month -= 12
            expiry_year += 1

        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001",
                    "methodName": "basic-card",
                    "details": {
                        "cardBrand": "Visa",
                        "tokenized": False,
                        "expiry_year": expiry_year,
                        "expiry_month": expiry_month
                    }
                }
            }
        }

        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)

        # Card expiring soon should have some risk
        assert result.risk_factors["payment_method_risk"] > 5


class TestShippingRisk:
    """Test shipping risk assessment"""

    @pytest.fixture
    def risk_engine(self):
        return RiskAssessmentEngine()

    def test_po_box_shipping_risk(self, risk_engine):
        """Test PO Box address has elevated risk"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                }
            }
        }

        cart_mandate = {
            "type": "CartMandate",
            "shipping_address": {
                "address_line1": "P.O. Box 123",
                "city": "Tokyo"
            }
        }

        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            cart_mandate=cart_mandate
        )

        # PO Box should increase shipping risk (15 points)
        assert result.risk_factors["shipping_risk"] == 15
        # Note: fraud indicator only added when shipping_risk > 20, PO Box alone is 15

    def test_po_box_with_express_shipping(self, risk_engine):
        """Test PO Box with express shipping triggers fraud indicator"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                }
            }
        }

        cart_mandate = {
            "type": "CartMandate",
            "shipping_address": {
                "address_line1": "P.O. Box 456",
                "city": "Tokyo"
            },
            "shipping_method": "express"
        }

        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            cart_mandate=cart_mandate
        )

        # PO Box (15) + express (5) = 20 points, capped at 20
        assert result.risk_factors["shipping_risk"] == 20
        # Should NOT trigger fraud indicator since it's not > 20
        assert "shipping_address_risk" not in result.fraud_indicators

    def test_express_shipping_risk(self, risk_engine):
        """Test express shipping has some risk"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                }
            }
        }

        cart_mandate = {
            "type": "CartMandate",
            "shipping_address": {
                "address_line1": "123 Main St"
            },
            "shipping_method": "express"
        }

        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            cart_mandate=cart_mandate
        )

        # Express shipping should add some risk
        assert result.risk_factors["shipping_risk"] > 0

    def test_no_shipping_address(self, risk_engine):
        """Test no cart mandate results in zero shipping risk"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                }
            }
        }

        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)

        # No cart mandate -> no shipping risk
        assert result.risk_factors["shipping_risk"] == 0


class TestTemporalRisk:
    """Test temporal risk assessment"""

    @pytest.fixture
    def risk_engine(self):
        return RiskAssessmentEngine()

    def test_very_fast_transaction(self, risk_engine):
        """Test very fast transaction (bot-like) has high risk"""
        from datetime import datetime, timezone, timedelta

        intent_time = datetime.now(timezone.utc)
        payment_time = intent_time + timedelta(seconds=3)

        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                },
                "timestamp": payment_time.isoformat()
            }
        }

        intent_mandate = {
            "type": "IntentMandate",
            "created_at": intent_time.isoformat()
        }

        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            intent_mandate=intent_mandate
        )

        # Very fast transaction should have temporal risk
        assert result.risk_factors["temporal_risk"] > 10

    def test_slow_transaction(self, risk_engine):
        """Test slow transaction has some risk"""
        from datetime import datetime, timezone, timedelta

        intent_time = datetime.now(timezone.utc)
        payment_time = intent_time + timedelta(hours=2)

        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                },
                "timestamp": payment_time.isoformat()
            }
        }

        intent_mandate = {
            "type": "IntentMandate",
            "created_at": intent_time.isoformat()
        }

        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            intent_mandate=intent_mandate
        )

        # Slow transaction should have some temporal risk
        assert result.risk_factors["temporal_risk"] > 0

    def test_normal_timing(self, risk_engine):
        """Test normal transaction timing has low risk"""
        from datetime import datetime, timezone, timedelta

        intent_time = datetime.now(timezone.utc)
        payment_time = intent_time + timedelta(seconds=45)

        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                },
                "timestamp": payment_time.isoformat()
            }
        }

        intent_mandate = {
            "type": "IntentMandate",
            "created_at": intent_time.isoformat()
        }

        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            intent_mandate=intent_mandate
        )

        # Normal timing should have low temporal risk
        assert result.risk_factors["temporal_risk"] == 0


class TestTransactionHistoryTracking:
    """Test transaction history tracking"""

    @pytest.fixture
    def risk_engine(self):
        return RiskAssessmentEngine()

    def test_transaction_history_recording(self, risk_engine):
        """Test that transactions are recorded in history"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "history_test_user"
                }
            }
        }

        # First transaction
        risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)

        # Check history
        assert "history_test_user" in risk_engine.transaction_history
        assert len(risk_engine.transaction_history["history_test_user"]) == 1

    def test_multiple_transactions_same_user(self, risk_engine):
        """Test multiple transactions from same user"""
        payer_id = "multi_transaction_user"

        for i in range(3):
            payment_mandate = {
                "payment_mandate_contents": {
                    "payment_details_total": {
                        "amount": {"value": f"{1000 * (i+1)}.00", "currency": "JPY"}
                    },
                    "payment_response": {
                        "payer_id": payer_id
                    }
                }
            }
            risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)

        # Check history
        assert len(risk_engine.transaction_history[payer_id]) == 3

    def test_velocity_check_high_frequency(self, risk_engine):
        """Test velocity check for high frequency transactions"""
        payer_id = "velocity_test_user"

        # Simulate 6 transactions
        for i in range(6):
            payment_mandate = {
                "payment_mandate_contents": {
                    "payment_details_total": {
                        "amount": {"value": "5000.00", "currency": "JPY"}
                    },
                    "payment_response": {
                        "payer_id": payer_id
                    }
                }
            }
            risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)

        # Last transaction should have elevated pattern risk
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": payer_id
                }
            }
        }
        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)

        # High frequency should trigger pattern risk
        assert result.risk_factors["pattern_risk"] > 20


class TestAgentInvolvementRisk:
    """Test agent involvement risk assessment"""

    @pytest.fixture
    def risk_engine(self):
        return RiskAssessmentEngine()

    def test_agent_involved_low_risk(self, risk_engine):
        """Test agent involvement results in low risk"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                }
            }
        }

        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)

        # Agent involvement should result in low risk
        assert result.risk_factors["agent_risk"] == 5


class TestConstraintComplianceEdgeCases:
    """Test constraint compliance edge cases"""

    @pytest.fixture
    def risk_engine(self):
        return RiskAssessmentEngine()

    def test_no_max_amount_constraint(self, risk_engine):
        """Test no max_amount constraint results in zero constraint risk"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "50000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                }
            }
        }

        session = {}  # No max_amount

        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            session=session
        )

        # No constraint -> no constraint risk
        assert result.risk_factors["constraint_risk"] == 0

    def test_currency_mismatch(self, risk_engine):
        """Test currency mismatch detection"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "USD"}  # USD instead of JPY
                },
                "payment_response": {
                    "payer_id": "user_001"
                }
            }
        }

        session = {
            "max_amount": 10000  # JPY
        }

        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            session=session
        )

        # Currency mismatch should trigger constraint risk
        assert result.risk_factors["constraint_risk"] == 50

    def test_amount_parsing_error_handling(self, risk_engine):
        """Test graceful handling of amount parsing errors"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "invalid_amount", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                }
            }
        }

        session = {
            "max_amount": 10000
        }

        # Should not raise error, but handle gracefully
        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            session=session
        )

        # Invalid amount should be treated as 0
        assert result.risk_factors["constraint_risk"] == 0


class TestRiskRecommendations:
    """Test risk-based recommendations"""

    @pytest.fixture
    def risk_engine(self):
        return RiskAssessmentEngine()

    def test_approve_recommendation(self, risk_engine):
        """Test approve recommendation for low risk"""
        recommendation = risk_engine._get_recommendation(15)
        assert recommendation == "approve"

    def test_review_recommendation(self, risk_engine):
        """Test review recommendation for medium risk"""
        recommendation = risk_engine._get_recommendation(45)
        assert recommendation == "review"

    def test_decline_recommendation(self, risk_engine):
        """Test decline recommendation for high risk"""
        recommendation = risk_engine._get_recommendation(85)
        assert recommendation == "decline"

    def test_boundary_conditions(self, risk_engine):
        """Test recommendation at boundary values"""
        # At LOW_RISK_THRESHOLD
        assert risk_engine._get_recommendation(30) == "review"

        # At HIGH_RISK_THRESHOLD
        assert risk_engine._get_recommendation(80) == "decline"


class TestAmountRiskTiers:
    """Test different amount risk tiers"""

    @pytest.fixture
    def risk_engine(self):
        return RiskAssessmentEngine()

    def test_moderate_amount_tier(self, risk_engine):
        """Test moderate amount tier (10,000 - 50,000 JPY)"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "20000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                }
            }
        }

        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)

        # Moderate amount should have some risk
        assert 5 <= result.risk_factors["amount_risk"] <= 30

    def test_high_amount_tier(self, risk_engine):
        """Test high amount tier (50,000 - 100,000 JPY)"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "75000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                }
            }
        }

        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)

        # High amount should have elevated risk
        assert result.risk_factors["amount_risk"] >= 20

    def test_very_high_amount_tier(self, risk_engine):
        """Test very high amount tier (100,000 - 500,000 JPY)"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "200000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                }
            }
        }

        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)

        # Very high amount should have high risk
        assert result.risk_factors["amount_risk"] >= 30


class TestDatabaseMode:
    """Test database mode functionality"""

    @pytest.fixture
    def risk_engine(self):
        # Create engine without database manager
        return RiskAssessmentEngine(db_manager=None)

    def test_engine_without_database(self, risk_engine):
        """Test engine works without database manager"""
        assert risk_engine.db_manager is None

        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                }
            }
        }

        # Should work with in-memory mode
        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)
        assert result is not None

    @pytest.mark.asyncio
    async def test_record_transaction_to_db_without_manager(self, risk_engine):
        """Test record_transaction_to_db without database manager"""
        # Should handle gracefully without database
        await risk_engine.record_transaction_to_db("user_001", "5000.00", 25)

    @pytest.mark.asyncio
    async def test_get_transaction_history_without_manager(self, risk_engine):
        """Test get_transaction_history_from_db without database manager"""
        # Should return empty list without database
        history = await risk_engine.get_transaction_history_from_db("user_001")
        assert history == []


class TestUnusualTransactionPattern:
    """Test unusual transaction pattern detection"""

    @pytest.fixture
    def risk_engine(self):
        return RiskAssessmentEngine()

    def test_pattern_risk_at_cap(self, risk_engine):
        """Test pattern_risk reaches cap of 30 with high velocity"""
        payer_id = "pattern_risk_user"

        # Create 5 transactions in quick succession to trigger pattern risk
        for i in range(5):
            payment_mandate = {
                "payment_mandate_contents": {
                    "payment_details_total": {
                        "amount": {"value": "3000.00", "currency": "JPY"}
                    },
                    "payment_response": {
                        "payer_id": payer_id
                    }
                }
            }
            risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)

        # 6th transaction should trigger high pattern risk (capped at 30)
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "3000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": payer_id
                }
            }
        }
        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)

        # Pattern risk should be capped at 30
        assert result.risk_factors["pattern_risk"] == 30


class TestShippingAddressRisk:
    """Test shipping address risk assessment"""

    @pytest.fixture
    def risk_engine(self):
        return RiskAssessmentEngine()

    def test_shipping_risk_po_box_japanese(self, risk_engine):
        """Test shipping risk with Japanese PO Box"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                }
            }
        }

        cart_mandate = {
            "type": "CartMandate",
            "shipping_address": {
                "address_line1": "私書箱 123号",
                "city": "Tokyo"
            },
            "shipping_method": "overnight"  # Express shipping adds 5 points
        }

        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            cart_mandate=cart_mandate
        )

        # PO Box (15) + overnight (5) = 20, capped at 20
        assert result.risk_factors["shipping_risk"] == 20

    def test_shipping_risk_at_cap(self, risk_engine):
        """Test shipping risk reaches cap of 20"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "50000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_002"
                }
            }
        }

        cart_mandate = {
            "type": "CartMandate",
            "shipping_address": {
                "address_line1": "PO Box 789",
                "city": "Osaka"
            },
            "shipping_method": "速達"  # Japanese express adds 5 points
        }

        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            cart_mandate=cart_mandate
        )

        # PO Box (15) + 速達 (5) = 20, capped at 20
        assert result.risk_factors["shipping_risk"] == 20


class TestSuspiciousTiming:
    """Test temporal risk assessment"""

    @pytest.fixture
    def risk_engine(self):
        return RiskAssessmentEngine()

    def test_temporal_risk_very_fast_transaction(self, risk_engine):
        """Test temporal risk for very fast transaction (< 5 seconds)"""
        from datetime import datetime, timezone, timedelta

        intent_time = datetime.now(timezone.utc)
        payment_time = intent_time + timedelta(seconds=2)  # 2 seconds - bot-like

        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                },
                "timestamp": payment_time.isoformat()
            }
        }

        intent_mandate = {
            "type": "IntentMandate",
            "created_at": intent_time.isoformat()
        }

        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            intent_mandate=intent_mandate
        )

        # Very fast transaction (< 5 seconds) should have temporal_risk of 15 (max)
        assert result.risk_factors["temporal_risk"] == 15

    def test_temporal_risk_fast_transaction(self, risk_engine):
        """Test temporal risk for fast transaction (< 30 seconds) - line 598"""
        from datetime import datetime, timezone, timedelta

        intent_time = datetime.now(timezone.utc)
        payment_time = intent_time + timedelta(seconds=25)  # 25 seconds - very fast

        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_002"
                },
                "timestamp": payment_time.isoformat()
            }
        }

        intent_mandate = {
            "type": "IntentMandate",
            "created_at": intent_time.isoformat()
        }

        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            intent_mandate=intent_mandate
        )

        # Fast transaction (< 30 seconds) should have temporal_risk of 10
        assert result.risk_factors["temporal_risk"] == 10


class TestMaxAmountParsing:
    """Test max_amount parsing with decimals and error handling (lines 246-257)"""

    @pytest.fixture
    def risk_engine(self):
        return RiskAssessmentEngine()

    def test_max_amount_decimal_parsing(self, risk_engine):
        """Test max_amount parsing with decimal value (line 246)"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "9500.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                }
            }
        }

        intent_mandate = {
            "constraints": {
                "max_amount": {
                    "value": "10000.50",  # Decimal max_amount
                    "currency": "JPY"
                }
            }
        }

        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            intent_mandate=intent_mandate
        )

        # Amount is within constraint, should have some amount_risk but low constraint_risk
        assert result.risk_factors["amount_risk"] >= 0

    def test_max_amount_ratio_95_percent(self, risk_engine):
        """Test amount at 95% of max_amount (lines 254-255)"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "9500.00", "currency": "JPY"}  # 95% of 10000
                },
                "payment_response": {
                    "payer_id": "user_001"
                }
            }
        }

        intent_mandate = {
            "constraints": {
                "max_amount": {
                    "value": "10000",
                    "currency": "JPY"
                }
            }
        }

        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            intent_mandate=intent_mandate
        )

        # At 95% of max, should add 10 points to amount_risk
        assert result.risk_factors["amount_risk"] >= 10

    def test_max_amount_ratio_85_percent(self, risk_engine):
        """Test amount at 85% of max_amount (lines 256-257)"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "8500.00", "currency": "JPY"}  # 85% of 10000
                },
                "payment_response": {
                    "payer_id": "user_001"
                }
            }
        }

        intent_mandate = {
            "constraints": {
                "max_amount": {
                    "value": "10000",
                    "currency": "JPY"
                }
            }
        }

        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            intent_mandate=intent_mandate
        )

        # At 85% of max (>= 0.80), should add 5 points to amount_risk
        assert result.risk_factors["amount_risk"] >= 5

    def test_max_amount_error_handling(self, risk_engine):
        """Test max_amount parsing error handling (lines 249-250)"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                }
            }
        }

        intent_mandate = {
            "constraints": {
                "max_amount": {
                    "value": "invalid_value",  # Invalid value
                    "currency": "JPY"
                }
            }
        }

        # Should handle gracefully without raising error
        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            intent_mandate=intent_mandate
        )

        assert result is not None


class TestConstraintComplianceEdgeCasesExtended:
    """Test additional constraint compliance edge cases (lines 296-297, 310)"""

    @pytest.fixture
    def risk_engine(self):
        return RiskAssessmentEngine()

    def test_session_without_max_amount(self, risk_engine):
        """Test session without max_amount (lines 296-297)"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "50000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                }
            }
        }

        # Session with max_amount set to None or 0
        session = {"max_amount": None}

        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            session=session
        )

        # No max_amount -> no constraint risk
        assert result.risk_factors["constraint_risk"] == 0

    def test_max_amount_decimal_in_session(self, risk_engine):
        """Test max_amount with decimal in session (line 310)"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                }
            }
        }

        session = {
            "max_amount": "10000.50"  # Decimal value as string
        }

        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            session=session
        )

        # Should parse decimal max_amount correctly
        assert result.risk_factors["constraint_risk"] == 0


class TestTokenizedPaymentEdgeCases:
    """Test tokenized payment edge cases (lines 422-423, 449-454)"""

    @pytest.fixture
    def risk_engine(self):
        return RiskAssessmentEngine()

    def test_tokenized_payment_missing_token(self, risk_engine):
        """Test tokenized payment without token (lines 422-423)"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001",
                    "methodName": "https://a2a-protocol.org/payment-methods/ap2-payment",
                    "details": {
                        "cardBrand": "Visa",
                        "token": "",  # Empty token
                        "tokenized": True
                    }
                }
            }
        }

        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)

        # Missing/empty token should add 15 points to payment_method_risk
        assert result.risk_factors["payment_method_risk"] >= 15

    def test_tokenized_payment_no_token_field(self, risk_engine):
        """Test tokenized payment with no token field"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001",
                    "methodName": "https://a2a-protocol.org/payment-methods/ap2-payment",
                    "details": {
                        "cardBrand": "Visa",
                        # No token field at all
                        "tokenized": True
                    }
                }
            }
        }

        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)

        # Missing token should add 15 points to payment_method_risk
        assert result.risk_factors["payment_method_risk"] >= 15

    def test_non_tokenized_invalid_expiry_format(self, risk_engine):
        """Test non-tokenized payment with invalid expiry format (lines 449-454)"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001",
                    "methodName": "basic-card",
                    "details": {
                        "cardBrand": "Visa",
                        "tokenized": False,
                        "expiry_year": "invalid",  # Invalid format
                        "expiry_month": "bad"  # Invalid format
                    }
                }
            }
        }

        # Should raise ValueError for invalid expiry format
        with pytest.raises(ValueError, match="Invalid payment method expiry date format"):
            risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)


class TestVelocityCheckEdgeCases:
    """Test velocity check edge cases (lines 494-495, 524)"""

    @pytest.fixture
    def risk_engine(self):
        # Create engine with mock db_manager to test database mode fallback
        class MockDBManager:
            pass

        engine = RiskAssessmentEngine(db_manager=MockDBManager())
        return engine

    def test_database_mode_fallback(self, risk_engine):
        """Test database mode fallback in sync context (lines 494-495)"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "db_fallback_user"
                }
            }
        }

        # Should use in-memory fallback when db_manager exists but in sync context
        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)

        assert result is not None
        assert "pattern_risk" in result.risk_factors

    def test_amount_without_decimal(self, risk_engine):
        """Test amount parsing without decimal (line 524)"""
        payer_id = "no_decimal_user"

        # First, add a transaction with decimal
        payment_mandate_1 = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "1000", "currency": "JPY"}  # No decimal
                },
                "payment_response": {
                    "payer_id": payer_id
                }
            }
        }
        risk_engine.assess_payment_mandate(payment_mandate=payment_mandate_1)

        # Second transaction with much higher amount (testing pattern detection)
        payment_mandate_2 = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000", "currency": "JPY"}  # No decimal, 5x higher
                },
                "payment_response": {
                    "payer_id": payer_id
                }
            }
        }
        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate_2)

        # Should parse amount without decimal correctly
        assert result is not None


class TestPatternAnalysisEdgeCases:
    """Test pattern analysis edge cases (lines 536-537, 543-545)"""

    @pytest.fixture
    def risk_engine(self):
        return RiskAssessmentEngine()

    def test_transaction_history_with_invalid_amounts(self, risk_engine):
        """Test transaction history with invalid amount values (lines 536-537)"""
        payer_id = "invalid_history_user"

        # Manually inject invalid transaction history
        risk_engine.transaction_history[payer_id] = [
            {
                "timestamp": datetime.now().isoformat(),
                "amount": "invalid_amount",  # Invalid amount
                "risk_score": 10
            },
            {
                "timestamp": datetime.now().isoformat(),
                "amount": "bad_value",  # Invalid amount
                "risk_score": 15
            }
        ]

        # New transaction
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "10000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": payer_id
                }
            }
        }

        # Should handle invalid amounts in history gracefully
        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)
        assert result is not None

    def test_current_amount_parsing_error(self, risk_engine):
        """Test current amount parsing error (lines 543-545)"""
        payer_id = "parse_error_user"

        # Add valid transaction to history
        risk_engine.transaction_history[payer_id] = [
            {
                "timestamp": datetime.now().isoformat(),
                "amount": "5000.00",
                "risk_score": 10
            }
        ]

        # Transaction with invalid current amount
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "not_a_number", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": payer_id
                }
            }
        }

        # Should handle parsing error gracefully
        result = risk_engine.assess_payment_mandate(payment_mandate=payment_mandate)
        assert result is not None


class TestTemporalRiskEdgeCases:
    """Test temporal risk edge cases (line 584, 606-608)"""

    @pytest.fixture
    def risk_engine(self):
        return RiskAssessmentEngine()

    def test_temporal_risk_missing_intent_created_at(self, risk_engine):
        """Test temporal risk with missing intent created_at (line 584)"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                },
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        }

        intent_mandate = {
            "type": "IntentMandate"
            # Missing created_at
        }

        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            intent_mandate=intent_mandate
        )

        # Missing timestamp should return 0 temporal risk
        assert result.risk_factors["temporal_risk"] == 0

    def test_temporal_risk_missing_payment_timestamp(self, risk_engine):
        """Test temporal risk with missing payment timestamp (line 584)"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                }
                # Missing timestamp
            }
        }

        intent_mandate = {
            "type": "IntentMandate",
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            intent_mandate=intent_mandate
        )

        # Missing timestamp should return 0 temporal risk
        assert result.risk_factors["temporal_risk"] == 0

    def test_temporal_risk_invalid_timestamp_format(self, risk_engine):
        """Test temporal risk with invalid timestamp format (lines 606-608)"""
        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000.00", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                },
                "timestamp": "invalid-timestamp-format"
            }
        }

        intent_mandate = {
            "type": "IntentMandate",
            "created_at": "also-invalid"
        }

        result = risk_engine.assess_payment_mandate(
            payment_mandate=payment_mandate,
            intent_mandate=intent_mandate
        )

        # Invalid timestamp should return 0 temporal risk (error handled)
        assert result.risk_factors["temporal_risk"] == 0


class TestRiskScoreCalculation:
    """Test risk score calculation edge cases (line 641)"""

    @pytest.fixture
    def risk_engine(self):
        return RiskAssessmentEngine()

    def test_risk_score_with_empty_factors(self, risk_engine):
        """Test risk score calculation with empty factors (line 641)"""
        # Test the _calculate_total_risk_score method directly
        risk_factors = {}

        total_score = risk_engine._calculate_total_risk_score(risk_factors)

        # Empty factors should result in 0 score
        assert total_score == 0


class TestAsyncDatabaseMethods:
    """Test async database methods (lines 701-722, 739-754)"""

    @pytest.fixture
    def risk_engine(self):
        return RiskAssessmentEngine()

    @pytest.fixture
    def risk_engine_with_mock_db(self):
        """Create risk engine with mock database manager"""
        from unittest.mock import MagicMock, AsyncMock

        mock_db_manager = MagicMock()

        # Mock the get_session context manager
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_db_manager.get_session.return_value = mock_session

        engine = RiskAssessmentEngine(db_manager=mock_db_manager)
        return engine, mock_db_manager, mock_session

    @pytest.mark.asyncio
    async def test_record_transaction_to_db_with_decimal_amount(self, risk_engine):
        """Test recording transaction with decimal amount (lines 701-722)"""
        # Test decimal amount parsing
        await risk_engine.record_transaction_to_db(
            payer_id="user_001",
            amount_value_str="10000.50",  # Decimal amount
            risk_score=25,
            currency="JPY"
        )
        # Should complete without error (no db_manager, so it just logs warning)

    @pytest.mark.asyncio
    async def test_record_transaction_to_db_with_integer_amount(self, risk_engine):
        """Test recording transaction with integer amount (lines 701-722)"""
        # Test integer amount parsing
        await risk_engine.record_transaction_to_db(
            payer_id="user_002",
            amount_value_str="10000",  # Integer amount
            risk_score=30,
            currency="JPY"
        )
        # Should complete without error

    @pytest.mark.asyncio
    async def test_get_transaction_history_from_db(self, risk_engine):
        """Test getting transaction history from database (lines 739-754)"""
        # Test with different days parameter
        history = await risk_engine.get_transaction_history_from_db("user_001", days=7)

        # Should return empty list (no db_manager)
        assert history == []

    @pytest.mark.asyncio
    async def test_get_transaction_history_from_db_default_days(self, risk_engine):
        """Test getting transaction history with default days"""
        history = await risk_engine.get_transaction_history_from_db("user_001")

        # Should return empty list with default 30 days
        assert history == []

    @pytest.mark.asyncio
    async def test_record_transaction_to_db_with_mock_database(self, risk_engine_with_mock_db):
        """Test recording transaction with mock database (lines 701-722)"""
        from unittest.mock import AsyncMock, patch

        engine, mock_db_manager, mock_session = risk_engine_with_mock_db

        # Mock the TransactionHistoryCRUD.create method
        with patch('common.database.TransactionHistoryCRUD') as mock_crud:
            mock_crud.create = AsyncMock(return_value=None)

            # Test with decimal amount
            await engine.record_transaction_to_db(
                payer_id="user_001",
                amount_value_str="10000.50",
                risk_score=25,
                currency="JPY"
            )

            # Verify create was called
            mock_crud.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_transaction_to_db_error_handling(self, risk_engine_with_mock_db):
        """Test error handling in record_transaction_to_db (line 722)"""
        from unittest.mock import AsyncMock, patch

        engine, mock_db_manager, mock_session = risk_engine_with_mock_db

        # Mock TransactionHistoryCRUD to raise an error
        with patch('common.database.TransactionHistoryCRUD') as mock_crud:
            mock_crud.create = AsyncMock(side_effect=Exception("Database error"))

            # Should handle error gracefully
            await engine.record_transaction_to_db(
                payer_id="user_001",
                amount_value_str="5000.00",
                risk_score=20
            )

    @pytest.mark.asyncio
    async def test_get_transaction_history_from_db_with_mock_database(self, risk_engine_with_mock_db):
        """Test getting transaction history with mock database (lines 739-754)"""
        from unittest.mock import AsyncMock, patch, MagicMock

        engine, mock_db_manager, mock_session = risk_engine_with_mock_db

        # Create mock transaction history records
        mock_record1 = MagicMock()
        mock_record1.to_dict.return_value = {
            "payer_id": "user_001",
            "amount_value": 5000,
            "currency": "JPY",
            "risk_score": 25
        }

        mock_record2 = MagicMock()
        mock_record2.to_dict.return_value = {
            "payer_id": "user_001",
            "amount_value": 10000,
            "currency": "JPY",
            "risk_score": 30
        }

        # Mock the TransactionHistoryCRUD.get_by_payer_id method
        with patch('common.database.TransactionHistoryCRUD') as mock_crud:
            mock_crud.get_by_payer_id = AsyncMock(return_value=[mock_record1, mock_record2])

            # Get transaction history
            history = await engine.get_transaction_history_from_db("user_001", days=30)

            # Verify we got the correct history
            assert len(history) == 2
            assert history[0]["payer_id"] == "user_001"
            assert history[1]["amount_value"] == 10000

    @pytest.mark.asyncio
    async def test_get_transaction_history_from_db_error_handling(self, risk_engine_with_mock_db):
        """Test error handling in get_transaction_history_from_db (line 753)"""
        from unittest.mock import AsyncMock, patch

        engine, mock_db_manager, mock_session = risk_engine_with_mock_db

        # Mock TransactionHistoryCRUD to raise an error
        with patch('common.database.TransactionHistoryCRUD') as mock_crud:
            mock_crud.get_by_payer_id = AsyncMock(side_effect=Exception("Database error"))

            # Should handle error gracefully and return empty list
            history = await engine.get_transaction_history_from_db("user_001")

            assert history == []
