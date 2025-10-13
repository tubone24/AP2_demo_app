"""
AP2 Protocol - Shopping Agent（暗号署名機能統合版）
実際の暗号署名を使用したセキュアな実装
"""

import uuid
from datetime import datetime, timedelta
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
    TransactionStatus
)

from ap2_crypto import KeyManager, SignatureManager


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
        
        now = datetime.utcnow()
        expires_at = now + timedelta(hours=valid_hours)
        
        constraints = IntentConstraints(
            max_amount=max_amount,
            categories=categories,
            brands=brands,
            valid_until=expires_at.isoformat() + 'Z',
            valid_from=now.isoformat() + 'Z',
            max_transactions=1
        )
        
        # ユーザーの公開鍵を取得
        user_public_key = user_key_manager.get_private_key(user_id).public_key()
        user_public_key_base64 = user_key_manager.public_key_to_base64(user_public_key)
        
        intent_mandate = IntentMandate(
            id=f"intent_{uuid.uuid4().hex}",
            type='IntentMandate',
            version='0.1',
            user_id=user_id,
            user_public_key=user_public_key_base64,
            intent=intent,
            constraints=constraints,
            created_at=now.isoformat() + 'Z',
            expires_at=expires_at.isoformat() + 'Z'
        )
        
        # ユーザーの秘密鍵で署名
        user_signature_manager = SignatureManager(user_key_manager)
        intent_mandate.user_signature = user_signature_manager.sign_mandate(
            asdict(intent_mandate),
            user_id
        )
        
        print(f"  ✓ Intent Mandate作成完了: {intent_mandate.id}")
        print(f"  ✓ ユーザー署名追加")
        
        # 署名を検証
        self._verify_intent_mandate(intent_mandate)
        
        return intent_mandate
    
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
        user_key_manager: KeyManager
    ) -> PaymentMandate:
        """
        Payment Mandateを作成し署名
        
        Args:
            cart_mandate: Cart Mandate
            intent_mandate: Intent Mandate
            payment_method: 支払い方法
            user_id: ユーザーID
            user_key_manager: ユーザーの鍵管理インスタンス
            
        Returns:
            PaymentMandate: 署名されたPayment Mandate
        """
        print(f"\n[{self.agent_name}] Payment Mandateを作成中...")
        
        payment_mandate = PaymentMandate(
            id=f"payment_{uuid.uuid4().hex}",
            type='PaymentMandate',
            version='0.1',
            cart_mandate_id=cart_mandate.id,
            intent_mandate_id=intent_mandate.id,
            payment_method=payment_method,
            amount=cart_mandate.total,
            transaction_type='human_present',
            agent_involved=True,
            payer_id=user_id,
            payee_id=cart_mandate.merchant_id,
            created_at=datetime.utcnow().isoformat() + 'Z'
        )
        
        # ユーザーの署名を追加
        # 注: Payment Mandateはユーザーのみが署名します
        # Cart Mandateで既にマーチャントの同意は得られているため、
        # マーチャント署名は不要です
        user_signature_manager = SignatureManager(user_key_manager)
        payment_mandate.user_signature = user_signature_manager.sign_mandate(
            asdict(payment_mandate),
            user_id
        )

        print(f"  ✓ Payment Mandate作成完了: {payment_mandate.id}")
        print(f"  ✓ ユーザー署名追加")
        
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
            authorized_at=datetime.utcnow().isoformat() + 'Z',
            captured_at=datetime.utcnow().isoformat() + 'Z',
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
