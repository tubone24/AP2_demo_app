"""
AP2 Protocol - 統一Verifier
AP2プロトコルのすべての検証ロジックを一元管理
"""

from datetime import datetime
from typing import Optional, Dict, List
from pathlib import Path
import json

from ap2_types import (
    IntentMandate,
    CartMandate,
    PaymentMandate,
    TransactionResult,
    Amount,
    AP2ErrorCode,
    MandateError,
    AmountError,
    SignatureError
)
from ap2_crypto import SignatureManager, KeyManager
from verifier_registry import VerifierPublicKeyRegistry


class AP2Verifier:
    """
    AP2プロトコルの統一Verifier

    すべてのMandate検証ロジックを一元管理し、
    AP2仕様に準拠した完全な検証を実施する。

    検証項目:
    - Intent Mandate: 署名、有効期限、制約条件
    - Cart Mandate: 署名（Merchant + User）、金額整合性、Intent制約
    - Payment Mandate: 署名、有効期限、金額一致、max_transactions
    """

    def __init__(
        self,
        public_key_registry: Optional[VerifierPublicKeyRegistry] = None,
        transaction_history_file: str = "./verifier_transaction_history.json"
    ):
        """
        Verifierを初期化

        Args:
            public_key_registry: 信頼された公開鍵のレジストリ
            transaction_history_file: トランザクション履歴ファイルのパス
        """
        self.registry = public_key_registry or VerifierPublicKeyRegistry()
        self.key_manager = KeyManager()
        self.signature_manager = SignatureManager(self.key_manager)

        # トランザクション履歴（max_transactions チェック用）
        self.history_file = Path(transaction_history_file)
        self.transaction_history: Dict[str, List[str]] = self._load_transaction_history()

    def _load_transaction_history(self) -> Dict[str, List[str]]:
        """トランザクション履歴を読み込む"""
        if self.history_file.exists():
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data
            except Exception as e:
                print(f"[AP2Verifier] 履歴ファイルの読み込みに失敗: {e}")
                return {}
        return {}

    def _save_transaction_history(self) -> None:
        """トランザクション履歴を保存"""
        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.transaction_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[AP2Verifier] 履歴ファイルの保存に失敗: {e}")

    def record_transaction(self, intent_mandate_id: str, payment_mandate_id: str) -> None:
        """
        トランザクションを記録（max_transactions チェック用）

        Args:
            intent_mandate_id: Intent Mandate ID
            payment_mandate_id: Payment Mandate ID
        """
        if intent_mandate_id not in self.transaction_history:
            self.transaction_history[intent_mandate_id] = []

        self.transaction_history[intent_mandate_id].append(payment_mandate_id)
        self._save_transaction_history()

    def get_transaction_count(self, intent_mandate_id: str) -> int:
        """
        Intent Mandateに紐づくトランザクション数を取得

        Args:
            intent_mandate_id: Intent Mandate ID

        Returns:
            int: トランザクション数
        """
        return len(self.transaction_history.get(intent_mandate_id, []))

    def verify_intent_mandate(self, intent_mandate: IntentMandate) -> bool:
        """
        Intent Mandateを完全に検証

        検証項目:
        1. User署名の有効性
        2. 有効期限のチェック
        3. 制約条件の妥当性

        Args:
            intent_mandate: 検証するIntent Mandate

        Returns:
            bool: 検証が成功したかどうか

        Raises:
            SignatureError: 署名検証に失敗した場合
            MandateError: Mandateが無効な場合
        """
        print(f"[AP2Verifier] Intent Mandateを検証中: {intent_mandate.id}")

        # 1. User署名の検証
        if not intent_mandate.user_signature:
            raise SignatureError(
                error_code=AP2ErrorCode.MISSING_SIGNATURE,
                message="User署名が存在しません",
                details={"intent_mandate_id": intent_mandate.id}
            )

        # 署名対象データ（intentとconstraintsのみ）
        signing_data = {
            'intent': intent_mandate.intent,
            'constraints': {
                'valid_until': intent_mandate.constraints.valid_until,
                'max_amount': {
                    'value': intent_mandate.constraints.max_amount.value,
                    'currency': intent_mandate.constraints.max_amount.currency
                } if intent_mandate.constraints.max_amount else None,
                'categories': intent_mandate.constraints.categories,
                'merchants': intent_mandate.constraints.merchants,
                'brands': intent_mandate.constraints.brands,
                'valid_from': intent_mandate.constraints.valid_from,
                'max_transactions': intent_mandate.constraints.max_transactions
            }
        }

        # 署名検証
        is_valid = self.signature_manager.verify_data_signature(
            signing_data,
            intent_mandate.user_signature
        )

        if not is_valid:
            raise SignatureError(
                error_code=AP2ErrorCode.SIGNATURE_VERIFICATION_FAILED,
                message="Intent MandateのUser署名検証に失敗しました",
                details={"intent_mandate_id": intent_mandate.id}
            )

        print(f"  ✓ User署名検証OK")

        # 2. 有効期限の検証
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

        print(f"  ✓ 有効期限OK")

        # 3. 制約条件の妥当性チェック（基本的な検証）
        if intent_mandate.constraints.max_amount:
            if intent_mandate.constraints.max_amount.to_decimal() <= 0:
                raise MandateError(
                    error_code=AP2ErrorCode.INVALID_AMOUNT,
                    message="max_amountは正の値である必要があります",
                    details={"max_amount": intent_mandate.constraints.max_amount.value}
                )

        print(f"[AP2Verifier] Intent Mandate検証完了: {intent_mandate.id}")
        return True

    def verify_cart_mandate(
        self,
        cart_mandate: CartMandate,
        intent_mandate: IntentMandate
    ) -> bool:
        """
        Cart Mandateを完全に検証

        検証項目:
        1. Merchant署名の有効性
        2. User署名の有効性
        3. Intent Mandateとの紐付け
        4. 金額整合性（小計+税+配送料=合計）
        5. Intent制約の遵守（max_amount、categories、brandsなど）

        Args:
            cart_mandate: 検証するCart Mandate
            intent_mandate: 関連するIntent Mandate

        Returns:
            bool: 検証が成功したかどうか

        Raises:
            SignatureError: 署名検証に失敗した場合
            MandateError: Mandateが無効な場合
            AmountError: 金額制約違反の場合
        """
        print(f"[AP2Verifier] Cart Mandateを検証中: {cart_mandate.id}")

        # 1. Intent Mandateとの紐付け確認
        if cart_mandate.intent_mandate_id != intent_mandate.id:
            raise MandateError(
                error_code=AP2ErrorCode.INVALID_MANDATE_CHAIN,
                message="Cart MandateのIntent Mandate IDが一致しません",
                details={
                    "cart_mandate_id": cart_mandate.id,
                    "expected_intent_id": intent_mandate.id,
                    "actual_intent_id": cart_mandate.intent_mandate_id
                }
            )

        print(f"  ✓ Intent Mandate紐付けOK")

        # 2. Merchant署名の検証
        if not cart_mandate.merchant_signature:
            raise SignatureError(
                error_code=AP2ErrorCode.MISSING_SIGNATURE,
                message="Merchant署名が存在しません",
                details={"cart_mandate_id": cart_mandate.id}
            )

        # Merchant署名検証（署名対象からsignatureフィールドを除外）
        cart_data_for_merchant = {
            'id': cart_mandate.id,
            'type': cart_mandate.type,
            'version': cart_mandate.version,
            'intent_mandate_id': cart_mandate.intent_mandate_id,
            'items': [
                {
                    'id': item.id,
                    'name': item.name,
                    'quantity': item.quantity,
                    'unit_price': {'value': item.unit_price.value, 'currency': item.unit_price.currency},
                    'total_price': {'value': item.total_price.value, 'currency': item.total_price.currency}
                }
                for item in cart_mandate.items
            ],
            'subtotal': {'value': cart_mandate.subtotal.value, 'currency': cart_mandate.subtotal.currency},
            'tax': {'value': cart_mandate.tax.value, 'currency': cart_mandate.tax.currency},
            'total': {'value': cart_mandate.total.value, 'currency': cart_mandate.total.currency},
            'merchant_id': cart_mandate.merchant_id,
            'merchant_name': cart_mandate.merchant_name
        }

        is_merchant_valid = self.signature_manager.verify_data_signature(
            cart_data_for_merchant,
            cart_mandate.merchant_signature
        )

        if not is_merchant_valid:
            raise SignatureError(
                error_code=AP2ErrorCode.SIGNATURE_VERIFICATION_FAILED,
                message="Cart MandateのMerchant署名検証に失敗しました",
                details={"cart_mandate_id": cart_mandate.id}
            )

        print(f"  ✓ Merchant署名検証OK")

        # 3. User署名の検証
        if not cart_mandate.user_signature:
            raise SignatureError(
                error_code=AP2ErrorCode.MISSING_SIGNATURE,
                message="User署名が存在しません",
                details={"cart_mandate_id": cart_mandate.id}
            )

        # User署名は全体に対して（merchant_signatureを除外）
        cart_data_for_user = cart_data_for_merchant.copy()

        is_user_valid = self.signature_manager.verify_data_signature(
            cart_data_for_user,
            cart_mandate.user_signature
        )

        if not is_user_valid:
            raise SignatureError(
                error_code=AP2ErrorCode.SIGNATURE_VERIFICATION_FAILED,
                message="Cart MandateのUser署名検証に失敗しました",
                details={"cart_mandate_id": cart_mandate.id}
            )

        print(f"  ✓ User署名検証OK")

        # 4. 金額整合性の検証
        calculated_total = cart_mandate.subtotal + cart_mandate.tax + cart_mandate.shipping.cost

        if calculated_total.value != cart_mandate.total.value:
            raise AmountError(
                error_code=AP2ErrorCode.INVALID_AMOUNT,
                message="Cart Mandateの金額計算が一致しません",
                details={
                    "cart_mandate_id": cart_mandate.id,
                    "subtotal": cart_mandate.subtotal.value,
                    "tax": cart_mandate.tax.value,
                    "shipping": cart_mandate.shipping.cost.value,
                    "expected_total": calculated_total.value,
                    "actual_total": cart_mandate.total.value
                }
            )

        print(f"  ✓ 金額整合性OK")

        # 5. Intent制約の遵守チェック
        # 5a. max_amount制約
        if intent_mandate.constraints.max_amount:
            if cart_mandate.total > intent_mandate.constraints.max_amount:
                raise AmountError(
                    error_code=AP2ErrorCode.AMOUNT_EXCEEDED,
                    message="Cart Mandateの金額がIntent Mandateのmax_amountを超えています",
                    details={
                        "cart_total": cart_mandate.total.value,
                        "max_amount": intent_mandate.constraints.max_amount.value
                    }
                )

        # 5b. categories制約（カテゴリー制約チェック）
        if intent_mandate.constraints.categories:
            allowed_categories = intent_mandate.constraints.categories
            for item in cart_mandate.items:
                if item.category and item.category not in allowed_categories:
                    raise MandateError(
                        error_code=AP2ErrorCode.CONSTRAINT_VIOLATION,
                        message=f"商品カテゴリがIntent制約に違反しています: {item.category}",
                        details={
                            "cart_mandate_id": cart_mandate.id,
                            "item_id": item.id,
                            "item_name": item.name,
                            "item_category": item.category,
                            "allowed_categories": allowed_categories
                        }
                    )
            print(f"  ✓ カテゴリー制約チェックOK")

        # 5c. brands制約（ブランド制約チェック）
        if intent_mandate.constraints.brands:
            allowed_brands = intent_mandate.constraints.brands
            for item in cart_mandate.items:
                if item.brand and item.brand not in allowed_brands:
                    raise MandateError(
                        error_code=AP2ErrorCode.CONSTRAINT_VIOLATION,
                        message=f"商品ブランドがIntent制約に違反しています: {item.brand}",
                        details={
                            "cart_mandate_id": cart_mandate.id,
                            "item_id": item.id,
                            "item_name": item.name,
                            "item_brand": item.brand,
                            "allowed_brands": allowed_brands
                        }
                    )
            print(f"  ✓ ブランド制約チェックOK")

        print(f"  ✓ Intent制約遵守OK")

        print(f"[AP2Verifier] Cart Mandate検証完了: {cart_mandate.id}")
        return True

    def verify_payment_mandate(
        self,
        payment_mandate: PaymentMandate,
        cart_mandate: CartMandate,
        intent_mandate: IntentMandate
    ) -> bool:
        """
        Payment Mandateを完全に検証

        検証項目:
        1. User署名の有効性
        2. 有効期限のチェック
        3. Cart Mandateとの紐付け・金額一致
        4. Intent Mandateとの紐付け
        5. max_transactionsチェック（重要！）

        Args:
            payment_mandate: 検証するPayment Mandate
            cart_mandate: 関連するCart Mandate
            intent_mandate: 関連するIntent Mandate

        Returns:
            bool: 検証が成功したかどうか

        Raises:
            SignatureError: 署名検証に失敗した場合
            MandateError: Mandateが無効な場合
            AmountError: 金額制約違反の場合
        """
        print(f"[AP2Verifier] Payment Mandateを検証中: {payment_mandate.id}")

        # 1. User署名の検証
        if not payment_mandate.user_signature:
            raise SignatureError(
                error_code=AP2ErrorCode.MISSING_SIGNATURE,
                message="User署名が存在しません",
                details={"payment_mandate_id": payment_mandate.id}
            )

        # 署名対象データ（signatureフィールドを除外）
        payment_data = {
            'id': payment_mandate.id,
            'type': payment_mandate.type,
            'version': payment_mandate.version,
            'cart_mandate_id': payment_mandate.cart_mandate_id,
            'intent_mandate_id': payment_mandate.intent_mandate_id,
            'amount': {'value': payment_mandate.amount.value, 'currency': payment_mandate.amount.currency},
            'payer_id': payment_mandate.payer_id,
            'payee_id': payment_mandate.payee_id,
            'created_at': payment_mandate.created_at
        }

        is_valid = self.signature_manager.verify_data_signature(
            payment_data,
            payment_mandate.user_signature
        )

        if not is_valid:
            raise SignatureError(
                error_code=AP2ErrorCode.SIGNATURE_VERIFICATION_FAILED,
                message="Payment MandateのUser署名検証に失敗しました",
                details={"payment_mandate_id": payment_mandate.id}
            )

        print(f"  ✓ User署名検証OK")

        # 2. 有効期限の検証
        expires_at = datetime.fromisoformat(payment_mandate.expires_at.replace('Z', '+00:00'))
        now = datetime.now(expires_at.tzinfo)

        if now > expires_at:
            raise MandateError(
                error_code=AP2ErrorCode.EXPIRED_PAYMENT,
                message=f"Payment Mandateは期限切れです: {payment_mandate.id}",
                details={
                    "payment_mandate_id": payment_mandate.id,
                    "expired_at": payment_mandate.expires_at,
                    "current_time": now.isoformat()
                }
            )

        print(f"  ✓ 有効期限OK")

        # 3. Cart Mandateとの紐付け・金額一致
        if payment_mandate.cart_mandate_id != cart_mandate.id:
            raise MandateError(
                error_code=AP2ErrorCode.INVALID_MANDATE_CHAIN,
                message="Payment MandateのCart Mandate IDが一致しません",
                details={
                    "payment_mandate_id": payment_mandate.id,
                    "expected_cart_id": cart_mandate.id,
                    "actual_cart_id": payment_mandate.cart_mandate_id
                }
            )

        if payment_mandate.amount.value != cart_mandate.total.value:
            raise AmountError(
                error_code=AP2ErrorCode.INVALID_AMOUNT,
                message="Payment Mandateの金額がCart Mandateと一致しません",
                details={
                    "payment_amount": payment_mandate.amount.value,
                    "cart_total": cart_mandate.total.value
                }
            )

        print(f"  ✓ Cart Mandate紐付け・金額OK")

        # 4. Intent Mandateとの紐付け
        if payment_mandate.intent_mandate_id != intent_mandate.id:
            raise MandateError(
                error_code=AP2ErrorCode.INVALID_MANDATE_CHAIN,
                message="Payment MandateのIntent Mandate IDが一致しません",
                details={
                    "payment_mandate_id": payment_mandate.id,
                    "expected_intent_id": intent_mandate.id,
                    "actual_intent_id": payment_mandate.intent_mandate_id
                }
            )

        print(f"  ✓ Intent Mandate紐付けOK")

        # 5. max_transactionsチェック（重要！）
        if intent_mandate.constraints.max_transactions is not None:
            current_count = self.get_transaction_count(intent_mandate.id)

            print(f"  → max_transactionsチェック: {current_count}/{intent_mandate.constraints.max_transactions}")

            if current_count >= intent_mandate.constraints.max_transactions:
                raise MandateError(
                    error_code=AP2ErrorCode.CONSTRAINT_VIOLATION,
                    message=f"Intent Mandateのmax_transactionsを超えています",
                    details={
                        "intent_mandate_id": intent_mandate.id,
                        "max_transactions": intent_mandate.constraints.max_transactions,
                        "current_transactions": current_count
                    }
                )

            print(f"  ✓ max_transactionsチェックOK")

        print(f"[AP2Verifier] Payment Mandate検証完了: {payment_mandate.id}")
        return True

    def verify_complete_transaction(
        self,
        payment_mandate: PaymentMandate,
        cart_mandate: CartMandate,
        intent_mandate: IntentMandate
    ) -> bool:
        """
        トランザクション全体を完全に検証

        Intent → Cart → Payment の3つのMandateすべてを検証する

        Args:
            payment_mandate: Payment Mandate
            cart_mandate: Cart Mandate
            intent_mandate: Intent Mandate

        Returns:
            bool: 検証が成功したかどうか

        Raises:
            各種エラー: 検証に失敗した場合
        """
        print(f"[AP2Verifier] トランザクション全体を検証中...")
        print(f"  Intent Mandate: {intent_mandate.id}")
        print(f"  Cart Mandate: {cart_mandate.id}")
        print(f"  Payment Mandate: {payment_mandate.id}")

        # 1. Intent Mandate検証
        self.verify_intent_mandate(intent_mandate)

        # 2. Cart Mandate検証
        self.verify_cart_mandate(cart_mandate, intent_mandate)

        # 3. Payment Mandate検証
        self.verify_payment_mandate(payment_mandate, cart_mandate, intent_mandate)

        print(f"[AP2Verifier] ✓ トランザクション全体の検証完了")

        # 検証が成功したらトランザクションを記録
        self.record_transaction(intent_mandate.id, payment_mandate.id)
        print(f"[AP2Verifier] トランザクションを記録しました")

        return True


def demo_ap2_verifier():
    """AP2 Verifierのデモ"""
    from secure_shopping_agent import SecureShoppingAgent
    from secure_merchant_agent import SecureMerchantAgent
    from merchant import Merchant
    from ap2_types import Amount, Address
    from datetime import datetime, timedelta

    print("=" * 80)
    print("AP2 Verifier - 統一検証デモ")
    print("=" * 80)

    # Verifierを初期化
    verifier = AP2Verifier()

    # Shopping Agentを初期化
    shopping_agent = SecureShoppingAgent(
        agent_id="shopping_agent_demo",
        agent_name="Secure Shopping Assistant",
        passphrase="shopping_agent_pass"
    )

    # User Key Manager
    from ap2_crypto import KeyManager
    user_key_manager = KeyManager()
    user_id = "user_demo_001"

    # Intent Mandateを作成
    print("\n--- Intent Mandateを作成 ---")
    intent_mandate = shopping_agent.create_intent_mandate_with_user_key(
        user_id=user_id,
        user_key_manager=user_key_manager,
        intent="むぎぼーグッズを購入したい",
        max_amount=Amount(value="50.00", currency="USD"),
        categories=["stationery", "tableware"],
        brands=["むぎぼーオフィシャル"],
        max_transactions=3  # 最大3回まで
    )

    print(f"Intent Mandate ID: {intent_mandate.id}")
    print(f"max_transactions: {intent_mandate.constraints.max_transactions}")

    # Intent Mandateを検証
    print("\n--- Intent Mandateを検証 ---")
    try:
        verifier.verify_intent_mandate(intent_mandate)
        print("✓ Intent Mandate検証成功")
    except Exception as e:
        print(f"✗ Intent Mandate検証失敗: {e}")
        return

    # Merchant Agentを初期化
    merchant_agent = SecureMerchantAgent(
        agent_id="merchant_agent_demo",
        merchant_name="むぎぼーグッズショップ",
        merchant_id="merchant_demo_001",
        passphrase="merchant_agent_pass"
    )

    # Merchantを初期化
    merchant = Merchant(
        merchant_id="merchant_demo_001",
        merchant_name="むぎぼーグッズショップ",
        passphrase="merchant_secure_pass"
    )

    # 商品を検索
    products = merchant_agent.search_products(intent_mandate)

    # Cart Mandateを作成
    print("\n--- Cart Mandateを作成 ---")
    shipping_address = Address(
        street="123 Main Street",
        city="San Francisco",
        state="CA",
        postal_code="94105",
        country="US"
    )

    quantities = {products[0].id: 1}
    unsigned_cart = merchant_agent.create_cart_mandate(
        intent_mandate=intent_mandate,
        products=[products[0]],
        quantities=quantities,
        shipping_address=shipping_address
    )

    # MerchantがCart Mandateに署名
    signed_cart = merchant.sign_cart_mandate(unsigned_cart)

    # UserがCart Mandateに署名
    import asyncio
    user_signed_cart = asyncio.run(
        shopping_agent.select_and_sign_cart(signed_cart, user_id, user_key_manager)
    )

    print(f"Cart Mandate ID: {user_signed_cart.id}")

    # Cart Mandateを検証
    print("\n--- Cart Mandateを検証 ---")
    try:
        verifier.verify_cart_mandate(user_signed_cart, intent_mandate)
        print("✓ Cart Mandate検証成功")
    except Exception as e:
        print(f"✗ Cart Mandate検証失敗: {e}")
        return

    # Payment Mandateを作成（3回実行してmax_transactionsをテスト）
    from credential_provider import CredentialProvider
    from ap2_types import CardPaymentMethod

    cp = CredentialProvider(
        provider_id="cp_demo_001",
        provider_name="Demo CP",
        passphrase="cp_pass"
    )

    demo_card = CardPaymentMethod(
        type='card',
        token='',
        last4='4242',
        brand='visa',
        expiry_month=12,
        expiry_year=2026,
        holder_name='Demo User'
    )

    cp.register_payment_method(user_id, demo_card, is_default=True)
    tokenized_pm = cp.create_tokenized_payment_method(
        method_id=cp.get_payment_methods(user_id)[0].method_id,
        user_id=user_id
    )

    # 3回トランザクションを実行
    for i in range(4):  # 4回目は失敗するはず
        print(f"\n--- トランザクション {i+1} を作成・検証 ---")

        payment_mandate = asyncio.run(
            shopping_agent.create_payment_mandate(
                cart_mandate=user_signed_cart,
                intent_mandate=intent_mandate,
                payment_method=tokenized_pm,
                user_id=user_id,
                user_key_manager=user_key_manager
            )
        )

        print(f"Payment Mandate ID: {payment_mandate.id}")

        # Payment Mandateを検証
        try:
            verifier.verify_complete_transaction(
                payment_mandate,
                user_signed_cart,
                intent_mandate
            )
            print(f"✓ トランザクション {i+1} 検証成功")
            print(f"  現在のトランザクション数: {verifier.get_transaction_count(intent_mandate.id)}")
        except Exception as e:
            print(f"✗ トランザクション {i+1} 検証失敗: {e}")
            if i < 3:
                return  # 3回目まではエラーで終了
            else:
                print("✓ 期待通り max_transactions 超過を検出")

    print("\n" + "=" * 80)
    print("デモンストレーション完了!")
    print("=" * 80)


if __name__ == "__main__":
    demo_ap2_verifier()