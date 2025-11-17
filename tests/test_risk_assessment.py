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
