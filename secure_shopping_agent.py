"""
AP2 Protocol - Shopping Agent（暗号署名機能統合版）
実際の暗号署名を使用したセキュアな実装
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from dataclasses import asdict

from ap2_types import (
    IntentMandate,
    IntentConstraints,
    CartMandate,
    PaymentMandate,
    Amount,
    AgentIdentity,
    AgentType,
    CardPaymentMethod,
    TransactionResult,
    TransactionStatus,
    AP2ErrorCode,
    MandateError,
    VersionError,
    validate_mandate_version,
    DEFAULT_AP2_VERSION,
    # A2A Extension拡張型
    AgentSignal,
    MandateMetadata,
    RiskPayload
)

from ap2_crypto import KeyManager, SignatureManager, compute_mandate_hash
from risk_assessment import RiskAssessmentEngine


class SecureShoppingAgent:
    """
    Shopping Agent（暗号署名統合版）
    実際の暗号署名を使用してセキュアにMandateを処理
    """
    
    def __init__(
        self,
        agent_id: str,
        agent_name: str,
        passphrase: str
    ):
        """
        Args:
            agent_id: エージェントID
            agent_name: エージェント名
            passphrase: 秘密鍵の暗号化に使用するパスフレーズ
        """
        self.agent_id = agent_id
        self.agent_name = agent_name
        
        # 鍵管理と署名管理の初期化
        self.key_manager = KeyManager()
        self.signature_manager = SignatureManager(self.key_manager)
        
        # エージェント自身の鍵ペアを生成
        self._initialize_agent_keys(passphrase)
        
        self.identity = AgentIdentity(
            id=agent_id,
            name=agent_name,
            type=AgentType.SHOPPING,
            public_key=self.key_manager.public_key_to_base64(self.public_key)
        )

        # リスク評価エンジン
        self.risk_engine = RiskAssessmentEngine()
    
    def _initialize_agent_keys(self, passphrase: str):
        """エージェントの鍵ペアを初期化"""
        print(f"[{self.agent_name}] 鍵ペアを初期化中...")
        
        try:
            # 既存の鍵を読み込み
            self.private_key = self.key_manager.load_private_key_encrypted(
                self.agent_id,
                passphrase
            )
            self.public_key = self.private_key.public_key()
            print(f"  ✓ 既存の鍵を読み込みました")
            
        except Exception:
            # 新しい鍵を生成
            print(f"  新しい鍵ペアを生成します...")
            self.private_key, self.public_key = self.key_manager.generate_key_pair(
                self.agent_id
            )
            
            # 暗号化して保存
            self.key_manager.save_private_key_encrypted(
                self.agent_id,
                self.private_key,
                passphrase
            )
            self.key_manager.save_public_key(self.agent_id, self.public_key)
    
    def create_intent_mandate_with_user_key(
        self,
        user_id: str,
        user_key_manager: KeyManager,
        intent: str,
        max_amount: Amount,
        valid_hours: int = 24,
        categories: Optional[List[str]] = None,
        brands: Optional[List[str]] = None
    ) -> IntentMandate:
        """
        ユーザーの鍵でIntent Mandateを作成し署名
        
        Args:
            user_id: ユーザーID
            user_key_manager: ユーザーの鍵管理インスタンス
            intent: 購買意図
            max_amount: 最大金額
            valid_hours: 有効期間（時間）
            categories: カテゴリー制約
            brands: ブランド制約
            
        Returns:
            IntentMandate: 署名されたIntent Mandate
        """
        print(f"\n[{self.agent_name}] Intent Mandateを作成中...")
        
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=valid_hours)
        
        # merchants制約を空リストで明示（AP2仕様準拠）
        merchants_constraint = []  # nullではなく空配列

        constraints = IntentConstraints(
            max_amount=max_amount,
            categories=categories,
            brands=brands,
            merchants=merchants_constraint,  # AP2仕様：空リストを明示
            valid_until=expires_at.isoformat().replace('+00:00', 'Z'),
            valid_from=now.isoformat().replace('+00:00', 'Z'),
            max_transactions=1
        )

        # ユーザーの公開鍵を取得
        user_public_key = user_key_manager.get_private_key(user_id).public_key()
        user_public_key_base64 = user_key_manager.public_key_to_base64(user_public_key)

        # A2A Extension: Agent Signalを作成
        agent_signal = AgentSignal(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            agent_version="1.0",
            agent_provider="AP2 Demo",
            model_name="Gemini 2.5 Flash",
            confidence_score=0.95,
            human_oversight=True,
            autonomous_level='semi_autonomous'  # AP2 Bedrock v0.2互換（human_in_loopも許容）
        )

        # A2A Extension: 初期Risk Payloadを作成
        # 注: AP2仕様では、nullフィールドは送信しないことが推奨される
        risk_payload = RiskPayload(
            device_fingerprint=f"device_{uuid.uuid4().hex[:16]}",
            platform="Web",
            session_id=f"session_{uuid.uuid4().hex[:16]}",
            account_age_days=30,  # サンプル値
            previous_transactions=5  # サンプル値
            # nullフィールドは明示的に設定しない（デフォルトNoneのまま）
        )

        intent_mandate = IntentMandate(
            id=f"intent_{uuid.uuid4().hex}",
            type='IntentMandate',
            version='0.1',
            user_id=user_id,
            user_public_key=user_public_key_base64,
            intent=intent,
            constraints=constraints,
            created_at=now.isoformat().replace('+00:00', 'Z'),
            expires_at=expires_at.isoformat().replace('+00:00', 'Z'),
            # A2A Extension拡張フィールド
            agent_signal=None,  # v0.2以降はmandate_metadata.agent_signalに移動
            risk_payload=risk_payload
        )

        # ユーザーの秘密鍵で署名（mandate_metadataは署名後に追加）
        user_signature_manager = SignatureManager(user_key_manager)
        intent_mandate.user_signature = user_signature_manager.sign_mandate(
            asdict(intent_mandate),
            user_id
        )

        # A2A Extension: Mandate Hashを計算してMandate Metadataを追加
        mandate_dict = asdict(intent_mandate)
        mandate_hash = compute_mandate_hash(mandate_dict, hash_format='hex')

        # 署名チェーン（audit_trail）を作成
        audit_trail = [
            {
                "action": "user_signature",
                "signer_id": user_id,
                "signed_at": intent_mandate.user_signature.signed_at,
                "signature_algorithm": intent_mandate.user_signature.algorithm,
                "mandate_type": "IntentMandate"
            }
        ]

        # Mandate Metadataにagent_signalとaudit_trailを含める（v0.2推奨）
        intent_mandate.mandate_metadata = MandateMetadata(
            mandate_hash=mandate_hash,
            schema_version='0.1',
            issuer=self.agent_id,
            issued_at=now.isoformat().replace('+00:00', 'Z'),
            nonce=uuid.uuid4().hex,
            agent_signal=agent_signal,  # v0.2以降の推奨位置
            audit_trail=audit_trail  # 署名チェーンの証跡
        )

        print(f"  ✓ Intent Mandate作成完了: {intent_mandate.id}")
        print(f"  ✓ ユーザー署名追加")
        print(f"  ✓ Mandate Hash: {mandate_hash[:16]}...")
        print(f"  ✓ Agent Signal: {agent_signal.agent_name}")
        
        # 署名を検証
        self._verify_intent_mandate(intent_mandate)
        
        return intent_mandate
    
    def _verify_intent_mandate_expiration(self, intent_mandate: IntentMandate) -> None:
        """
        Intent Mandateの有効期限を検証

        Args:
            intent_mandate: 検証するIntent Mandate

        Raises:
            MandateError: 期限切れの場合
        """
        # 不正な形式（+00:00Z）を修正してからパース
        expires_at_str = intent_mandate.expires_at.replace('+00:00Z', 'Z').replace('Z', '+00:00')
        expires_at = datetime.fromisoformat(expires_at_str)
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

    def _verify_intent_mandate(self, intent_mandate: IntentMandate) -> bool:
        """Intent Mandateの署名を検証"""
        print(f"[{self.agent_name}] Intent Mandateの署名を検証中...")

        if not intent_mandate.user_signature:
            print(f"  ✗ ユーザー署名がありません")
            return False

        mandate_dict = asdict(intent_mandate)
        is_valid = self.signature_manager.verify_mandate_signature(
            mandate_dict,
            intent_mandate.user_signature
        )

        if is_valid:
            print(f"  ✓ Intent Mandateの署名は有効です")
        else:
            print(f"  ✗ Intent Mandateの署名が無効です")

        return is_valid
    
    def verify_cart_mandate(
        self,
        cart_mandate: CartMandate
    ) -> bool:
        """
        Cart Mandateの署名を検証
        
        Args:
            cart_mandate: 検証するCart Mandate
            
        Returns:
            bool: 検証結果
        """
        print(f"\n[{self.agent_name}] Cart Mandateの署名を検証中...")
        
        cart_dict = asdict(cart_mandate)
        
        # Merchant署名を検証
        if not cart_mandate.merchant_signature:
            print(f"  ✗ Merchant署名がありません")
            return False
        
        is_merchant_valid = self.signature_manager.verify_mandate_signature(
            cart_dict,
            cart_mandate.merchant_signature
        )
        
        if not is_merchant_valid:
            print(f"  ✗ Merchant署名が無効です")
            return False
        
        print(f"  ✓ Merchant署名は有効です")
        
        # User署名を検証（Human Presentの場合）
        if cart_mandate.user_signature:
            is_user_valid = self.signature_manager.verify_mandate_signature(
                cart_dict,
                cart_mandate.user_signature
            )
            
            if is_user_valid:
                print(f"  ✓ User署名は有効です")
            else:
                print(f"  ✗ User署名が無効です")
                return False
        
        return True
    
    async def select_and_sign_cart(
        self,
        cart_mandate: CartMandate,
        user_id: str,
        user_key_manager: KeyManager
    ) -> CartMandate:
        """
        カートを選択し、ユーザーの署名を追加
        
        Args:
            cart_mandate: Cart Mandate
            user_id: ユーザーID
            user_key_manager: ユーザーの鍵管理インスタンス
            
        Returns:
            CartMandate: ユーザー署名付きCart Mandate
        """
        print(f"\n[{self.agent_name}] カートにユーザー署名を追加中...")
        print(f"  商品数: {len(cart_mandate.items)}")
        print(f"  合計金額: {cart_mandate.total}")
        
        # ユーザーが署名
        user_signature_manager = SignatureManager(user_key_manager)
        cart_mandate.user_signature = user_signature_manager.sign_mandate(
            asdict(cart_mandate),
            user_id
        )
        
        print(f"  ✓ ユーザー署名を追加しました")
        
        # 署名を検証
        self.verify_cart_mandate(cart_mandate)
        
        return cart_mandate
    
    async def create_payment_mandate(
        self,
        cart_mandate: CartMandate,
        intent_mandate: IntentMandate,
        payment_method: CardPaymentMethod,
        user_id: str,
        user_key_manager: KeyManager,
        device_attestation: Optional['DeviceAttestation'] = None,
        payment_id: Optional[str] = None
    ) -> PaymentMandate:
        """
        Payment Mandateを作成し署名

        AP2プロトコル ステップ23: Device AttestationとともにPayment Mandateを作成

        Args:
            cart_mandate: Cart Mandate
            intent_mandate: Intent Mandate
            payment_method: 支払い方法
            user_id: ユーザーID
            user_key_manager: ユーザーの鍵管理インスタンス
            device_attestation: Device Attestation（AP2ステップ20-22で生成）
            payment_id: Payment MandateのID（指定しない場合は自動生成）

        Returns:
            PaymentMandate: 署名されたPayment Mandate
        """
        print(f"\n[{self.agent_name}] Payment Mandateを作成中...")

        # Intent Mandateの有効期限を検証
        self._verify_intent_mandate_expiration(intent_mandate)
        print(f"  ✓ Intent Mandate有効期限OK")

        if device_attestation:
            print(f"  ✓ Device Attestation検出: {device_attestation.device_id}")
            print(f"    - Platform: {device_attestation.platform}")
            print(f"    - Type: {device_attestation.attestation_type.value}")

        # Payment IDが指定されていない場合は新規生成
        if not payment_id:
            payment_id = f"payment_{uuid.uuid4().hex}"

        # Payment Mandateの有効期限を設定（作成時刻から15分）
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=15)

        # A2A Extension: IntentMandateとCartMandateのハッシュを計算
        intent_mandate_dict = asdict(intent_mandate)
        intent_mandate_hash = compute_mandate_hash(intent_mandate_dict, hash_format='hex')

        cart_mandate_dict = asdict(cart_mandate)
        cart_mandate_hash = compute_mandate_hash(cart_mandate_dict, hash_format='hex')

        # A2A Extension: Risk Payloadの連鎖
        # IntentMandate→CartMandate→PaymentMandateとリスク情報を引き継ぐ
        combined_risk_payload = RiskPayload(
            # IntentMandateから引き継ぐ
            device_fingerprint=intent_mandate.risk_payload.device_fingerprint if intent_mandate.risk_payload else None,
            platform=intent_mandate.risk_payload.platform if intent_mandate.risk_payload else None,
            session_id=intent_mandate.risk_payload.session_id if intent_mandate.risk_payload else None,
            account_age_days=intent_mandate.risk_payload.account_age_days if intent_mandate.risk_payload else None,
            previous_transactions=intent_mandate.risk_payload.previous_transactions if intent_mandate.risk_payload else None,
            # CartMandateから追加情報を引き継ぐ（存在する場合）
            ip_address=cart_mandate.risk_payload.ip_address if cart_mandate.risk_payload else None,
            # Payment段階で追加情報を設定
            time_on_site=180,  # サンプル値：3分
            pages_viewed=5  # サンプル値
        )

        payment_mandate = PaymentMandate(
            id=payment_id,
            type='PaymentMandate',
            version='0.1',
            cart_mandate_id=cart_mandate.id,
            intent_mandate_id=intent_mandate.id,
            payment_method=payment_method,
            amount=cart_mandate.total,
            transaction_type='user_present',  # AP2仕様v0.2推奨値（human_presentは非推奨）
            agent_involved=True,
            payer_id=user_id,
            payee_id=cart_mandate.merchant_id,
            created_at=now.isoformat().replace('+00:00', 'Z'),
            expires_at=expires_at.isoformat().replace('+00:00', 'Z'),
            merchant_signature=cart_mandate.merchant_signature,  # Cart MandateのMerchant署名を継承
            device_attestation=device_attestation,  # AP2ステップ23: Device Attestationを含める
            # A2A Extension拡張フィールド
            cart_mandate_hash=cart_mandate_hash,
            intent_mandate_hash=intent_mandate_hash,
            risk_payload=combined_risk_payload
        )
        
        # リスク評価を実行
        print(f"  リスク評価を実行中...")
        risk_result = self.risk_engine.assess_payment_mandate(
            payment_mandate,
            cart_mandate,
            intent_mandate
        )

        # リスクスコアと不正指標を設定
        payment_mandate.risk_score = risk_result.risk_score
        payment_mandate.fraud_indicators = risk_result.fraud_indicators

        print(f"  ✓ リスク評価完了")
        print(f"    - リスクスコア: {risk_result.risk_score}/100")
        print(f"    - 推奨アクション: {risk_result.recommendation}")
        if risk_result.fraud_indicators:
            print(f"    - 不正指標: {', '.join(risk_result.fraud_indicators)}")

        # ユーザーの署名を追加
        # 注: Payment MandateにはCart MandateのMerchant署名を継承し、
        # さらにユーザーが最終承認の署名を追加します
        user_signature_manager = SignatureManager(user_key_manager)
        payment_mandate.user_signature = user_signature_manager.sign_mandate(
            asdict(payment_mandate),
            user_id
        )

        # A2A Extension: Mandate Hashを計算してMandate Metadataを追加
        payment_mandate_dict = asdict(payment_mandate)
        payment_mandate_hash = compute_mandate_hash(payment_mandate_dict, hash_format='hex')

        # 署名チェーン（audit_trail）を作成
        # Payment Mandateには複数の署名が含まれる：
        # 1. IntentMandateからのUser署名
        # 2. CartMandateからのMerchant署名
        # 3. CartMandateへのUser署名（select_and_sign_cart後）
        # 4. PaymentMandateへのUser署名
        audit_trail = []

        # Merchant署名の記録（CartMandateから継承）
        if payment_mandate.merchant_signature:
            audit_trail.append({
                "action": "merchant_signature",
                "signer_id": cart_mandate.merchant_id,
                "signed_at": payment_mandate.merchant_signature.signed_at,
                "signature_algorithm": payment_mandate.merchant_signature.algorithm,
                "mandate_type": "CartMandate",
                "inherited_from": "CartMandate"
            })

        # User署名の記録（Payment Mandate）
        audit_trail.append({
            "action": "user_signature",
            "signer_id": user_id,
            "signed_at": payment_mandate.user_signature.signed_at,
            "signature_algorithm": payment_mandate.user_signature.algorithm,
            "mandate_type": "PaymentMandate"
        })

        payment_mandate.mandate_metadata = MandateMetadata(
            mandate_hash=payment_mandate_hash,
            schema_version='0.1',
            issuer=self.agent_id,
            issued_at=now.isoformat().replace('+00:00', 'Z'),
            previous_mandate_hash=cart_mandate_hash,  # CartMandateから連鎖
            nonce=uuid.uuid4().hex,
            audit_trail=audit_trail  # 署名チェーンの証跡
        )

        print(f"  ✓ Payment Mandate作成完了: {payment_mandate.id}")
        print(f"  ✓ ユーザー署名追加")
        print(f"  ✓ Mandate Hash: {payment_mandate_hash[:16]}...")
        print(f"  ✓ IntentMandate Hash参照: {intent_mandate_hash[:16]}...")
        print(f"  ✓ CartMandate Hash参照: {cart_mandate_hash[:16]}...")

        return payment_mandate
    
    async def process_payment(
        self,
        payment_mandate: PaymentMandate,
        payment_processor_id: str,
        otp: Optional[str] = None
    ) -> TransactionResult:
        """
        支払いを処理
        
        Args:
            payment_mandate: Payment Mandate
            payment_processor_id: Payment ProcessorのID
            otp: ワンタイムパスワード
            
        Returns:
            TransactionResult: トランザクション結果
        """
        print(f"\n[{self.agent_name}] 支払いを処理中...")
        print(f"  金額: {payment_mandate.amount}")
        print(f"  支払い方法: {payment_mandate.payment_method.type}")
        
        # Payment Mandateの署名を検証
        payment_dict = asdict(payment_mandate)
        
        if payment_mandate.user_signature:
            is_user_valid = self.signature_manager.verify_mandate_signature(
                payment_dict,
                payment_mandate.user_signature
            )
            if not is_user_valid:
                raise Exception("Payment MandateのUser署名が無効です")
            print(f"  ✓ User署名検証完了")
        
        if payment_mandate.merchant_signature:
            is_merchant_valid = self.signature_manager.verify_mandate_signature(
                payment_dict,
                payment_mandate.merchant_signature
            )
            if not is_merchant_valid:
                raise Exception("Payment MandateのMerchant署名が無効です")
            print(f"  ✓ Merchant署名検証完了")
        
        # 実際の支払い処理（シミュレーション）
        result = TransactionResult(
            id=f"txn_{uuid.uuid4().hex}",
            status=TransactionStatus.CAPTURED,
            payment_mandate_id=payment_mandate.id,
            authorized_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            captured_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            receipt_url=f"https://example.com/receipt/{uuid.uuid4().hex}"
        )
        
        print(f"  ✓ 支払い成功: {result.id}")
        print(f"  領収書URL: {result.receipt_url}")
        
        return result


# ========================================
# 使用例
# ========================================

async def demo_secure_shopping():
    """セキュアなShopping Agentのデモ"""
    
    print("=" * 80)
    print("AP2 Protocol - セキュアなShopping Agentのデモ")
    print("=" * 80)
    
    # ユーザーの鍵管理を初期化
    print("\n" + "=" * 80)
    print("ステップ1: ユーザーとエージェントの鍵を初期化")
    print("=" * 80)
    
    user_id = "user_123"
    user_passphrase = "secure_user_passphrase"
    user_key_manager = KeyManager()
    
    try:
        # 既存の鍵を読み込み
        user_key_manager.load_private_key_encrypted(user_id, user_passphrase)
        print(f"[User] 既存の鍵を読み込みました")
    except Exception:
        # 新しい鍵を生成
        print(f"[User] 新しい鍵ペアを生成します...")
        user_private_key, user_public_key = user_key_manager.generate_key_pair(user_id)
        user_key_manager.save_private_key_encrypted(user_id, user_private_key, user_passphrase)
        user_key_manager.save_public_key(user_id, user_public_key)
    
    # Shopping Agentを初期化
    shopping_agent = SecureShoppingAgent(
        agent_id="shopping_agent_001",
        agent_name="Secure Shopping Assistant",
        passphrase="agent_secure_passphrase"
    )
    
    # Intent Mandateを作成
    print("\n" + "=" * 80)
    print("ステップ2: Intent Mandateの作成と署名")
    print("=" * 80)
    
    intent_mandate = shopping_agent.create_intent_mandate_with_user_key(
        user_id=user_id,
        user_key_manager=user_key_manager,
        intent="新しいランニングシューズを100ドル以下で購入したい",
        max_amount=Amount(value="100.00", currency="USD"),
        categories=["running"],
        brands=["Nike", "Adidas", "Asics"]
    )
    
    print(f"\nIntent Mandate ID: {intent_mandate.id}")
    print(f"意図: {intent_mandate.intent}")
    print(f"最大金額: {intent_mandate.constraints.max_amount}")
    print(f"署名アルゴリズム: {intent_mandate.user_signature.algorithm}")
    
    print("\n" + "=" * 80)
    print("デモンストレーション完了!")
    print("=" * 80)


if __name__ == "__main__":
    import asyncio
    asyncio.run(demo_secure_shopping())
