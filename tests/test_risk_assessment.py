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
