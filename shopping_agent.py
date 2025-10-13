"""
AP2 Protocol - Shopping Agent実装サンプル
ユーザーの購買意図を受け取り、商品を検索し、決済プロセスを管理するエージェント
"""

import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import json
from dataclasses import asdict

from ap2_types import (
    IntentMandate,
    IntentConstraints,
    CartMandate,
    PaymentMandate,
    Amount,
    AgentIdentity,
    AgentType,
    A2AMessage,
    TaskRequest,
    TaskResponse,
    Signature,
    CardPaymentMethod,
    TransactionResult,
    TransactionStatus
)


class ShoppingAgent:
    """
    Shopping Agent
    ユーザーの代理として商品検索、カート作成、決済を行うエージェント
    """
    
    def __init__(self, agent_id: str, agent_name: str):
        self.identity = AgentIdentity(
            id=agent_id,
            name=agent_name,
            type=AgentType.SHOPPING,
            public_key="shopping_agent_public_key_placeholder"
        )
        self.current_session: Optional[Dict[str, Any]] = None
        
    def create_intent_mandate(
        self,
        user_id: str,
        user_public_key: str,
        intent: str,
        max_amount: Amount,
        valid_hours: int = 24,
        categories: Optional[List[str]] = None,
        brands: Optional[List[str]] = None
    ) -> IntentMandate:
        """
        Intent Mandateを作成
        
        Args:
            user_id: ユーザーID
            user_public_key: ユーザーの公開鍵
            intent: 購買意図（自然言語）
            max_amount: 最大金額
            valid_hours: 有効期間（時間）
            categories: 許可されたカテゴリー
            brands: 許可されたブランド
            
        Returns:
            IntentMandate: 作成されたIntent Mandate
        """
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
        
        intent_mandate = IntentMandate(
            id=f"intent_{uuid.uuid4().hex}",
            type='IntentMandate',
            version='0.1',
            user_id=user_id,
            user_public_key=user_public_key,
            intent=intent,
            constraints=constraints,
            created_at=now.isoformat() + 'Z',
            expires_at=expires_at.isoformat() + 'Z'
        )
        
        # 実際にはユーザーがこれに署名する
        # ここではプレースホルダーとして署名を追加
        intent_mandate.user_signature = self._create_placeholder_signature(
            user_public_key,
            "user signature placeholder"
        )
        
        return intent_mandate
    
    def _create_placeholder_signature(
        self,
        public_key: str,
        value: str
    ) -> Signature:
        """プレースホルダーの署名を作成（実際にはクライアント側で署名）"""
        return Signature(
            algorithm='ECDSA',
            value=value,
            public_key=public_key,
            signed_at=datetime.utcnow().isoformat() + 'Z'
        )
    
    async def search_products(
        self,
        intent_mandate: IntentMandate,
        merchant_agent_id: str
    ) -> TaskResponse:
        """
        商品を検索（Merchant Agentに委譲）
        
        Args:
            intent_mandate: Intent Mandate
            merchant_agent_id: Merchant AgentのID
            
        Returns:
            TaskResponse: 検索結果（Cart Mandatesを含む）
        """
        # Merchant Agentにリクエストを送信
        task_request = TaskRequest(
            task_id=f"task_{uuid.uuid4().hex}",
            intent=intent_mandate.intent,
            intent_mandate=intent_mandate,
            context={
                "max_amount": asdict(intent_mandate.constraints.max_amount),
                "categories": intent_mandate.constraints.categories,
                "brands": intent_mandate.constraints.brands
            }
        )
        
        # A2Aメッセージとして送信
        message = A2AMessage(
            id=f"msg_{uuid.uuid4().hex}",
            type="search_products_request",
            from_agent=self.identity,
            to_agent=AgentIdentity(
                id=merchant_agent_id,
                name="Merchant Agent",
                type=AgentType.MERCHANT,
                public_key="merchant_public_key_placeholder"
            ),
            timestamp=datetime.utcnow().isoformat() + 'Z',
            payload=asdict(task_request)
        )
        
        # 実際にはここで非同期通信を行う
        # このサンプルでは簡略化のためダミーのレスポンスを返す
        print(f"[{self.identity.name}] 商品検索リクエストを送信: {intent_mandate.intent}")
        print(f"  → Merchant Agent: {merchant_agent_id}")
        
        # ダミーレスポンス（実際にはMerchant Agentから返される）
        return TaskResponse(
            task_id=task_request.task_id,
            status='completed',
            cart_mandates=[],  # 実際にはCart Mandatesが入る
            result={"message": "Products found"}
        )
    
    async def select_cart(
        self,
        cart_mandate: CartMandate,
        user_id: str,
        user_public_key: str
    ) -> CartMandate:
        """
        カートを選択し、ユーザーの署名を追加
        
        Args:
            cart_mandate: Cart Mandate
            user_id: ユーザーID
            user_public_key: ユーザーの公開鍵
            
        Returns:
            CartMandate: ユーザー署名付きCart Mandate
        """
        print(f"[{self.identity.name}] カートを選択:")
        print(f"  商品数: {len(cart_mandate.items)}")
        print(f"  合計金額: {cart_mandate.total}")
        
        # ユーザーがCart Mandateに署名（Human Presentの場合）
        cart_mandate.user_signature = self._create_placeholder_signature(
            user_public_key,
            "user cart approval signature"
        )
        
        return cart_mandate
    
    async def get_payment_methods(
        self,
        credentials_provider_agent_id: str,
        user_id: str
    ) -> List[CardPaymentMethod]:
        """
        利用可能な支払い方法を取得（Credentials Provider Agentから）
        
        Args:
            credentials_provider_agent_id: Credentials Provider AgentのID
            user_id: ユーザーID
            
        Returns:
            List[CardPaymentMethod]: 利用可能な支払い方法
        """
        print(f"[{self.identity.name}] 支払い方法を取得中...")
        
        # 実際にはCredentials Provider Agentと通信
        # ここではダミーの支払い方法を返す
        payment_methods = [
            CardPaymentMethod(
                type='card',
                token='tok_visa_1234',
                last4='4242',
                brand='visa',
                expiry_month=12,
                expiry_year=2026,
                holder_name='Test User'
            ),
            CardPaymentMethod(
                type='card',
                token='tok_mc_5678',
                last4='5555',
                brand='mastercard',
                expiry_month=6,
                expiry_year=2027,
                holder_name='Test User'
            )
        ]
        
        print(f"  → {len(payment_methods)}件の支払い方法を取得")
        return payment_methods
    
    async def create_payment_mandate(
        self,
        cart_mandate: CartMandate,
        intent_mandate: IntentMandate,
        payment_method: CardPaymentMethod,
        user_id: str,
        user_public_key: str
    ) -> PaymentMandate:
        """
        Payment Mandateを作成
        
        Args:
            cart_mandate: Cart Mandate
            intent_mandate: Intent Mandate
            payment_method: 選択された支払い方法
            user_id: ユーザーID
            user_public_key: ユーザーの公開鍵
            
        Returns:
            PaymentMandate: 作成されたPayment Mandate
        """
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
        
        # ユーザーとマーチャントの署名を追加
        payment_mandate.user_signature = self._create_placeholder_signature(
            user_public_key,
            "user payment approval signature"
        )
        payment_mandate.merchant_signature = cart_mandate.merchant_signature
        
        print(f"[{self.identity.name}] Payment Mandateを作成: {payment_mandate.id}")
        
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
            otp: ワンタイムパスワード（必要な場合）
            
        Returns:
            TransactionResult: トランザクション結果
        """
        print(f"[{self.identity.name}] 支払いを処理中...")
        print(f"  金額: {payment_mandate.amount}")
        print(f"  支払い方法: {payment_mandate.payment_method.type}")
        
        # 実際にはPayment Processorと通信
        # ここではダミーの成功レスポンスを返す
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

async def main_example():
    """Shopping Agentの使用例"""
    
    # Shopping Agentを初期化
    shopping_agent = ShoppingAgent(
        agent_id="shopping_agent_001",
        agent_name="My Shopping Assistant"
    )
    
    # ユーザー情報
    user_id = "user_123"
    user_public_key = "user_public_key_placeholder"
    
    # 1. Intent Mandateを作成
    print("\n=== Step 1: Intent Mandateの作成 ===")
    intent_mandate = shopping_agent.create_intent_mandate(
        user_id=user_id,
        user_public_key=user_public_key,
        intent="新しいランニングシューズを100ドル以下で購入したい",
        max_amount=Amount(value="100.00", currency="USD"),
        categories=["shoes", "running"],
        brands=["Nike", "Adidas", "Asics"]
    )
    print(f"Intent Mandate作成: {intent_mandate.id}")
    print(f"意図: {intent_mandate.intent}")
    print(f"最大金額: {intent_mandate.constraints.max_amount}")
    
    # 2. 商品を検索
    print("\n=== Step 2: 商品検索 ===")
    search_result = await shopping_agent.search_products(
        intent_mandate=intent_mandate,
        merchant_agent_id="merchant_agent_001"
    )
    
    # 3. 支払い方法を取得
    print("\n=== Step 3: 支払い方法の取得 ===")
    payment_methods = await shopping_agent.get_payment_methods(
        credentials_provider_agent_id="credentials_provider_001",
        user_id=user_id
    )
    for i, pm in enumerate(payment_methods, 1):
        print(f"  {i}. {pm.brand.upper()} ****{pm.last4}")
    
    print("\n=== 完了 ===")
    print("AP2プロトコルの基本的なフローを実行しました!")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main_example())
