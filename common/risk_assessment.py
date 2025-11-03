"""
v2/common/risk_assessment.py

Payment Mandateのリスク評価エンジン
既存のrisk_assessment.pyをv2の構造に適応
"""

from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


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
    - 配送先リスク
    - 時間的リスク
    """

    # リスクスコアの閾値
    LOW_RISK_THRESHOLD = 30
    MEDIUM_RISK_THRESHOLD = 60
    HIGH_RISK_THRESHOLD = 80

    # 金額リスクの閾値（JPY基準、centで管理）
    MODERATE_VALUE_THRESHOLD = 10000 * 100  # 10,000円 (in cents)
    HIGH_VALUE_THRESHOLD = 50000 * 100      # 50,000円
    VERY_HIGH_VALUE_THRESHOLD = 100000 * 100  # 100,000円
    EXTREME_VALUE_THRESHOLD = 500000 * 100    # 500,000円
    SUSPICIOUS_VALUE_THRESHOLD = 1000000 * 100  # 1,000,000円

    def __init__(self, db_manager=None):
        """
        リスク評価エンジンを初期化

        Args:
            db_manager: データベースマネージャー（オプション）
                        指定されない場合はインメモリで動作（後方互換性のため）
        """
        self.db_manager = db_manager
        # 後方互換性のため、インメモリストアも残す（db_managerが指定されない場合）
        self.transaction_history: Dict[str, List[Dict]] = {}
        logger.info(f"[RiskAssessmentEngine] Initialized (database_mode={'enabled' if db_manager else 'disabled'})")

    def assess_payment_mandate(
        self,
        payment_mandate: Dict,
        cart_mandate: Optional[Dict] = None,
        intent_mandate: Optional[Dict] = None
    ) -> RiskAssessmentResult:
        """
        Payment Mandateのリスクを評価

        Args:
            payment_mandate: 評価対象のPayment Mandate
            cart_mandate: 関連するCart Mandate（オプション）
            intent_mandate: 関連するIntent Mandate（オプション）

        Returns:
            RiskAssessmentResult: リスク評価結果
        """
        risk_factors = {}
        fraud_indicators = []

        # 1. 取引金額リスク
        amount_risk = self._assess_amount_risk(payment_mandate, intent_mandate)
        risk_factors["amount_risk"] = amount_risk
        if amount_risk > 30:
            fraud_indicators.append("high_transaction_amount")

        # 2. Intent制約違反チェック（intent_mandateがある場合のみ）
        if intent_mandate:
            constraint_risk = self._assess_constraint_compliance(
                payment_mandate,
                cart_mandate,
                intent_mandate
            )
            risk_factors["constraint_risk"] = constraint_risk
            if constraint_risk > 0:
                fraud_indicators.append("intent_constraint_violation")
        else:
            risk_factors["constraint_risk"] = 0

        # 3. Agent関与によるリスク
        # AP2完全準拠：AP2プロトコル使用時は常にAgent関与
        # （PaymentMandateが存在すること自体がAgent関与の証明）
        agent_risk = self._assess_agent_involvement(True)
        risk_factors["agent_risk"] = agent_risk

        # 4. 取引タイプリスク（CNP vs CP）
        # AP2完全準拠：user_authorizationの有無から判定
        # - user_authorization あり（WebAuthn署名）→ human_present
        # - user_authorization なし → human_not_present
        user_authorization = payment_mandate.get("user_authorization")
        transaction_type = "human_present" if user_authorization else "human_not_present"
        transaction_type_risk = self._assess_transaction_type(transaction_type)
        risk_factors["transaction_type_risk"] = transaction_type_risk
        if transaction_type == "human_not_present":
            fraud_indicators.append("card_not_present_transaction")

        # 5. 支払い方法リスク
        # AP2完全準拠: PaymentResponseから支払い方法を取得
        payment_mandate_contents = payment_mandate.get("payment_mandate_contents", {})
        payment_response = payment_mandate_contents.get("payment_response", {})
        payment_method_risk = self._assess_payment_method(payment_response)
        risk_factors["payment_method_risk"] = payment_method_risk
        if payment_method_risk > 20:
            fraud_indicators.append("payment_method_risk")

        # 6. 取引パターンリスク
        # AP2完全準拠: PaymentResponseから支払者情報を取得
        payment_mandate_contents = payment_mandate.get("payment_mandate_contents", {})
        payment_response = payment_mandate_contents.get("payment_response", {})
        payer_id = payment_response.get("payer_id", "unknown")

        # 金額を取得（既に_assess_amount_riskで計算済みだが、再取得）
        payment_details_total = payment_mandate_contents.get("payment_details_total", {})
        amount_value = str(payment_details_total.get("amount", {}).get("value", "0"))

        pattern_risk = self._assess_transaction_pattern(payer_id, amount_value)
        risk_factors["pattern_risk"] = pattern_risk
        if pattern_risk > 30:
            fraud_indicators.append("unusual_transaction_pattern")

        # 7. 配送先リスク（Cart Mandateがある場合のみ）
        if cart_mandate:
            shipping_risk = self._assess_shipping_risk(cart_mandate)
            risk_factors["shipping_risk"] = shipping_risk
            if shipping_risk > 20:
                fraud_indicators.append("shipping_address_risk")
        else:
            risk_factors["shipping_risk"] = 0

        # 8. 時間的リスク（Intent Mandateがある場合のみ）
        if intent_mandate:
            # AP2完全準拠: PaymentMandateContentsからタイムスタンプを取得
            payment_timestamp = payment_mandate_contents.get("timestamp")
            temporal_risk = self._assess_temporal_risk(
                intent_mandate.get("created_at"),
                payment_timestamp
            )
            risk_factors["temporal_risk"] = temporal_risk
            if temporal_risk > 20:
                fraud_indicators.append("suspicious_timing")
        else:
            risk_factors["temporal_risk"] = 0

        # 総合リスクスコアを計算（加重平均）
        total_risk_score = self._calculate_total_risk_score(risk_factors)

        # 推奨アクションを決定
        recommendation = self._get_recommendation(total_risk_score)

        # 取引履歴に記録
        self._record_transaction(payer_id, amount_value, total_risk_score)

        logger.info(
            f"[RiskAssessmentEngine] Assessment completed: "
            f"risk_score={total_risk_score}, recommendation={recommendation}, "
            f"fraud_indicators={fraud_indicators}"
        )

        return RiskAssessmentResult(
            risk_score=total_risk_score,
            fraud_indicators=fraud_indicators,
            risk_factors=risk_factors,
            recommendation=recommendation
        )

    def _assess_amount_risk(
        self,
        payment_mandate: Dict,
        intent_mandate: Optional[Dict]
    ) -> int:
        """
        取引金額のリスクを評価（AP2完全準拠）

        Returns:
            0-80のリスクスコア
        """
        # AP2完全準拠: PaymentMandateの正しい構造からデータを取得
        payment_mandate_contents = payment_mandate.get("payment_mandate_contents", {})
        payment_details_total = payment_mandate_contents.get("payment_details_total", {})
        amount = payment_details_total.get("amount", {})
        amount_value_str = str(amount.get("value", "0"))

        # 値を整数に変換（cent単位）
        # AP2完全準拠: PaymentItemのvalueはfloatまたはint（円単位）
        try:
            if "." in amount_value_str:
                amount_value = int(float(amount_value_str) * 100)
            else:
                amount_value = int(amount_value_str) * 100  # 円→セント変換
        except (ValueError, TypeError):
            logger.warning(f"[RiskAssessmentEngine] Invalid amount value: {amount_value_str}")
            amount_value = 0

        risk = 0

        # 絶対額によるリスク（段階的に評価）
        if amount_value >= self.SUSPICIOUS_VALUE_THRESHOLD:  # 1,000,000円以上
            risk += 60
        elif amount_value >= self.EXTREME_VALUE_THRESHOLD:  # 500,000円以上
            risk += 45
        elif amount_value >= self.VERY_HIGH_VALUE_THRESHOLD:  # 100,000円以上
            risk += 35
        elif amount_value >= self.HIGH_VALUE_THRESHOLD:  # 50,000円以上
            risk += 25
        elif amount_value >= self.MODERATE_VALUE_THRESHOLD:  # 10,000円以上
            risk += 10
        elif amount_value >= 5000 * 100:  # 5,000円以上
            risk += 5

        # Intent制約上限との比率（intent_mandateがある場合のみ）
        if intent_mandate:
            max_amount = intent_mandate.get("constraints", {}).get("max_amount", {})
            max_amount_str = max_amount.get("value", "0")
            try:
                if "." in max_amount_str:
                    max_amount_value = int(float(max_amount_str) * 100)
                else:
                    max_amount_value = int(max_amount_str)
            except (ValueError, TypeError):
                max_amount_value = 0

            if max_amount_value > 0:
                ratio = amount_value / max_amount_value
                if ratio >= 0.95:  # 上限の95%以上
                    risk += 10
                elif ratio >= 0.80:  # 上限の80%以上
                    risk += 5

        return min(risk, 80)

    def _assess_constraint_compliance(
        self,
        payment_mandate: Dict,
        cart_mandate: Optional[Dict],
        intent_mandate: Dict
    ) -> int:
        """
        Intent制約への準拠を評価（AP2完全準拠）

        Returns:
            0または50（違反があれば高リスク）
        """
        # AP2完全準拠: PaymentMandateの正しい構造からデータを取得
        # payment_mandate["payment_mandate_contents"]["payment_details_total"]["amount"]
        payment_mandate_contents = payment_mandate.get("payment_mandate_contents", {})
        payment_details_total = payment_mandate_contents.get("payment_details_total", {})
        payment_amount = payment_details_total.get("amount", {})
        payment_value_str = str(payment_amount.get("value", "0"))
        payment_currency = payment_amount.get("currency", "JPY")

        # IntentMandateの制約から最大金額を取得
        max_amount = intent_mandate.get("constraints", {}).get("max_amount", {})
        max_value_str = str(max_amount.get("value", "0"))
        max_currency = max_amount.get("currency", "JPY")

        try:
            # AP2完全準拠: PaymentItemのvalueはfloatまたはint（円単位）
            if "." in payment_value_str:
                payment_value = int(float(payment_value_str) * 100)
            else:
                payment_value = int(payment_value_str) * 100  # 円→セント変換

            if "." in max_value_str:
                max_value = int(float(max_value_str) * 100)
            else:
                max_value = int(max_value_str) * 100  # 円→セント変換

            if payment_value > max_value:
                logger.warning(
                    f"[RiskAssessmentEngine] Amount exceeds constraint: "
                    f"{payment_value/100}円 > {max_value/100}円"
                )
                return 50
        except (ValueError, TypeError) as e:
            logger.warning(
                f"[RiskAssessmentEngine] Failed to parse amounts for constraint check: "
                f"payment_value={payment_value_str}, max_value={max_value_str}, error={e}"
            )

        # 通貨不一致
        if payment_currency != max_currency:
            logger.warning(
                f"[RiskAssessmentEngine] Currency mismatch: "
                f"{payment_currency} != {max_currency}"
            )
            return 50

        # ブランド制約チェック（未実装）
        # AP2仕様では、Intent制約にブランド指定がある場合、Cart内の商品ブランドが
        # 制約に準拠しているかを検証する必要がある
        # デモ実装では、商品のブランド情報が不完全なため、このチェックは省略している
        # 本番実装では、以下のようなチェックが必要：
        # - cart_mandate内の全itemsに対してbrand情報を取得
        # - intent_mandate.constraints.brandsリストと照合
        # - 違反があれば50を返す

        return 0

    def _assess_agent_involvement(self, agent_involved: bool) -> int:
        """
        Agent関与によるリスクを評価

        Returns:
            0-5のリスクスコア
        """
        # Agentが関与している場合、プロトコルに従っているので低リスク
        return 5 if agent_involved else 0

    def _assess_transaction_type(self, transaction_type: str) -> int:
        """
        取引タイプのリスクを評価

        Returns:
            0-15のリスクスコア
        """
        if transaction_type == "human_not_present":
            # カード番号盗用のリスクが高い
            return 15
        else:
            # 物理的なカード提示が必要なので低リスク
            return 5

    def _assess_payment_method(self, payment_method: Dict) -> int:
        """
        支払い方法のリスクを評価

        AP2完全準拠 & PCI DSS準拠:
        - 引数payment_methodは実際にはPaymentResponse（W3C Payment Request API準拠）
        - トークン化された支払い方法（tokenized=true）の場合、有効期限チェックは不要
        - Credential Providerが内部でトークンと紐付けられたカード情報を管理
        - A2A通信には有効期限を含めない（PCI DSS 3.2.2項準拠）

        Args:
            payment_method: PaymentResponse（W3C Payment Request API形式）
                {
                  "methodName": "https://a2a-protocol.org/payment-methods/ap2-payment",
                  "details": {
                    "cardBrand": "Visa",
                    "token": "tok_...",
                    "tokenized": true
                  }
                }

        Returns:
            0-25のリスクスコア
        """
        risk = 0

        # W3C Payment Request API準拠: PaymentResponseからdetailsを取得
        details = payment_method.get("details", {})
        method_name = payment_method.get("methodName", "")

        # カード決済の場合のみリスク評価
        # AP2完全準拠: AP2公式payment method URLを優先
        # 注意: basic-cardは非推奨だが、既存データとの互換性のため判定は維持
        is_card_payment = (
            method_name == "https://a2a-protocol.org/payment-methods/ap2-payment" or
            method_name == "basic-card" or  # 既存データとの互換性
            method_name == "card"  # 既存データとの互換性
        )

        if is_card_payment:
            # AP2 & PCI DSS準拠：トークン化済みの場合は有効期限チェックをスキップ
            is_tokenized = details.get("tokenized", False)

            if is_tokenized:
                # トークン化された支払い方法：有効期限はCredential Provider内部で管理
                logger.info(
                    "[_assess_payment_method] Tokenized payment method detected. "
                    "Skipping expiry date validation (managed by Credential Provider)."
                )
                # トークンの存在確認のみ
                token = details.get("token")
                if not token or token == '':
                    logger.warning("[_assess_payment_method] Tokenized payment method missing token")
                    risk += 15
                else:
                    logger.debug(f"[_assess_payment_method] Token found: {token[:20]}...")
            else:
                # 非トークン化の支払い方法：有効期限チェックが必要
                current_year = datetime.now().year
                current_month = datetime.now().month

                expiry_year = details.get("expiry_year") or details.get("expiryYear")
                expiry_month = details.get("expiry_month") or details.get("expiryMonth")

                # 有効期限が設定されていない場合は高リスク
                if not expiry_year or not expiry_month:
                    logger.error(
                        f"[_assess_payment_method] Invalid payment method: "
                        f"missing expiry_year or expiry_month. "
                        f"expiry_year={expiry_year}, expiry_month={expiry_month}"
                    )
                    raise ValueError(
                        "Invalid payment method: expiry_year and expiry_month are required for card payments. "
                        "Please register a valid payment method with proper expiration date."
                    )

                # 有効期限が近い（3ヶ月以内）
                try:
                    months_until_expiry = (int(expiry_year) - current_year) * 12 + (int(expiry_month) - current_month)
                except (TypeError, ValueError) as e:
                    logger.error(
                        f"[_assess_payment_method] Invalid expiry date format: "
                        f"expiry_year={expiry_year}, expiry_month={expiry_month}, error={e}"
                    )
                    raise ValueError(
                        f"Invalid payment method expiry date format: "
                        f"expiry_year={expiry_year}, expiry_month={expiry_month}. "
                        f"Expected numeric values."
                    )
                if months_until_expiry <= 3:
                    risk += 10

                # 有効期限が切れている
                if months_until_expiry < 0:
                    risk += 50

                # トークン化されていない場合
                token = details.get("token")
                if not token or token == '':
                    risk += 15

        return min(risk, 25)

    def _assess_transaction_pattern(self, payer_id: str, amount_value_str: str) -> int:
        """
        取引パターンのリスクを評価（データベースまたはインメモリ）

        Returns:
            0-30のリスクスコア
        """
        import asyncio

        # 非同期処理が必要な場合はイベントループを取得
        # ただし、このメソッドは同期メソッドなので、非同期処理を避ける
        # そのため、データベースモードでも同期的に動作させる必要がある

        risk = 0

        # データベースモードまたはインメモリモードで履歴を取得
        if self.db_manager:
            # データベースから取引履歴を取得（同期的に）
            # 注意: ここは本来非同期メソッドだが、既存のインターフェースを維持するため
            # データベースアクセスはskip（次のリファクタリングで対応）
            # 一旦インメモリフォールバック
            logger.debug("[RiskAssessmentEngine] Database mode enabled but sync context - using fallback")
            history = self.transaction_history.get(payer_id, [])
        else:
            # インメモリモード
            history = self.transaction_history.get(payer_id, [])

        if not history:
            # 初回取引（新規ユーザー）
            risk += 15
        else:
            # 過去24時間の取引数をチェック
            now = datetime.now()
            recent_transactions = [
                t for t in history
                if (now - datetime.fromisoformat(t['timestamp'])).total_seconds() < 86400
            ]

            if len(recent_transactions) >= 5:
                # 24時間以内に5回以上の取引（カードテスティングの可能性）
                risk += 30
            elif len(recent_transactions) >= 3:
                risk += 15

            # 金額の急激な変化
            if history:
                try:
                    # 値を整数に変換
                    if "." in amount_value_str:
                        current_amount = int(float(amount_value_str) * 100)
                    else:
                        current_amount = int(amount_value_str)

                    # 過去5件の取引金額の平均を計算
                    recent_amounts = []
                    for t in history[-5:]:
                        amount_str = t.get('amount', '0')
                        try:
                            if "." in amount_str:
                                val = int(float(amount_str) * 100)
                            else:
                                val = int(amount_str)
                            recent_amounts.append(val)
                        except (ValueError, TypeError):
                            continue

                    if recent_amounts:
                        avg_amount = sum(recent_amounts) / len(recent_amounts)
                        if current_amount > avg_amount * 3:
                            # 平均の3倍以上（異常パターン）
                            risk += 15
                except (ValueError, TypeError):
                    logger.warning("[RiskAssessmentEngine] Failed to parse amount for pattern check")

        return min(risk, 30)

    def _assess_shipping_risk(self, cart_mandate: Dict) -> int:
        """
        配送先のリスクを評価

        Returns:
            0-20のリスクスコア
        """
        risk = 0

        shipping = cart_mandate.get("shipping_address", {})
        address_line1 = shipping.get("address_line1", "")

        # 私書箱や郵便局留め（簡易チェック）
        if 'P.O.' in address_line1 or 'PO Box' in address_line1 or '私書箱' in address_line1:
            risk += 15

        # 配送方法が速達（cart_mandateに shipping_methodがある場合）
        shipping_method = cart_mandate.get("shipping_method", "standard")
        if shipping_method in ['express', 'overnight', '速達']:
            risk += 5

        return min(risk, 20)

    def _assess_temporal_risk(
        self,
        intent_created_at: Optional[str],
        payment_created_at: Optional[str]
    ) -> int:
        """
        時間的リスクを評価（Intent作成から決済までの時間）

        Returns:
            0-15のリスクスコア
        """
        if not intent_created_at or not payment_created_at:
            return 0

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

        except Exception as e:
            logger.warning(f"[RiskAssessmentEngine] Failed to assess temporal risk: {e}")
            return 0

    def _calculate_total_risk_score(self, risk_factors: Dict[str, int]) -> int:
        """
        総合リスクスコアを計算（加重平均）

        Returns:
            0-100のリスクスコア
        """
        # 各要因の重み
        weights = {
            "amount_risk": 2.5,
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

        Returns:
            "approve", "review", "decline"
        """
        if risk_score < self.LOW_RISK_THRESHOLD:
            return "approve"
        elif risk_score < self.HIGH_RISK_THRESHOLD:
            return "review"
        else:
            return "decline"

    def _record_transaction(self, payer_id: str, amount_value_str: str, risk_score: int):
        """
        取引を履歴に記録（データベースまたはインメモリ）

        注意: このメソッドは同期メソッドですが、将来的に非同期化する必要があります。
        現時点では、データベース保存は別途非同期コンテキストで行う必要があります。
        """
        # インメモリ履歴に記録（後方互換性）
        if payer_id not in self.transaction_history:
            self.transaction_history[payer_id] = []

        self.transaction_history[payer_id].append({
            "timestamp": datetime.now().isoformat(),
            "amount": amount_value_str,
            "risk_score": risk_score
        })

        # 古い履歴を削除（30日以上前）
        cutoff = datetime.now() - timedelta(days=30)
        self.transaction_history[payer_id] = [
            t for t in self.transaction_history[payer_id]
            if datetime.fromisoformat(t['timestamp']) > cutoff
        ]

        # データベースモードの場合、呼び出し元で非同期保存を行う必要がある
        # （このメソッドは同期メソッドのため、ここでは保存しない）
        logger.debug(f"[RiskAssessmentEngine] Transaction recorded: payer_id={payer_id}, risk_score={risk_score}")

    async def record_transaction_to_db(self, payer_id: str, amount_value_str: str, risk_score: int, currency: str = "JPY"):
        """
        取引履歴をデータベースに保存（非同期メソッド）

        Args:
            payer_id: ユーザーID
            amount_value_str: 金額（文字列形式、例: "10000.00"）
            risk_score: リスクスコア
            currency: 通貨（デフォルト: JPY）
        """
        if not self.db_manager:
            logger.warning("[RiskAssessmentEngine] Database manager not configured, skipping DB save")
            return

        try:
            # 金額をcent単位の整数に変換
            if "." in amount_value_str:
                amount_cents = int(float(amount_value_str) * 100)
            else:
                amount_cents = int(amount_value_str)

            # データベースに保存
            from common.database import TransactionHistoryCRUD

            async with self.db_manager.get_session() as session:
                await TransactionHistoryCRUD.create(session, {
                    "payer_id": payer_id,
                    "amount_value": amount_cents,
                    "currency": currency,
                    "risk_score": risk_score
                })

            logger.info(f"[RiskAssessmentEngine] Transaction history saved to database: payer_id={payer_id}, amount_cents={amount_cents}, risk_score={risk_score}")

        except Exception as e:
            logger.error(f"[RiskAssessmentEngine] Failed to save transaction history to database: {e}", exc_info=True)

    async def get_transaction_history_from_db(self, payer_id: str, days: int = 30) -> List[Dict]:
        """
        データベースから取引履歴を取得（非同期メソッド）

        Args:
            payer_id: ユーザーID
            days: 過去何日間の履歴を取得するか

        Returns:
            取引履歴のリスト
        """
        if not self.db_manager:
            logger.warning("[RiskAssessmentEngine] Database manager not configured, returning empty history")
            return []

        try:
            from common.database import TransactionHistoryCRUD

            async with self.db_manager.get_session() as session:
                history_records = await TransactionHistoryCRUD.get_by_payer_id(session, payer_id, days=days)

            # TransactionHistoryオブジェクトをdictに変換
            history = [record.to_dict() for record in history_records]

            logger.info(f"[RiskAssessmentEngine] Retrieved {len(history)} transaction history records from database for payer_id={payer_id}")

            return history

        except Exception as e:
            logger.error(f"[RiskAssessmentEngine] Failed to retrieve transaction history from database: {e}", exc_info=True)
            return []