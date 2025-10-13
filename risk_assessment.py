"""
AP2 Protocol - リスク評価エンジン
Payment Mandateのリスクスコアと不正指標を評価
"""

from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from decimal import Decimal

from ap2_types import (
    PaymentMandate, CartMandate, IntentMandate,
    PaymentMethod, Amount,
    AP2ErrorCode, MandateError
)


@dataclass
class RiskAssessmentResult:
    """リスク評価結果"""
    risk_score: int  # 0-100 (0=低リスク, 100=高リスク)
    fraud_indicators: List[str]
    risk_factors: Dict[str, int]  # 各リスク要因のスコア
    recommendation: str  # "approve", "review", "decline"


class RiskAssessmentEngine:
    """
    リスク評価エンジン

    実際の決済システムで使われる要素を考慮してリスクスコアを算出：
    - 取引金額
    - Intent制約との整合性
    - Agent関与
    - 取引タイプ（human_present vs not_present）
    - 支払い方法の信頼性
    - 取引パターン
    """

    # リスクスコアの閾値
    LOW_RISK_THRESHOLD = 30
    MEDIUM_RISK_THRESHOLD = 60
    HIGH_RISK_THRESHOLD = 80

    # 金額リスクの閾値（USD基準）
    # より現実的な閾値に設定
    MODERATE_VALUE_THRESHOLD = 100.0    # 100ドル以上
    HIGH_VALUE_THRESHOLD = 500.0        # 500ドル以上
    VERY_HIGH_VALUE_THRESHOLD = 1000.0  # 1,000ドル以上（非常に高額）
    EXTREME_VALUE_THRESHOLD = 5000.0    # 5,000ドル以上（極めて高額）
    SUSPICIOUS_VALUE_THRESHOLD = 10000.0 # 10,000ドル以上（疑わしい）

    def __init__(self):
        """リスク評価エンジンを初期化"""
        # 簡易的な取引履歴（実際はデータベースに保存）
        self.transaction_history: Dict[str, List[Dict]] = {}

    def assess_payment_mandate(
        self,
        payment_mandate: PaymentMandate,
        cart_mandate: CartMandate,
        intent_mandate: IntentMandate
    ) -> RiskAssessmentResult:
        """
        Payment Mandateのリスクを評価

        Args:
            payment_mandate: 評価対象のPayment Mandate
            cart_mandate: 関連するCart Mandate
            intent_mandate: 関連するIntent Mandate

        Returns:
            RiskAssessmentResult: リスク評価結果

        Raises:
            MandateError: Intent Mandateが期限切れの場合
        """
        # Intent Mandateの有効期限を検証
        expires_at = datetime.fromisoformat(intent_mandate.expires_at.replace('Z', '+00:00'))
        now = datetime.now(expires_at.tzinfo)

        if now > expires_at:
            raise MandateError(
                error_code=AP2ErrorCode.EXPIRED_INTENT,
                message=f"Intent Mandateは期限切れです: {intent_mandate.id}",
                details={
                    "intent_mandate_id": intent_mandate.id,
                    "expired_at": intent_mandate.expires_at,
                    "current_time": now.isoformat()
                }
            )

        risk_factors = {}
        fraud_indicators = []

        # 1. 取引金額リスク
        amount_risk = self._assess_amount_risk(
            payment_mandate.amount,
            intent_mandate
        )
        risk_factors["amount_risk"] = amount_risk
        if amount_risk > 30:
            fraud_indicators.append(f"high_transaction_amount")

        # 2. Intent制約違反チェック
        constraint_risk = self._assess_constraint_compliance(
            payment_mandate,
            cart_mandate,
            intent_mandate
        )
        risk_factors["constraint_risk"] = constraint_risk
        if constraint_risk > 0:
            fraud_indicators.append("intent_constraint_violation")

        # 3. Agent関与によるリスク
        agent_risk = self._assess_agent_involvement(
            payment_mandate.agent_involved
        )
        risk_factors["agent_risk"] = agent_risk

        # 4. 取引タイプリスク（CNP vs CP）
        transaction_type_risk = self._assess_transaction_type(
            payment_mandate.transaction_type
        )
        risk_factors["transaction_type_risk"] = transaction_type_risk
        if payment_mandate.transaction_type == "human_not_present":
            fraud_indicators.append("card_not_present_transaction")

        # 5. 支払い方法リスク
        payment_method_risk = self._assess_payment_method(
            payment_mandate.payment_method
        )
        risk_factors["payment_method_risk"] = payment_method_risk
        if payment_method_risk > 20:
            fraud_indicators.append("payment_method_risk")

        # 6. 取引パターンリスク
        pattern_risk = self._assess_transaction_pattern(
            payment_mandate.payer_id,
            payment_mandate.amount
        )
        risk_factors["pattern_risk"] = pattern_risk
        if pattern_risk > 30:
            fraud_indicators.append("unusual_transaction_pattern")

        # 7. 配送先リスク（Cart Mandateから）
        shipping_risk = self._assess_shipping_risk(cart_mandate)
        risk_factors["shipping_risk"] = shipping_risk
        if shipping_risk > 20:
            fraud_indicators.append("shipping_address_risk")

        # 8. 時間的リスク（Intent作成からの経過時間）
        temporal_risk = self._assess_temporal_risk(
            intent_mandate.created_at,
            payment_mandate.created_at
        )
        risk_factors["temporal_risk"] = temporal_risk
        if temporal_risk > 20:
            fraud_indicators.append("suspicious_timing")

        # 総合リスクスコアを計算（加重平均）
        total_risk_score = self._calculate_total_risk_score(risk_factors)

        # 推奨アクションを決定
        recommendation = self._get_recommendation(total_risk_score)

        # 取引履歴に記録
        self._record_transaction(
            payment_mandate.payer_id,
            payment_mandate.amount,
            total_risk_score
        )

        return RiskAssessmentResult(
            risk_score=total_risk_score,
            fraud_indicators=fraud_indicators,
            risk_factors=risk_factors,
            recommendation=recommendation
        )

    def _assess_amount_risk(
        self,
        amount: Amount,
        intent_mandate: IntentMandate
    ) -> int:
        """
        取引金額のリスクを評価

        より現実的なリスク評価：
        - 1,000ドル以上: 高リスク
        - 5,000ドル以上: 非常に高リスク
        - 10,000ドル以上: 極めて高リスク（ほぼ拒否）

        Returns:
            0-80のリスクスコア（高額取引用に上限を引き上げ）
        """
        # Decimalで精度を保証
        amount_value = amount.to_decimal()
        max_amount_value = intent_mandate.constraints.max_amount.to_decimal()

        risk = 0

        # 絶対額によるリスク（段階的に評価）
        threshold_suspicious = Decimal(str(self.SUSPICIOUS_VALUE_THRESHOLD))
        threshold_extreme = Decimal(str(self.EXTREME_VALUE_THRESHOLD))
        threshold_very_high = Decimal(str(self.VERY_HIGH_VALUE_THRESHOLD))
        threshold_high = Decimal(str(self.HIGH_VALUE_THRESHOLD))
        threshold_moderate = Decimal(str(self.MODERATE_VALUE_THRESHOLD))
        threshold_fifty = Decimal("50.0")

        if amount_value >= threshold_suspicious:  # 10,000ドル以上
            risk += 60  # 極めて高リスク
        elif amount_value >= threshold_extreme:  # 5,000ドル以上
            risk += 45  # 非常に高リスク
        elif amount_value >= threshold_very_high:  # 1,000ドル以上
            risk += 35  # 高リスク
        elif amount_value >= threshold_high:  # 500ドル以上
            risk += 25  # 中リスク
        elif amount_value >= threshold_moderate:  # 100ドル以上
            risk += 10  # 低〜中リスク
        elif amount_value >= threshold_fifty:  # 50ドル以上
            risk += 5   # 低リスク

        # Intent制約上限との比率
        ratio = amount_value / max_amount_value if max_amount_value > Decimal("0") else Decimal("0")
        if ratio >= Decimal("0.95"):  # 上限の95%以上
            risk += 10
        elif ratio >= Decimal("0.80"):  # 上限の80%以上
            risk += 5

        return min(risk, 80)  # 上限を40から80に引き上げ

    def _assess_constraint_compliance(
        self,
        payment_mandate: PaymentMandate,
        cart_mandate: CartMandate,
        intent_mandate: IntentMandate
    ) -> int:
        """
        Intent制約への準拠を評価

        Returns:
            0または50（違反があれば高リスク）
        """
        # 金額オーバー（Decimalで精度を保証）
        if payment_mandate.amount.to_decimal() > intent_mandate.constraints.max_amount.to_decimal():
            return 50

        # 通貨不一致
        if payment_mandate.amount.currency != intent_mandate.constraints.max_amount.currency:
            return 50

        # ブランド制約違反（商品ブランドがIntent制約外）
        if intent_mandate.constraints.brands:
            for item in cart_mandate.items:
                # 実際の商品ブランドチェックはここで行う
                # 簡易版なので省略
                pass

        return 0

    def _assess_agent_involvement(self, agent_involved: bool) -> int:
        """
        Agent関与によるリスクを評価

        Agent経由の取引は自動化されているため、
        パターンと動作が予測可能で低リスク

        Returns:
            0-5のリスクスコア
        """
        # Agentが関与している場合、プロトコルに従っているので低リスク
        # ただし、Agent自体が侵害されている可能性もあるので若干のリスク
        return 5 if agent_involved else 0

    def _assess_transaction_type(self, transaction_type: str) -> int:
        """
        取引タイプのリスクを評価

        CNP（Card Not Present）取引はCP（Card Present）より高リスク

        Returns:
            0-15のリスクスコア
        """
        if transaction_type == "human_not_present":
            # カード番号盗用のリスクが高い
            return 15
        else:
            # 物理的なカード提示が必要なので低リスク
            return 5

    def _assess_payment_method(self, payment_method: PaymentMethod) -> int:
        """
        支払い方法のリスクを評価

        Returns:
            0-25のリスクスコア
        """
        risk = 0

        if payment_method.type == 'card':
            # カードの有効期限をチェック
            current_year = datetime.now().year
            current_month = datetime.now().month

            expiry_year = payment_method.expiry_year
            expiry_month = payment_method.expiry_month

            # 有効期限が近い（3ヶ月以内）
            months_until_expiry = (expiry_year - current_year) * 12 + (expiry_month - current_month)
            if months_until_expiry <= 3:
                risk += 10

            # 有効期限が切れている
            if months_until_expiry < 0:
                risk += 50  # 非常に高リスク

            # トークン化されていない場合（理論上はあり得ないが）
            if not payment_method.token or payment_method.token == '':
                risk += 15

        return min(risk, 25)

    def _assess_transaction_pattern(
        self,
        payer_id: str,
        amount: Amount
    ) -> int:
        """
        取引パターンのリスクを評価

        Returns:
            0-30のリスクスコア
        """
        risk = 0

        # 過去の取引履歴を確認
        history = self.transaction_history.get(payer_id, [])

        if not history:
            # 初回取引（新規ユーザー）
            risk += 15
        else:
            # 過去24時間の取引数をチェック
            recent_transactions = [
                t for t in history
                if (datetime.now() - datetime.fromisoformat(t['timestamp'])).total_seconds() < 86400
            ]

            if len(recent_transactions) >= 5:
                # 24時間以内に5回以上の取引（カードテスティングの可能性）
                risk += 30
            elif len(recent_transactions) >= 3:
                risk += 15

            # 金額の急激な変化（Decimalで精度を保証）
            if history:
                # 過去5件の取引金額の平均をDecimalで計算
                recent_amounts = [Decimal(t['amount']) for t in history[-5:]]
                avg_amount = sum(recent_amounts) / Decimal(min(len(history), 5))
                current_amount = amount.to_decimal()

                if current_amount > avg_amount * Decimal("3"):
                    # 平均の3倍以上（異常パターン）
                    risk += 15

        return min(risk, 30)

    def _assess_shipping_risk(self, cart_mandate: CartMandate) -> int:
        """
        配送先のリスクを評価

        Returns:
            0-20のリスクスコア
        """
        risk = 0

        shipping = cart_mandate.shipping
        address = shipping.address

        # 私書箱や郵便局留め（簡易チェック）
        if 'P.O.' in address.street or 'PO Box' in address.street:
            risk += 15

        # 配送方法が速達（急ぎの配送は不正の兆候の場合がある）
        if shipping.method == 'express' or shipping.method == 'overnight':
            risk += 5

        return min(risk, 20)

    def _assess_temporal_risk(
        self,
        intent_created_at: str,
        payment_created_at: str
    ) -> int:
        """
        時間的リスクを評価（Intent作成から決済までの時間）

        Returns:
            0-15のリスクスコア
        """
        try:
            intent_time = datetime.fromisoformat(intent_created_at.replace('Z', '+00:00'))
            payment_time = datetime.fromisoformat(payment_created_at.replace('Z', '+00:00'))

            time_diff = (payment_time - intent_time).total_seconds()

            # 5秒未満（あまりにも速い、ボットの可能性）
            if time_diff < 5:
                return 15

            # 30秒未満（非常に速い）
            elif time_diff < 30:
                return 10

            # 1時間以上（放置されていた可能性）
            elif time_diff > 3600:
                return 5

            return 0

        except:
            # パースエラーの場合は低リスク
            return 0

    def _calculate_total_risk_score(self, risk_factors: Dict[str, int]) -> int:
        """
        総合リスクスコアを計算（加重平均）

        Returns:
            0-100のリスクスコア
        """
        # 各要因の重み
        # 金額リスクの重みを引き上げて、高額取引をより厳格に評価
        weights = {
            "amount_risk": 2.5,          # 金額リスクの重みを大幅に引き上げ（1.5 → 2.5）
            "constraint_risk": 2.0,
            "agent_risk": 0.5,
            "transaction_type_risk": 1.0,
            "payment_method_risk": 1.2,
            "pattern_risk": 1.3,
            "shipping_risk": 0.8,
            "temporal_risk": 0.7
        }

        weighted_sum = 0
        total_weight = 0

        for factor, score in risk_factors.items():
            weight = weights.get(factor, 1.0)
            weighted_sum += score * weight
            total_weight += weight

        # 加重平均を100点満点に正規化
        if total_weight > 0:
            normalized_score = int((weighted_sum / total_weight))
        else:
            normalized_score = 0

        return min(max(normalized_score, 0), 100)

    def _get_recommendation(self, risk_score: int) -> str:
        """
        リスクスコアに基づいて推奨アクションを返す

        Args:
            risk_score: 0-100のリスクスコア

        Returns:
            "approve", "review", "decline"
        """
        if risk_score < self.LOW_RISK_THRESHOLD:
            return "approve"
        elif risk_score < self.HIGH_RISK_THRESHOLD:
            return "review"
        else:
            return "decline"

    def _record_transaction(
        self,
        payer_id: str,
        amount: Amount,
        risk_score: int
    ):
        """取引を履歴に記録"""
        if payer_id not in self.transaction_history:
            self.transaction_history[payer_id] = []

        self.transaction_history[payer_id].append({
            "timestamp": datetime.now().isoformat(),
            "amount": amount.value,
            "currency": amount.currency,
            "risk_score": risk_score
        })

        # 古い履歴を削除（30日以上前）
        cutoff = datetime.now() - timedelta(days=30)
        self.transaction_history[payer_id] = [
            t for t in self.transaction_history[payer_id]
            if datetime.fromisoformat(t['timestamp']) > cutoff
        ]


def demo_risk_assessment():
    """リスク評価のデモ"""
    from ap2_types import (
        IntentMandate, IntentConstraints, CartMandate, CartItem,
        ShippingInfo, Address, CardPaymentMethod
    )
    from datetime import datetime, timedelta

    print("=== Risk Assessment Engine Demo ===\n")

    # リスク評価エンジンを初期化
    engine = RiskAssessmentEngine()

    # Intent Mandateを作成
    intent_mandate = IntentMandate(
        id="intent_001",
        type="IntentMandate",
        version="1.0",
        user_id="user_001",
        user_public_key="dummy_key",
        intent="ランニングシューズを購入",
        constraints=IntentConstraints(
            valid_until=(datetime.now() + timedelta(hours=24)).isoformat(),
            max_amount=Amount(value="200.00", currency="USD"),
            brands=["Nike", "Adidas"]
        ),
        created_at=datetime.now().isoformat(),
        expires_at=(datetime.now() + timedelta(hours=24)).isoformat()
    )

    # Cart Mandateを作成
    cart_mandate = CartMandate(
        id="cart_001",
        type="CartMandate",
        version="1.0",
        intent_mandate_id="intent_001",
        merchant_id="merchant_001",
        merchant_name="Running Shoes Store",
        items=[
            CartItem(
                id="prod_001",
                name="Nike Air Zoom Pegasus 40",
                description="Running shoes",
                quantity=1,
                unit_price=Amount(value="150.00", currency="USD"),
                total_price=Amount(value="150.00", currency="USD")
            )
        ],
        subtotal=Amount(value="150.00", currency="USD"),
        tax=Amount(value="12.00", currency="USD"),
        shipping=ShippingInfo(
            address=Address(
                street="123 Main St",
                city="San Francisco",
                state="CA",
                postal_code="94105",
                country="US"
            ),
            method="standard",
            cost=Amount(value="10.00", currency="USD"),
            estimated_delivery="2025-10-20"
        ),
        total=Amount(value="172.00", currency="USD"),
        created_at=datetime.now().isoformat()
    )

    # Payment Mandateを作成（有効期限15分）
    now = datetime.now()
    expires_at = now + timedelta(minutes=15)

    payment_mandate = PaymentMandate(
        id="payment_001",
        type="PaymentMandate",
        version="1.0",
        cart_mandate_id="cart_001",
        intent_mandate_id="intent_001",
        payment_method=CardPaymentMethod(
            type='card',
            token='tok_xxxxx',
            last4='4242',
            brand='visa',
            expiry_month=12,
            expiry_year=2026,
            holder_name='Test User'
        ),
        amount=Amount(value="172.00", currency="USD"),
        transaction_type="human_not_present",
        agent_involved=True,
        payer_id="user_001",
        payee_id="merchant_001",
        created_at=now.isoformat(),
        expires_at=expires_at.isoformat()
    )

    # リスク評価を実行
    result = engine.assess_payment_mandate(
        payment_mandate,
        cart_mandate,
        intent_mandate
    )

    print(f"リスクスコア: {result.risk_score}/100")
    print(f"推奨アクション: {result.recommendation}")
    print(f"\n不正指標:")
    for indicator in result.fraud_indicators:
        print(f"  - {indicator}")

    print(f"\nリスク要因の詳細:")
    for factor, score in result.risk_factors.items():
        print(f"  {factor}: {score}")


if __name__ == "__main__":
    demo_risk_assessment()