"""
AP2 Protocol - Merchant Payment Processor
決済処理を担当するエンティティ
Credential Providerと連携して実際の決済を実行
"""

from datetime import datetime
from typing import Optional, Dict
import uuid
import time

from ap2_types import (
    CartMandate,
    PaymentMandate,
    TransactionResult,
    TransactionStatus,
    Amount,
    AP2ErrorCode,
    MandateError
)
from ap2_crypto import KeyManager, SignatureManager
from transaction_store import TransactionStore


class TransactionChallengeRequired(Exception):
    """
    高リスク取引でOTP認証が必要な場合に発生する例外

    Attributes:
        transaction_id: チャレンジ待ちのトランザクションID
        risk_score: リスクスコア
        message: エラーメッセージ
    """
    def __init__(self, transaction_id: str, risk_score: int, message: str):
        self.transaction_id = transaction_id
        self.risk_score = risk_score
        self.message = message
        super().__init__(message)


class MerchantPaymentProcessor:
    """
    Merchant Payment Processor (決済処理業者)

    AP2プロトコルにおいて、実際の決済処理を担当するエンティティ。
    Credential Providerから取得した支払い情報を使用して、
    トランザクションの承認とキャプチャを実行する。

    役割:
    - Payment Mandateの検証
    - トランザクションの承認（Authorization）
    - トランザクションのキャプチャ（Capture）
    - 決済ネットワークとの通信（シミュレート）
    - トランザクション状態の管理
    """

    def __init__(self, processor_id: str, processor_name: str, passphrase: str, credential_provider=None):
        """
        Payment Processorを初期化

        Args:
            processor_id: 決済処理業者ID
            processor_name: 決済処理業者名
            passphrase: 秘密鍵を保護するパスフレーズ
            credential_provider: Credential Providerのインスタンス（オプション）
        """
        self.processor_id = processor_id
        self.processor_name = processor_name
        self.credential_provider = credential_provider

        # 鍵管理
        self.key_manager = KeyManager()
        try:
            self.private_key = self.key_manager.load_private_key_encrypted(
                processor_id,
                passphrase
            )
            self.public_key = self.private_key.public_key()
        except:
            self.private_key, self.public_key = self.key_manager.generate_key_pair(processor_id)
            self.key_manager.save_private_key_encrypted(processor_id, self.private_key, passphrase)
            self.key_manager.save_public_key(processor_id, self.public_key)

        self.signature_manager = SignatureManager(self.key_manager)

        # トランザクション履歴（メモリ内）
        self.transactions = {}

        # トランザクション永続化ストア
        self.transaction_store = TransactionStore(f"./transaction_history_{processor_id}.json")

        # OTPチャレンジ待ちのトランザクション
        self.pending_challenges = {}

        print(f"[Payment Processor] 初期化完了: {processor_name} (ID: {processor_id})")

    def validate_payment_mandate(self, payment_mandate: PaymentMandate, cart_mandate: CartMandate) -> bool:
        """
        Payment Mandateを検証

        Args:
            payment_mandate: 検証するPayment Mandate
            cart_mandate: 対応するCart Mandate

        Returns:
            検証が成功したかどうか

        Raises:
            MandateError: Payment Mandateが期限切れの場合
        """
        print(f"[Payment Processor] Payment Mandateを検証中...")

        # 0. Payment Mandateの有効期限をチェック
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

        print(f"  ✓ Payment Mandate有効期限OK")

        # 1. Cart Mandate IDが一致するか確認
        if payment_mandate.cart_mandate_id != cart_mandate.id:
            print(f"[Payment Processor] エラー: Cart Mandate IDが一致しません")
            return False

        # 2. 金額が一致するか確認
        if payment_mandate.amount.value != cart_mandate.total.value:
            print(f"[Payment Processor] エラー: 金額が一致しません")
            return False

        # 3. 通貨が一致するか確認
        if payment_mandate.amount.currency != cart_mandate.total.currency:
            print(f"[Payment Processor] エラー: 通貨が一致しません")
            return False

        # 4. 支払い方法が有効か確認
        if not payment_mandate.payment_method:
            print(f"[Payment Processor] エラー: 支払い方法が設定されていません")
            return False

        print(f"[Payment Processor] 検証完了: Payment Mandateは有効です")
        return True

    def authorize_transaction(
        self,
        payment_mandate: PaymentMandate,
        cart_mandate: CartMandate,
        otp: Optional[str] = None
    ) -> TransactionResult:
        """
        トランザクションを承認（Authorization）

        AP2仕様のステップ25-27に対応：
        - MPP → CP: "request payment credentials { PaymentMandate }"
        - CP → MPP: "{ payment credentials }"
        - 高リスク取引の場合はOTPチャレンジを要求

        Args:
            payment_mandate: Payment Mandate
            cart_mandate: Cart Mandate
            otp: ワンタイムパスワード（高リスク取引で必要）

        Returns:
            トランザクション結果

        Raises:
            TransactionChallengeRequired: 高リスク取引でOTPが必要な場合
        """
        print(f"[Payment Processor] トランザクションの承認を開始...")

        # Payment Mandateを検証
        if not self.validate_payment_mandate(payment_mandate, cart_mandate):
            raise ValueError("Payment Mandateの検証に失敗しました")

        # トランザクションIDを生成
        transaction_id = f"txn_{uuid.uuid4().hex[:12]}"

        # === AP2仕様ステップ25-27: Credential Providerから payment credentials を取得 ===
        payment_credentials = None

        if self.credential_provider:
            print(f"[Payment Processor] Credential Providerに payment credentials をリクエスト...")
            print(f"  AP2仕様ステップ25-27: MPP → CP 通信")

            try:
                # Credential Provider に payment credentials をリクエスト
                payment_credentials = self.credential_provider.request_payment_credentials(
                    payment_mandate,
                    otp=otp
                )

                print(f"[Payment Processor] ✓ Payment credentials を取得しました")
                print(f"  Brand: {payment_credentials['brand'].upper()}")
                print(f"  Last4: ****{payment_credentials['card_number'][-4:]}")
                print(f"  Cryptogram: {payment_credentials['cryptogram'][:16]}...")

            except ValueError as e:
                error_msg = str(e)

                # 高リスク取引でOTPが必要な場合
                if "OTP" in error_msg or "追加認証" in error_msg:
                    # トランザクションをペンディング状態として保存
                    self.pending_challenges[transaction_id] = {
                        "payment_mandate": payment_mandate,
                        "cart_mandate": cart_mandate,
                        "risk_score": payment_mandate.risk_score or 0,
                        "created_at": datetime.utcnow().isoformat() + "Z"
                    }

                    risk_score = payment_mandate.risk_score or 0
                    print(f"[Payment Processor] ⚠ 高リスク取引検出 (リスクスコア: {risk_score}/100)")
                    print(f"[Payment Processor] OTPによる追加認証が必要です")

                    raise TransactionChallengeRequired(
                        transaction_id=transaction_id,
                        risk_score=risk_score,
                        message=f"高リスク取引です。OTPによる追加認証が必要です。(取引ID: {transaction_id})"
                    )
                else:
                    # その他のエラー
                    raise
        else:
            # Credential Providerが設定されていない場合は、従来の方法
            print(f"[Payment Processor] ⚠ Credential Providerが設定されていません")
            print(f"[Payment Processor] Payment Mandateから直接支払い情報を使用します")

        # 決済ネットワークとの通信をシミュレート
        print(f"[Payment Processor] 決済ネットワークに承認リクエストを送信中...")

        if payment_credentials:
            # Credential Providerから取得した credentials を使用
            print(f"  Cryptogram: {payment_credentials['cryptogram'][:16]}...")
            card_last4 = payment_credentials['card_number'][-4:]
            card_brand = payment_credentials['brand']
        else:
            # 従来の方法（Payment Mandateから直接）
            print(f"  Payment Method: {payment_mandate.payment_method.brand} ****{payment_mandate.payment_method.last4}")
            card_last4 = payment_mandate.payment_method.last4
            card_brand = payment_mandate.payment_method.brand

        time.sleep(0.5)  # シミュレート用の遅延

        # === オーソリ処理のシミュレーション ===
        # カードの下4桁に基づいて失敗パターンをシミュレート（テスト用）
        transaction_result = self._simulate_authorization(
            transaction_id,
            payment_mandate,
            cart_mandate,
            card_last4,
            card_brand
        )

        # トランザクションを保存（メモリ内）
        self.transactions[transaction_id] = transaction_result

        # トランザクションを永続化
        self.transaction_store.save_transaction(
            transaction_result,
            payment_mandate,
            cart_mandate=cart_mandate
        )

        # 結果を表示
        if transaction_result.status == TransactionStatus.AUTHORIZED:
            print(f"[Payment Processor] ✓ トランザクション承認完了: {transaction_id}")
            print(f"  金額: {payment_mandate.amount.currency} {payment_mandate.amount.value}")
            if payment_credentials:
                print(f"  支払い方法: {card_brand.upper()} {payment_credentials['card_number']}")
            else:
                print(f"  支払い方法: {card_brand.upper()} ****{card_last4}")
        else:
            print(f"[Payment Processor] ✗ トランザクション承認失敗: {transaction_id}")
            print(f"  エラーコード: {transaction_result.error_code}")
            print(f"  エラーメッセージ: {transaction_result.error_message}")

        return transaction_result

    def complete_challenge(
        self,
        transaction_id: str,
        otp: str
    ) -> TransactionResult:
        """
        OTPチャレンジを完了してトランザクションを承認

        高リスク取引で TransactionChallengeRequired 例外が発生した後、
        ユーザーがOTPを入力した場合にこのメソッドを呼び出します。

        Args:
            transaction_id: チャレンジ待ちのトランザクションID
            otp: ワンタイムパスワード

        Returns:
            トランザクション結果

        Raises:
            ValueError: トランザクションが見つからないか、OTPが無効な場合
        """
        print(f"[Payment Processor] OTPチャレンジを完了中: {transaction_id}")

        # ペンディング中のトランザクションを取得
        if transaction_id not in self.pending_challenges:
            raise ValueError(f"ペンディング中のトランザクションが見つかりません: {transaction_id}")

        challenge_data = self.pending_challenges[transaction_id]
        payment_mandate = challenge_data["payment_mandate"]
        cart_mandate = challenge_data["cart_mandate"]

        print(f"  リスクスコア: {challenge_data['risk_score']}/100")
        print(f"  OTPを検証中...")

        # OTPを使ってトランザクションを再実行
        try:
            transaction_result = self.authorize_transaction(
                payment_mandate,
                cart_mandate,
                otp=otp
            )

            # 成功したらペンディングリストから削除
            del self.pending_challenges[transaction_id]

            print(f"[Payment Processor] ✓ OTPチャレンジ完了")
            return transaction_result

        except TransactionChallengeRequired:
            # まだチャレンジが必要（OTPが無効など）
            raise ValueError(f"OTPが無効です")

        except Exception as e:
            # その他のエラー
            raise ValueError(f"トランザクションの処理に失敗しました: {str(e)}")

    def capture_transaction(self, transaction_id: str) -> TransactionResult:
        """
        トランザクションをキャプチャ（実際の決済実行）

        Args:
            transaction_id: トランザクションID

        Returns:
            更新されたトランザクション結果
        """
        print(f"[Payment Processor] トランザクションのキャプチャを開始: {transaction_id}")

        # トランザクションが存在するか確認
        if transaction_id not in self.transactions:
            raise ValueError(f"トランザクションが見つかりません: {transaction_id}")

        transaction = self.transactions[transaction_id]

        # トランザクションが承認済みか確認
        if transaction.status != TransactionStatus.AUTHORIZED:
            raise ValueError(f"トランザクションは承認済みではありません: {transaction.status}")

        # 決済ネットワークとの通信をシミュレート
        print(f"[Payment Processor] 決済ネットワークにキャプチャリクエストを送信中...")
        time.sleep(0.5)  # シミュレート用の遅延

        # キャプチャ処理をシミュレート（常に成功）
        captured_at = datetime.utcnow().isoformat() + "Z"

        # 領収書URLを生成（実際はS3などのストレージURLを使用）
        receipt_url = f"https://receipts.ap2-demo.com/{transaction_id}.pdf"

        # トランザクション結果を更新
        transaction.status = TransactionStatus.CAPTURED
        transaction.captured_at = captured_at
        transaction.receipt_url = receipt_url

        print(f"[Payment Processor] トランザクションキャプチャ完了: {transaction_id}")
        print(f"[Payment Processor] 決済完了日時: {captured_at}")
        print(f"[Payment Processor] 領収書URL: {receipt_url}")

        return transaction

    def refund_transaction(self, transaction_id: str, amount: Optional[Amount] = None) -> TransactionResult:
        """
        トランザクションを返金

        Args:
            transaction_id: トランザクションID
            amount: 返金額（Noneの場合は全額返金）

        Returns:
            更新されたトランザクション結果
        """
        print(f"[Payment Processor] トランザクションの返金を開始: {transaction_id}")

        # トランザクションが存在するか確認
        if transaction_id not in self.transactions:
            raise ValueError(f"トランザクションが見つかりません: {transaction_id}")

        transaction = self.transactions[transaction_id]

        # トランザクションがキャプチャ済みか確認
        if transaction.status != TransactionStatus.CAPTURED:
            raise ValueError(f"トランザクションはキャプチャ済みではありません: {transaction.status}")

        # 返金額を決定
        refund_amount = amount if amount else transaction.amount

        # 決済ネットワークとの通信をシミュレート
        print(f"[Payment Processor] 決済ネットワークに返金リクエストを送信中...")
        time.sleep(0.5)  # シミュレート用の遅延

        # 返金処理をシミュレート（常に成功）
        refunded_at = datetime.utcnow().isoformat() + "Z"

        # トランザクション結果を更新
        transaction.status = TransactionStatus.REFUNDED

        print(f"[Payment Processor] トランザクション返金完了: {transaction_id}")
        print(f"[Payment Processor] 返金額: {refund_amount.currency} {refund_amount.value}")
        print(f"[Payment Processor] 返金日時: {refunded_at}")

        return transaction

    def _simulate_authorization(
        self,
        transaction_id: str,
        payment_mandate: PaymentMandate,
        cart_mandate: CartMandate,
        card_last4: str,
        card_brand: str
    ) -> TransactionResult:
        """
        オーソリ処理をシミュレート

        テスト用：カードの下4桁に基づいて失敗パターンを決定
        実際のシステムでは、決済ネットワーク（Visa/Mastercard等）からのレスポンスに基づく

        Args:
            transaction_id: トランザクションID
            payment_mandate: Payment Mandate
            cart_mandate: Cart Mandate
            card_last4: カード番号の下4桁
            card_brand: カードブランド

        Returns:
            TransactionResult: トランザクション結果（成功または失敗）
        """
        # テスト用のエラーパターン（カード下4桁に基づく）
        error_patterns = {
            "0001": ("insufficient_funds", "残高不足です。カードの利用可能額を確認してください。"),
            "0002": ("card_declined", "カードが拒否されました。カード発行会社にお問い合わせください。"),
            "0003": ("expired_card", "カードの有効期限が切れています。"),
            "0004": ("incorrect_cvc", "セキュリティコード（CVV/CVC）が正しくありません。"),
            "0005": ("fraud_suspected", "不正利用の疑いがあるため、取引がブロックされました。"),
            "0006": ("lost_card", "紛失カードとして登録されているため、使用できません。"),
            "0007": ("stolen_card", "盗難カードとして登録されているため、使用できません。"),
            "0008": ("invalid_account", "カード番号が無効です。"),
            "0009": ("do_not_honor", "カード発行会社により取引が拒否されました。"),
            "0010": ("card_velocity_exceeded", "短時間に複数回の取引が行われたため、ブロックされました。"),
        }

        # カードの下4桁をチェック
        if card_last4 in error_patterns:
            error_code, error_message = error_patterns[card_last4]

            print(f"[Payment Processor] ✗ オーソリ失敗（テストモード）")
            print(f"  カード: {card_brand.upper()} ****{card_last4}")
            print(f"  エラーコード: {error_code}")
            print(f"  エラーメッセージ: {error_message}")

            return TransactionResult(
                id=transaction_id,
                status=TransactionStatus.FAILED,
                payment_mandate_id=payment_mandate.id,
                error_code=error_code,
                error_message=error_message
            )

        # それ以外のカードは成功
        authorized_at = datetime.utcnow().isoformat() + "Z"

        return TransactionResult(
            id=transaction_id,
            status=TransactionStatus.AUTHORIZED,
            payment_mandate_id=payment_mandate.id,
            authorized_at=authorized_at,
            captured_at=None,
            receipt_url=None
        )

    def get_transaction(self, transaction_id: str) -> Optional[TransactionResult]:
        """
        トランザクション情報を取得

        Args:
            transaction_id: トランザクションID

        Returns:
            トランザクション結果（存在しない場合はNone）
        """
        return self.transactions.get(transaction_id)

    def verify_processor_signature(self, transaction_result: TransactionResult, signature: str) -> bool:
        """
        Payment Processor署名を検証

        Args:
            transaction_result: トランザクション結果
            signature: 検証する署名

        Returns:
            署名が有効かどうか
        """
        transaction_data = {
            "id": transaction_result.id,
            "status": transaction_result.status.value,
            "amount": {
                "value": transaction_result.amount.value,
                "currency": transaction_result.amount.currency
            },
            "authorized_at": transaction_result.authorized_at,
            "captured_at": transaction_result.captured_at
        }

        return self.signature_manager.verify_signature(
            transaction_data,
            signature
        )


def demo_payment_processor():
    """Payment Processorのデモ"""
    from merchant import Merchant
    from secure_merchant_agent import SecureMerchantAgent
    from ap2_types import IntentMandate, IntentConstraints, Address, CardPaymentMethod
    from datetime import datetime, timedelta

    print("=== Payment Processor Demo ===\n")

    # Merchant Agentを初期化
    merchant_agent = SecureMerchantAgent(
        agent_id="merchant_agent_demo",
        merchant_name="Demo Running Shoes Store",
        merchant_id="merchant_demo_001",
        passphrase="merchant_agent_pass"
    )

    # Merchantを初期化
    merchant = Merchant(
        merchant_id="merchant_demo_001",
        merchant_name="Demo Running Shoes Store",
        passphrase="merchant_secure_pass"
    )

    # Payment Processorを初期化
    payment_processor = MerchantPaymentProcessor(
        processor_id="processor_demo_001",
        processor_name="Demo Payment Processor",
        passphrase="processor_secure_pass"
    )

    # Intent Mandateを作成
    intent_mandate = IntentMandate(
        id="intent_001",
        type="IntentMandate",
        version="1.0",
        user_id="user_demo_001",
        user_public_key="dummy_public_key",
        intent="ランニングシューズを購入したい",
        constraints=IntentConstraints(
            valid_until=(datetime.utcnow() + timedelta(hours=24)).isoformat(),
            max_amount=Amount(value="100.00", currency="USD"),
            brands=["Nike", "Adidas"]
        ),
        created_at=datetime.utcnow().isoformat(),
        expires_at=(datetime.utcnow() + timedelta(hours=24)).isoformat()
    )

    # 商品を検索
    products = merchant_agent.search_products(intent_mandate)

    # Cart Mandateを作成
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

    # MerchantがCart Mandateに署名
    print("\n--- MerchantがCart Mandateに署名 ---")
    signed_cart = merchant.sign_cart_mandate(cart_mandate)

    # Payment Mandateを作成（簡易版）
    print("\n--- Payment Mandateを作成 ---")
    payment_method = CardPaymentMethod(
        type='card',
        token='tok_demo_xxxxx',
        last4='4242',
        brand='visa',
        expiry_month=12,
        expiry_year=2026,
        holder_name='Demo User'
    )

    # Payment Mandateを作成（有効期限15分）
    now = datetime.utcnow()
    expires_at = now + timedelta(minutes=15)

    payment_mandate = PaymentMandate(
        id=f"payment_{uuid.uuid4().hex[:12]}",
        type="PaymentMandate",
        version="1.0",
        cart_mandate_id=signed_cart.id,
        intent_mandate_id=intent_mandate.id,
        payment_method=payment_method,
        amount=signed_cart.total,
        transaction_type="human_not_present",
        agent_involved=False,
        payer_id="user_demo_001",
        payee_id="merchant_demo_001",
        created_at=now.isoformat() + 'Z',
        expires_at=expires_at.isoformat() + 'Z'
    )

    print(f"Payment Mandate ID: {payment_mandate.id}")
    print(f"支払い方法: {payment_method.brand.upper()} ****{payment_method.last4}")

    # トランザクションを承認
    print("\n--- トランザクションを承認 ---")
    transaction = payment_processor.authorize_transaction(payment_mandate, signed_cart)

    print(f"\nトランザクションID: {transaction.id}")
    print(f"ステータス: {transaction.status.value}")

    # トランザクションをキャプチャ
    print("\n--- トランザクションをキャプチャ ---")
    captured_transaction = payment_processor.capture_transaction(transaction.id)

    print(f"\nトランザクションID: {captured_transaction.id}")
    print(f"ステータス: {captured_transaction.status.value}")
    print(f"領収書URL: {captured_transaction.receipt_url}")


if __name__ == "__main__":
    demo_payment_processor()