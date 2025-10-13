"""
AP2 Protocol - Merchant Agent（暗号署名機能統合版）
実際の暗号署名を使用したセキュアな実装
"""

import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from dataclasses import asdict
from decimal import Decimal, ROUND_HALF_UP

from ap2_types import (
    CartMandate,
    CartItem,
    IntentMandate,
    Amount,
    ShippingInfo,
    Address,
    AgentIdentity,
    AgentType,
    AP2ErrorCode,
    MandateError,
    AmountError,
    DEFAULT_AP2_VERSION,
    SUPPORTED_AP2_VERSIONS
)

from ap2_crypto import KeyManager, SignatureManager


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


class SecureMerchantAgent:
    """
    Merchant Agent（暗号署名統合版）
    実際の暗号署名を使用してCart Mandateを作成
    """
    
    def __init__(
        self,
        agent_id: str,
        merchant_name: str,
        merchant_id: str,
        passphrase: str
    ):
        """
        Args:
            agent_id: エージェントID
            merchant_name: マーチャント名
            merchant_id: マーチャントID
            passphrase: 秘密鍵の暗号化に使用するパスフレーズ
        """
        self.agent_id = agent_id
        self.merchant_name = merchant_name
        self.merchant_id = merchant_id
        
        # 鍵管理と署名管理の初期化
        self.key_manager = KeyManager()
        self.signature_manager = SignatureManager(self.key_manager)
        
        # エージェント自身の鍵ペアを生成
        self._initialize_agent_keys(passphrase)
        
        self.identity = AgentIdentity(
            id=agent_id,
            name=merchant_name,
            type=AgentType.MERCHANT,
            public_key=self.key_manager.public_key_to_base64(self.public_key)
        )
        
        # 商品カタログを初期化
        self.catalog = self._initialize_catalog()
        
        # デフォルトの配送情報
        self.default_shipping_cost = Amount(value="10.00", currency="USD")
        self.default_tax_rate = 0.08  # 8%
    
    def _initialize_agent_keys(self, passphrase: str):
        """エージェントの鍵ペアを初期化"""
        print(f"[{self.merchant_name}] 鍵ペアを初期化中...")
        
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
    
    def _initialize_catalog(self) -> List[Product]:
        """商品カタログを初期化"""
        return [
            Product(
                id="prod_001",
                name="むぎぼーステッカー",
                description="かわいいむぎぼーのステッカー。スマホやノートPCに貼れます！",
                price=Amount(value="5.99", currency="USD"),
                category="stationery",
                brand="むぎぼーオフィシャル",
                image_url="assets/むぎぼーステッカー.png",
                stock=100
            ),
            Product(
                id="prod_002",
                name="むぎぼーマグカップ",
                description="毎日の生活をむぎぼーと一緒に。耐熱性に優れた陶器製マグカップ。",
                price=Amount(value="18.99", currency="USD"),
                category="tableware",
                brand="むぎぼーオフィシャル",
                image_url="assets/むぎぼーマグカップ.png",
                stock=50
            ),
            Product(
                id="prod_003",
                name="むぎぼーカレンダー",
                description="2025年版むぎぼーカレンダー。毎月違うむぎぼーの表情を楽しめます。",
                price=Amount(value="24.99", currency="USD"),
                category="calendar",
                brand="むぎぼーオフィシャル",
                image_url="assets/むぎぼーカレンダー.png",
                stock=30
            ),
            Product(
                id="prod_004",
                name="むぎぼー時計",
                description="むぎぼーの可愛い壁掛け時計。お部屋のアクセントに最適。",
                price=Amount(value="35.99", currency="USD"),
                category="interior",
                brand="むぎぼーオフィシャル",
                image_url="assets/むぎぼー時計.png",
                stock=20
            ),
            Product(
                id="prod_005",
                name="むぎぼーアクリルキーホルダー",
                description="バッグや鍵につけられる、丈夫なアクリル製キーホルダー。",
                price=Amount(value="12.99", currency="USD"),
                category="accessories",
                brand="むぎぼーオフィシャル",
                image_url="assets/むぎぼーアクリルキーホルダー.png",
                stock=80
            ),
        ]
    
    def _verify_intent_mandate_expiration(self, intent_mandate: IntentMandate) -> None:
        """
        Intent Mandateの有効期限を検証

        Args:
            intent_mandate: 検証するIntent Mandate

        Raises:
            MandateError: 期限切れの場合
        """
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

        Raises:
            MandateError: Intent Mandateが期限切れの場合
        """
        print(f"\n[{self.merchant_name}] 商品検索を実行:")
        print(f"  意図: {intent_mandate.intent}")

        # Intent Mandateの有効期限を検証
        self._verify_intent_mandate_expiration(intent_mandate)
        print(f"  ✓ Intent Mandate有効期限OK")

        results = []
        constraints = intent_mandate.constraints

        for product in self.catalog:
            # カテゴリーチェック
            if constraints.categories and product.category not in constraints.categories:
                continue

            # ブランドチェック
            if constraints.brands and product.brand not in constraints.brands:
                continue

            # 価格チェック（Decimalを使用）
            if constraints.max_amount:
                product_price = product.price.to_decimal()
                max_price = constraints.max_amount.to_decimal()
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
    ) -> CartMandate:
        """
        Cart Mandateを作成（署名なし）

        複数商品を1つのCart Mandateにまとめます。

        注意: Merchant Agentは Cart Mandate を作成するのみで、
        署名は Merchant エンティティが別途行います。

        Args:
            intent_mandate: Intent Mandate
            products: 選択された商品リスト
            quantities: 商品ごとの数量 {product_id: quantity}
            shipping_address: 配送先住所

        Returns:
            CartMandate: 未署名のCart Mandate（複数商品を含む）
        """
        print(f"\n[Merchant Agent: {self.merchant_name}] Cart Mandateを作成中...")

        if not products:
            raise ValueError("商品が選択されていません")

        # Intent Mandateの有効期限を検証
        self._verify_intent_mandate_expiration(intent_mandate)

        # すべてのCart Itemを作成（Decimalで精度を保証）
        cart_items = []
        subtotal_value = Decimal("0.00")

        for product in products:
            quantity = quantities.get(product.id, 1) if quantities else 1

            if quantity <= 0:
                continue  # 数量が0以下の商品はスキップ

            # Cart Itemを作成（Decimalを使用）
            unit_price = product.price
            unit_price_decimal = unit_price.to_decimal()
            item_total_decimal = unit_price_decimal * Decimal(quantity)

            # Decimal を ROUND_HALF_UP で2桁に丸める
            item_total_decimal = item_total_decimal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            total_price = Amount.from_decimal(item_total_decimal, unit_price.currency)

            cart_item = CartItem(
                id=product.id,
                name=product.name,
                description=product.description,
                quantity=quantity,
                unit_price=unit_price,
                total_price=total_price,
                image_url=product.image_url
            )

            cart_items.append(cart_item)
            subtotal_value += item_total_decimal

            print(f"  ✓ 商品追加: {cart_item.name} x {quantity} = ${item_total_decimal}")

        if not cart_items:
            raise ValueError("有効な商品がありません")

        # 金額計算（Decimalで精度を保証）
        subtotal = Amount.from_decimal(subtotal_value, "USD")

        # 税額計算（Decimal）
        tax_rate_decimal = Decimal(str(self.default_tax_rate))
        tax_amount_decimal = (subtotal_value * tax_rate_decimal).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        tax = Amount.from_decimal(tax_amount_decimal, "USD")

        # 配送情報
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

        # 合計金額（Decimalで精度を保証）
        shipping_cost_decimal = self.default_shipping_cost.to_decimal()
        total_value_decimal = subtotal_value + tax_amount_decimal + shipping_cost_decimal
        total = Amount.from_decimal(total_value_decimal, "USD")

        # Cart Mandateを作成（署名なし）
        now = datetime.utcnow()
        expires_at = now + timedelta(hours=1)

        cart_mandate = CartMandate(
            id=f"cart_{uuid.uuid4().hex}",
            type='CartMandate',
            version='0.1',
            intent_mandate_id=intent_mandate.id,
            items=cart_items,  # 複数のアイテムを含む
            subtotal=subtotal,
            tax=tax,
            shipping=shipping_info,
            total=total,
            merchant_id=self.merchant_id,
            merchant_name=self.merchant_name,
            created_at=now.isoformat() + 'Z',
            expires_at=expires_at.isoformat() + 'Z'
        )

        print(f"\n  ✓ Cart Mandate作成完了: {cart_mandate.id}")
        print(f"    商品数: {len(cart_items)}点")
        print(f"    小計: ${subtotal_value:.2f}")
        print(f"    税金: ${tax_amount_decimal:.2f}")
        print(f"    配送料: ${shipping_cost_decimal:.2f}")
        print(f"    合計: ${total_value_decimal:.2f}")
        print(f"    ※ Merchant署名は Merchant エンティティが追加します")

        return cart_mandate
    
    def _verify_cart_mandate_signature(self, cart_mandate: CartMandate) -> bool:
        """Cart Mandateの署名を検証"""
        if not cart_mandate.merchant_signature:
            print(f"  ✗ Merchant署名がありません")
            return False
        
        cart_dict = asdict(cart_mandate)
        is_valid = self.signature_manager.verify_mandate_signature(
            cart_dict,
            cart_mandate.merchant_signature
        )
        
        if is_valid:
            print(f"  ✓ Merchant署名は有効です")
        else:
            print(f"  ✗ Merchant署名が無効です")
        
        return is_valid
    
    def verify_complete_cart_mandate(self, cart_mandate: CartMandate) -> bool:
        """
        Cart Mandate全体の検証（署名、金額、有効期限など）
        
        Args:
            cart_mandate: 検証するCart Mandate
            
        Returns:
            bool: 検証結果
        """
        print(f"\n[{self.merchant_name}] Cart Mandateを検証中: {cart_mandate.id}")
        
        # 1. 有効期限チェック
        expires_at = datetime.fromisoformat(cart_mandate.expires_at.replace('Z', '+00:00'))
        now = datetime.now(expires_at.tzinfo)
        
        if now > expires_at:
            print(f"  ✗ Cart Mandateは期限切れです")
            return False
        
        print(f"  ✓ 有効期限OK")
        
        # 2. Merchant署名チェック
        if not self._verify_cart_mandate_signature(cart_mandate):
            return False
        
        # 3. User署名チェック（存在する場合）
        if cart_mandate.user_signature:
            cart_dict = asdict(cart_mandate)
            is_user_valid = self.signature_manager.verify_mandate_signature(
                cart_dict,
                cart_mandate.user_signature
            )
            
            if not is_user_valid:
                print(f"  ✗ User署名が無効です")
                return False
            
            print(f"  ✓ User署名は有効です")
        
        # 4. 金額の整合性チェック（Decimalで精度を保証）
        calculated_subtotal = sum(
            item.total_price.to_decimal() for item in cart_mandate.items
        )
        expected_subtotal = cart_mandate.subtotal.to_decimal()

        if abs(calculated_subtotal - expected_subtotal) > Decimal("0.01"):
            print(f"  ✗ 小計の計算が一致しません")
            print(f"    計算値: {calculated_subtotal}, 期待値: {expected_subtotal}")
            return False

        calculated_total = (
            cart_mandate.subtotal.to_decimal() +
            cart_mandate.tax.to_decimal() +
            cart_mandate.shipping.cost.to_decimal()
        )
        expected_total = cart_mandate.total.to_decimal()

        if abs(calculated_total - expected_total) > Decimal("0.01"):
            print(f"  ✗ 合計金額の計算が一致しません")
            print(f"    計算値: {calculated_total}, 期待値: {expected_total}")
            return False
        
        print(f"  ✓ 金額の整合性OK")
        
        print(f"  ✓✓✓ Cart Mandate検証成功 ✓✓✓")
        return True


# ========================================
# 使用例
# ========================================

async def demo_secure_merchant():
    """セキュアなMerchant Agentのデモ"""
    
    print("=" * 80)
    print("AP2 Protocol - セキュアなMerchant Agentのデモ")
    print("=" * 80)
    
    # Merchant Agentを初期化
    merchant_agent = SecureMerchantAgent(
        agent_id="merchant_agent_001",
        merchant_name="Secure Running Shoes Store",
        merchant_id="merchant_123",
        passphrase="merchant_secure_passphrase"
    )
    
    # ダミーのIntent Mandateを作成
    from ap2_types import IntentConstraints
    
    print("\n" + "=" * 80)
    print("ステップ1: Intent Mandateの準備（ダミー）")
    print("=" * 80)
    
    intent_mandate = IntentMandate(
        id="intent_test_001",
        type='IntentMandate',
        version='0.1',
        user_id="user_123",
        user_public_key="user_public_key_placeholder",
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
    print("\n" + "=" * 80)
    print("ステップ2: 商品検索")
    print("=" * 80)
    
    products = merchant_agent.search_products(intent_mandate)
    
    # Cart Mandateを作成（署名なし）
    print("\n" + "=" * 80)
    print("ステップ3: Cart Mandateの作成")
    print("=" * 80)

    cart_mandates = merchant_agent.create_cart_mandate(
        intent_mandate=intent_mandate,
        products=products[:2]  # 最初の2商品
    )

    print("\n  ※ 注意: AP2プロトコルに準拠した実装では、")
    print("    Merchant署名は別途 Merchant エンティティが追加します。")
    
    print("\n" + "=" * 80)
    print("デモンストレーション完了!")
    print("=" * 80)


if __name__ == "__main__":
    import asyncio
    asyncio.run(demo_secure_merchant())
