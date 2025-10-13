"""
AP2 Protocol - Merchant Agent実装サンプル
商品カタログを管理し、Cart Mandateを作成するエージェント
"""

import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from dataclasses import asdict

from ap2_types import (
    CartMandate,
    CartItem,
    IntentMandate,
    Amount,
    ShippingInfo,
    Address,
    AgentIdentity,
    AgentType,
    Signature,
    A2AMessage,
    TaskRequest,
    TaskResponse
)


class Product:
    """商品モデル"""
    
    def __init__(
        self,
        id: str,
        name: str,
        description: str,
        price: Amount,
        category: str,
        brand: str,
        image_url: Optional[str] = None,
        stock: int = 100
    ):
        self.id = id
        self.name = name
        self.description = description
        self.price = price
        self.category = category
        self.brand = brand
        self.image_url = image_url
        self.stock = stock


class MerchantAgent:
    """
    Merchant Agent
    商品カタログを管理し、Shopping Agentからのリクエストに応答する
    """
    
    def __init__(
        self,
        agent_id: str,
        merchant_name: str,
        merchant_id: str
    ):
        self.identity = AgentIdentity(
            id=agent_id,
            name=merchant_name,
            type=AgentType.MERCHANT,
            public_key="merchant_agent_public_key_placeholder"
        )
        self.merchant_id = merchant_id
        self.merchant_name = merchant_name
        
        # 商品カタログを初期化
        self.catalog = self._initialize_catalog()
        
        # デフォルトの配送情報
        self.default_shipping_cost = Amount(value="10.00", currency="USD")
        self.default_tax_rate = 0.08  # 8%
    
    def _initialize_catalog(self) -> List[Product]:
        """商品カタログを初期化"""
        return [
            Product(
                id="prod_001",
                name="Nike Air Zoom Pegasus 40",
                description="軽量で快適なランニングシューズ。クッション性に優れています。",
                price=Amount(value="89.99", currency="USD"),
                category="running",
                brand="Nike",
                image_url="https://example.com/images/nike-pegasus.jpg"
            ),
            Product(
                id="prod_002",
                name="Adidas Ultraboost 22",
                description="エネルギーリターンに優れた、人気のランニングシューズ。",
                price=Amount(value="95.00", currency="USD"),
                category="running",
                brand="Adidas",
                image_url="https://example.com/images/adidas-ultraboost.jpg"
            ),
            Product(
                id="prod_003",
                name="Asics Gel-Nimbus 25",
                description="長距離ランに最適。優れたクッション性と安定性。",
                price=Amount(value="99.00", currency="USD"),
                category="running",
                brand="Asics",
                image_url="https://example.com/images/asics-nimbus.jpg"
            ),
            Product(
                id="prod_004",
                name="Nike ZoomX Vaporfly Next% 2",
                description="レーシングシューズの最高峰。記録更新を目指すランナーに。",
                price=Amount(value="150.00", currency="USD"),
                category="running",
                brand="Nike",
                image_url="https://example.com/images/nike-vaporfly.jpg"
            ),
            Product(
                id="prod_005",
                name="Adidas Solarboost 4",
                description="快適なロングラン向けシューズ。通気性に優れています。",
                price=Amount(value="79.99", currency="USD"),
                category="running",
                brand="Adidas",
                image_url="https://example.com/images/adidas-solarboost.jpg"
            ),
        ]
    
    def search_products(
        self,
        intent_mandate: IntentMandate,
        query: Optional[str] = None
    ) -> List[Product]:
        """
        Intent Mandateの制約に基づいて商品を検索
        
        Args:
            intent_mandate: Intent Mandate
            query: 検索クエリ（オプション）
            
        Returns:
            List[Product]: マッチした商品のリスト
        """
        print(f"[{self.identity.name}] 商品検索を実行:")
        print(f"  意図: {intent_mandate.intent}")
        
        results = []
        constraints = intent_mandate.constraints
        
        for product in self.catalog:
            # カテゴリーチェック
            if constraints.categories and product.category not in constraints.categories:
                continue
            
            # ブランドチェック
            if constraints.brands and product.brand not in constraints.brands:
                continue
            
            # 価格チェック
            if constraints.max_amount:
                product_price = float(product.price.value)
                max_price = float(constraints.max_amount.value)
                if product_price > max_price:
                    continue
            
            results.append(product)
        
        print(f"  → {len(results)}件の商品が見つかりました")
        return results
    
    def create_cart_mandate(
        self,
        intent_mandate: IntentMandate,
        products: List[Product],
        quantities: Optional[Dict[str, int]] = None,
        shipping_address: Optional[Address] = None
    ) -> List[CartMandate]:
        """
        Cart Mandateを作成
        
        Args:
            intent_mandate: Intent Mandate
            products: 選択された商品
            quantities: 商品ごとの数量（デフォルトは1）
            shipping_address: 配送先住所
            
        Returns:
            List[CartMandate]: 作成されたCart Mandateのリスト
        """
        cart_mandates = []
        
        # 各商品に対してCart Mandateを作成（または1つのカートにまとめる）
        for product in products:
            quantity = quantities.get(product.id, 1) if quantities else 1
            
            # Cart Itemを作成
            unit_price = product.price
            total_price = Amount(
                value=str(float(unit_price.value) * quantity),
                currency=unit_price.currency
            )
            
            cart_item = CartItem(
                id=product.id,
                name=product.name,
                description=product.description,
                quantity=quantity,
                unit_price=unit_price,
                total_price=total_price,
                image_url=product.image_url
            )
            
            # 小計を計算
            subtotal = total_price
            
            # 税金を計算
            tax_amount = float(subtotal.value) * self.default_tax_rate
            tax = Amount(
                value=f"{tax_amount:.2f}",
                currency=subtotal.currency
            )
            
            # 配送情報を設定
            shipping_info = ShippingInfo(
                address=shipping_address or Address(
                    street="123 Main St",
                    city="San Francisco",
                    state="CA",
                    postal_code="94105",
                    country="US"
                ),
                method="Standard Shipping",
                cost=self.default_shipping_cost,
                estimated_delivery=(datetime.utcnow() + timedelta(days=5)).isoformat() + 'Z'
            )
            
            # 合計金額を計算
            total_value = (
                float(subtotal.value) +
                float(tax.value) +
                float(shipping_info.cost.value)
            )
            total = Amount(
                value=f"{total_value:.2f}",
                currency=subtotal.currency
            )
            
            # Cart Mandateを作成
            now = datetime.utcnow()
            expires_at = now + timedelta(hours=1)  # 1時間有効
            
            cart_mandate = CartMandate(
                id=f"cart_{uuid.uuid4().hex}",
                type='CartMandate',
                version='0.1',
                intent_mandate_id=intent_mandate.id,
                items=[cart_item],
                subtotal=subtotal,
                tax=tax,
                shipping=shipping_info,
                total=total,
                merchant_id=self.merchant_id,
                merchant_name=self.merchant_name,
                created_at=now.isoformat() + 'Z',
                expires_at=expires_at.isoformat() + 'Z'
            )
            
            # Merchant署名を追加
            cart_mandate.merchant_signature = self._create_merchant_signature(cart_mandate)
            
            cart_mandates.append(cart_mandate)
            
            print(f"[{self.identity.name}] Cart Mandate作成:")
            print(f"  ID: {cart_mandate.id}")
            print(f"  商品: {cart_item.name}")
            print(f"  数量: {cart_item.quantity}")
            print(f"  合計: {cart_mandate.total}")
        
        return cart_mandates
    
    def _create_merchant_signature(self, cart_mandate: CartMandate) -> Signature:
        """Merchantの署名を作成"""
        # 実際には、Cart MandateのハッシュにMerchantの秘密鍵で署名
        # ここではプレースホルダーとして返す
        return Signature(
            algorithm='ECDSA',
            value="merchant_signature_placeholder",
            public_key=self.identity.public_key,
            signed_at=datetime.utcnow().isoformat() + 'Z'
        )
    
    async def handle_search_request(
        self,
        message: A2AMessage
    ) -> TaskResponse:
        """
        Shopping Agentからの検索リクエストを処理
        
        Args:
            message: A2Aメッセージ
            
        Returns:
            TaskResponse: 検索結果
        """
        task_request: TaskRequest = message.payload
        intent_mandate = task_request.intent_mandate
        
        if not intent_mandate:
            return TaskResponse(
                task_id=task_request.task_id,
                status='failed',
                error="Intent Mandate is required"
            )
        
        # 商品を検索
        products = self.search_products(intent_mandate)
        
        # Cart Mandateを作成
        cart_mandates = self.create_cart_mandate(intent_mandate, products)
        
        return TaskResponse(
            task_id=task_request.task_id,
            status='completed',
            cart_mandates=cart_mandates,
            result={
                "products_found": len(products),
                "carts_created": len(cart_mandates)
            }
        )
    
    def verify_cart_mandate(self, cart_mandate: CartMandate) -> bool:
        """
        Cart Mandateを検証
        
        Args:
            cart_mandate: 検証するCart Mandate
            
        Returns:
            bool: 検証結果
        """
        # 有効期限チェック
        expires_at = datetime.fromisoformat(cart_mandate.expires_at.replace('Z', '+00:00'))
        if datetime.now(expires_at.tzinfo) > expires_at:
            print(f"[{self.identity.name}] ❌ Cart Mandateは期限切れです")
            return False
        
        # 署名チェック（実際には暗号検証を行う）
        if not cart_mandate.merchant_signature:
            print(f"[{self.identity.name}] ❌ Merchant署名がありません")
            return False
        
        if not cart_mandate.user_signature:
            print(f"[{self.identity.name}] ❌ User署名がありません")
            return False
        
        # 金額の整合性チェック
        calculated_total = sum(
            float(item.total_price.value) for item in cart_mandate.items
        )
        calculated_total += float(cart_mandate.tax.value)
        calculated_total += float(cart_mandate.shipping.cost.value)
        
        actual_total = float(cart_mandate.total.value)
        
        if abs(calculated_total - actual_total) > 0.01:
            print(f"[{self.identity.name}] ❌ 金額の整合性エラー")
            return False
        
        print(f"[{self.identity.name}] ✓ Cart Mandate検証成功")
        return True


# ========================================
# 使用例
# ========================================

async def main_example():
    """Merchant Agentの使用例"""
    
    # Merchant Agentを初期化
    merchant_agent = MerchantAgent(
        agent_id="merchant_agent_001",
        merchant_name="Running Shoes Store",
        merchant_id="merchant_123"
    )
    
    # ダミーのIntent Mandateを作成
    from ap2_types import IntentConstraints
    
    intent_mandate = IntentMandate(
        id="intent_test_001",
        type='IntentMandate',
        version='0.1',
        user_id="user_123",
        user_public_key="user_public_key",
        intent="新しいランニングシューズを100ドル以下で購入したい",
        constraints=IntentConstraints(
            max_amount=Amount(value="100.00", currency="USD"),
            categories=["running"],
            brands=["Nike", "Adidas"],
            valid_until=(datetime.utcnow() + timedelta(hours=24)).isoformat() + 'Z'
        ),
        created_at=datetime.utcnow().isoformat() + 'Z',
        expires_at=(datetime.utcnow() + timedelta(hours=24)).isoformat() + 'Z'
    )
    
    # 商品を検索
    print("\n=== Step 1: 商品検索 ===")
    products = merchant_agent.search_products(intent_mandate)
    
    print("\n検索結果:")
    for i, product in enumerate(products, 1):
        print(f"{i}. {product.name} ({product.brand})")
        print(f"   価格: {product.price}")
        print(f"   説明: {product.description}")
        print()
    
    # Cart Mandateを作成
    print("\n=== Step 2: Cart Mandate作成 ===")
    cart_mandates = merchant_agent.create_cart_mandate(
        intent_mandate=intent_mandate,
        products=products[:2]  # 最初の2商品をカートに追加
    )
    
    print(f"\n{len(cart_mandates)}個のCart Mandateを作成しました")
    
    # 最初のCart Mandateを表示
    if cart_mandates:
        cart = cart_mandates[0]
        print(f"\nCart Mandate詳細:")
        print(f"  ID: {cart.id}")
        print(f"  商品数: {len(cart.items)}")
        print(f"  小計: {cart.subtotal}")
        print(f"  税金: {cart.tax}")
        print(f"  配送料: {cart.shipping.cost}")
        print(f"  合計: {cart.total}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main_example())
