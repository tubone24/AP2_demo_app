"""
AP2 Protocol - Merchant
実際の販売者（店舗）を表現するクラス
Merchant Agentとは別のエンティティとして、Cart Mandateを検証・署名する
"""

from ap2_crypto import KeyManager, SignatureManager, compute_mandate_hash
from ap2_types import CartMandate, MandateMetadata
import uuid
from datetime import datetime, timezone


class Merchant:
    """
    Merchant (販売者)

    AP2プロトコルにおいて、実際の商品/サービスを提供する販売者。
    Merchant Agentによって作成されたCart Mandateを検証し、署名する。

    役割:
    - Cart Mandateの検証
    - 商品在庫の確認
    - Merchant署名の追加
    - 注文の確定
    """

    def __init__(self, merchant_id: str, merchant_name: str, passphrase: str):
        """
        Merchantを初期化

        Args:
            merchant_id: 販売者ID
            merchant_name: 販売者名
            passphrase: 秘密鍵を保護するパスフレーズ
        """
        self.merchant_id = merchant_id
        self.merchant_name = merchant_name

        # 鍵管理
        self.key_manager = KeyManager()
        try:
            self.private_key = self.key_manager.load_private_key_encrypted(
                merchant_id,
                passphrase
            )
            self.public_key = self.private_key.public_key()
        except:
            self.private_key, self.public_key = self.key_manager.generate_key_pair(merchant_id)
            self.key_manager.save_private_key_encrypted(merchant_id, self.private_key, passphrase)
            self.key_manager.save_public_key(merchant_id, self.public_key)

        self.signature_manager = SignatureManager(self.key_manager)

        # 在庫管理（商品ID -> 在庫数）
        self.inventory: Dict[str, int] = {}

        print(f"[Merchant] 初期化完了: {merchant_name} (ID: {merchant_id})")

    def register_inventory(self, product_id: str, quantity: int) -> None:
        """
        商品の在庫を登録・更新

        Args:
            product_id: 商品ID
            quantity: 在庫数
        """
        self.inventory[product_id] = quantity
        print(f"[Merchant] 在庫登録: {product_id} = {quantity}")

    def get_inventory(self, product_id: str) -> int:
        """
        商品の在庫数を取得

        Args:
            product_id: 商品ID

        Returns:
            在庫数（登録されていない場合は0）
        """
        return self.inventory.get(product_id, 0)

    def reserve_inventory(self, product_id: str, quantity: int) -> bool:
        """
        在庫を予約（減らす）

        Args:
            product_id: 商品ID
            quantity: 予約数

        Returns:
            予約が成功したかどうか
        """
        current_stock = self.get_inventory(product_id)
        if current_stock < quantity:
            print(f"[Merchant] 在庫不足: {product_id}（在庫: {current_stock}, 要求: {quantity}）")
            return False

        self.inventory[product_id] = current_stock - quantity
        print(f"[Merchant] 在庫予約: {product_id} x {quantity}（残り: {self.inventory[product_id]}）")
        return True

    def validate_cart_mandate(self, cart_mandate: CartMandate) -> bool:
        """
        Cart Mandateを検証

        Args:
            cart_mandate: 検証するCart Mandate

        Returns:
            検証が成功したかどうか
        """
        print(f"[Merchant] Cart Mandateを検証中: {cart_mandate.id}")

        # 1. 販売者IDが一致するか確認
        if cart_mandate.merchant_id != self.merchant_id:
            print(f"[Merchant] エラー: 販売者IDが一致しません")
            return False

        # 2. 商品の在庫を確認
        for item in cart_mandate.items:
            stock = self.get_inventory(item.id)
            print(f"[Merchant]   商品確認: {item.name} x {item.quantity} (在庫: {stock})")

            if stock < item.quantity:
                print(f"[Merchant] エラー: 在庫不足 - {item.name}（在庫: {stock}, 要求: {item.quantity}）")
                return False

        # 3. 金額の整合性を確認
        # （実際のシステムでは、小計、税金、送料、合計を再計算して検証）

        print(f"[Merchant] 検証完了: Cart Mandateは有効です")
        return True

    def sign_cart_mandate(self, cart_mandate: CartMandate) -> CartMandate:
        """
        Cart MandateにMerchant署名を追加

        Args:
            cart_mandate: 署名するCart Mandate

        Returns:
            署名されたCart Mandate
        """
        from dataclasses import asdict

        # Cart Mandateを検証
        if not self.validate_cart_mandate(cart_mandate):
            raise ValueError("Cart Mandateの検証に失敗しました")

        # 在庫を予約（減らす）
        print(f"[Merchant] 在庫を予約中...")
        for item in cart_mandate.items:
            current_stock = self.get_inventory(item.id)
            if current_stock < item.quantity:
                raise ValueError(
                    f"在庫不足: {item.name}\n"
                    f"要求数量: {item.quantity}個\n"
                    f"現在の在庫: {current_stock}個\n"
                    f"不足数: {item.quantity - current_stock}個"
                )
            if not self.reserve_inventory(item.id, item.quantity):
                raise ValueError(f"在庫予約に失敗しました: {item.name}")

        # Merchant署名を作成
        print(f"[Merchant] Cart MandateにMerchant署名を追加中...")

        # Cart Mandate全体を辞書に変換して署名
        # sign_mandateメソッドが自動的にsignatureフィールドを除外してくれる
        cart_dict = asdict(cart_mandate)
        signature = self.signature_manager.sign_mandate(
            cart_dict,
            self.merchant_id
        )

        # Cart MandateにMerchant署名を追加
        cart_mandate.merchant_signature = signature

        # A2A Extension: Mandate Hashを計算してMandate Metadataを追加
        cart_dict_signed = asdict(cart_mandate)
        cart_mandate_hash = compute_mandate_hash(cart_dict_signed, hash_format='hex')

        now = datetime.now(timezone.utc)

        # 署名チェーン（audit_trail）を作成
        # Merchant署名を記録
        audit_trail = [
            {
                "action": "merchant_signature",
                "signer_id": self.merchant_id,
                "signed_at": signature.signed_at,
                "signature_algorithm": signature.algorithm,
                "mandate_type": "CartMandate"
            }
        ]

        cart_mandate.mandate_metadata = MandateMetadata(
            mandate_hash=cart_mandate_hash,
            schema_version='0.1',
            issuer=self.merchant_id,
            issued_at=now.isoformat().replace('+00:00', 'Z'),
            previous_mandate_hash=cart_mandate.intent_mandate_hash,  # IntentMandateから連鎖
            nonce=uuid.uuid4().hex,
            audit_trail=audit_trail  # 署名チェーンの証跡
        )

        print(f"[Merchant] Merchant署名を追加完了")
        print(f"[Merchant] Mandate Hash: {cart_mandate_hash[:16]}...")
        print(f"[Merchant] 注文確定: {cart_mandate.id}")

        return cart_mandate

    def verify_merchant_signature(self, cart_mandate: CartMandate) -> bool:
        """
        Cart MandateのMerchant署名を検証

        Args:
            cart_mandate: 検証するCart Mandate

        Returns:
            署名が有効かどうか
        """
        from dataclasses import asdict

        if not cart_mandate.merchant_signature:
            return False

        # Cart Mandate全体を辞書に変換して検証
        # verify_mandate_signatureメソッドが自動的にsignatureフィールドを除外してくれる
        cart_dict = asdict(cart_mandate)
        return self.signature_manager.verify_mandate_signature(
            cart_dict,
            cart_mandate.merchant_signature
        )


def demo_merchant():
    """Merchantのデモ"""
    from secure_merchant_agent import SecureMerchantAgent
    from ap2_types import IntentMandate, IntentConstraints, Amount
    from datetime import datetime, timedelta

    print("=== Merchant Demo ===\n")

    # Merchant Agentを初期化
    merchant_agent = SecureMerchantAgent(
        agent_id="merchant_agent_demo",
        merchant_name="Demo Running Shoes Store",
        merchant_id="merchant_demo_001",
        passphrase="merchant_agent_pass"
    )

    # Merchantを初期化（別エンティティ）
    merchant = Merchant(
        merchant_id="merchant_demo_001",
        merchant_name="Demo Running Shoes Store",
        passphrase="merchant_secure_pass"
    )

    # Intent Mandateを作成（簡易版）
    intent_mandate = IntentMandate(
        id="intent_001",
        type="IntentMandate",
        version="1.0",
        user_id="user_demo_001",
        user_public_key="dummy_public_key",
        intent="ランニングシューズを購入したい",
        constraints=IntentConstraints(
            valid_until=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
            max_amount=Amount(value="100.00", currency="USD"),
            brands=["Nike", "Adidas"]
        ),
        created_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    )

    # 商品を検索
    products = merchant_agent.search_products(intent_mandate)

    # Cart Mandateを作成（Merchant Agent）
    from ap2_types import Address
    shipping_address = Address(
        street="123 Main Street",
        city="San Francisco",
        state="CA",
        postal_code="94105",
        country="US"
    )

    cart_mandates = merchant_agent.create_cart_mandate(
        intent_mandate=intent_mandate,
        products=[products[0]],
        shipping_address=shipping_address
    )

    cart_mandate = cart_mandates[0]

    print("\n--- Merchant AgentがCart Mandateを作成 ---")
    print(f"Cart Mandate ID: {cart_mandate.id}")
    print(f"Merchant署名: {'あり' if cart_mandate.merchant_signature else 'なし'}")

    # MerchantがCart Mandateに署名（新しいフロー）
    print("\n--- MerchantがCart Mandateに署名 ---")
    signed_cart = merchant.sign_cart_mandate(cart_mandate)

    print(f"\nMerchant署名: {'あり' if signed_cart.merchant_signature else 'なし'}")
    print(f"署名検証: {merchant.verify_merchant_signature(signed_cart)}")


if __name__ == "__main__":
    demo_merchant()