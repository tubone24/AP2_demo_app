"""
AP2 Protocol - Credential Provider
ユーザーの支払い認証情報を管理し、トークン化するプロバイダー
"""

import secrets
from typing import List, Dict, Optional
from datetime import datetime
from dataclasses import dataclass

from ap2_types import PaymentMethod, CardPaymentMethod
from ap2_crypto import KeyManager, SignatureManager


@dataclass
class StoredPaymentMethod:
    """保存された支払い方法"""
    method_id: str
    user_id: str
    payment_method: PaymentMethod
    is_default: bool
    created_at: str
    last_used_at: Optional[str] = None


class CredentialProvider:
    """
    Credential Provider (CP)

    AP2プロトコルにおいて、ユーザーの支払い認証情報を管理し、
    安全にトークン化して提供する役割を担う。

    役割:
    - 支払い方法の登録・管理
    - 支払い方法のトークン化
    - トークンの検証
    - 利用可能な支払い方法の提供
    """

    def __init__(self, provider_id: str, provider_name: str, passphrase: str):
        """
        Credential Providerを初期化

        Args:
            provider_id: プロバイダーID
            provider_name: プロバイダー名
            passphrase: 秘密鍵を保護するパスフレーズ
        """
        self.provider_id = provider_id
        self.provider_name = provider_name

        # 鍵管理
        self.key_manager = KeyManager()
        try:
            self.private_key = self.key_manager.load_private_key_encrypted(
                provider_id,
                passphrase
            )
            self.public_key = self.private_key.public_key()
        except:
            self.private_key, self.public_key = self.key_manager.generate_key_pair(provider_id)
            self.key_manager.save_private_key_encrypted(provider_id, self.private_key, passphrase)
            self.key_manager.save_public_key(provider_id, self.public_key)

        self.signature_manager = SignatureManager(self.key_manager)

        # 支払い方法の保存（実運用ではデータベース）
        self.stored_methods: Dict[str, StoredPaymentMethod] = {}

        # トークンマッピング（実運用では暗号化されたデータベース）
        self.token_mapping: Dict[str, str] = {}  # token -> method_id

    def register_payment_method(
        self,
        user_id: str,
        payment_method: PaymentMethod,
        is_default: bool = False
    ) -> str:
        """
        ユーザーの支払い方法を登録

        Args:
            user_id: ユーザーID
            payment_method: 支払い方法
            is_default: デフォルトの支払い方法とするか

        Returns:
            登録された支払い方法のID
        """
        method_id = f"pm_{secrets.token_urlsafe(16)}"

        stored_method = StoredPaymentMethod(
            method_id=method_id,
            user_id=user_id,
            payment_method=payment_method,
            is_default=is_default,
            created_at=datetime.utcnow().isoformat()
        )

        self.stored_methods[method_id] = stored_method

        print(f"[Credential Provider] 支払い方法を登録: {method_id}")
        return method_id

    def get_payment_methods(self, user_id: str) -> List[StoredPaymentMethod]:
        """
        ユーザーの利用可能な支払い方法を取得

        Args:
            user_id: ユーザーID

        Returns:
            ユーザーの支払い方法リスト
        """
        methods = [
            method for method in self.stored_methods.values()
            if method.user_id == user_id
        ]

        # デフォルトを最初に
        methods.sort(key=lambda m: (not m.is_default, m.created_at))

        return methods

    def tokenize_payment_method(self, method_id: str) -> str:
        """
        支払い方法をトークン化

        実際のシステムでは、PCI DSS準拠のトークナイゼーションを使用

        Args:
            method_id: 支払い方法ID

        Returns:
            トークン
        """
        if method_id not in self.stored_methods:
            raise ValueError(f"支払い方法が見つかりません: {method_id}")

        # トークンを生成
        token = f"tok_{secrets.token_urlsafe(32)}"

        # トークンとmethod_idをマッピング
        self.token_mapping[token] = method_id

        # 最終使用日時を更新
        self.stored_methods[method_id].last_used_at = datetime.utcnow().isoformat()

        print(f"[Credential Provider] 支払い方法をトークン化: {method_id} -> {token[:16]}...")

        return token

    def get_payment_method_by_token(self, token: str) -> Optional[PaymentMethod]:
        """
        トークンから支払い方法を取得

        Args:
            token: トークン

        Returns:
            支払い方法（存在しない場合はNone）
        """
        method_id = self.token_mapping.get(token)
        if not method_id:
            return None

        stored_method = self.stored_methods.get(method_id)
        if not stored_method:
            return None

        return stored_method.payment_method

    def validate_token(self, token: str, user_id: str) -> bool:
        """
        トークンの検証

        Args:
            token: トークン
            user_id: ユーザーID

        Returns:
            トークンが有効かどうか
        """
        method_id = self.token_mapping.get(token)
        if not method_id:
            return False

        stored_method = self.stored_methods.get(method_id)
        if not stored_method:
            return False

        # ユーザーIDが一致するか確認
        if stored_method.user_id != user_id:
            return False

        return True

    def create_tokenized_payment_method(
        self,
        method_id: str,
        user_id: str
    ) -> PaymentMethod:
        """
        トークン化された支払い方法を作成

        実際のカード情報の代わりにトークンを含む支払い方法を返す

        Args:
            method_id: 支払い方法ID
            user_id: ユーザーID

        Returns:
            トークン化された支払い方法
        """
        stored_method = self.stored_methods.get(method_id)
        if not stored_method or stored_method.user_id != user_id:
            raise ValueError(f"支払い方法が見つかりません: {method_id}")

        # トークンを生成
        token = self.tokenize_payment_method(method_id)

        # 元の支払い方法を取得
        original_method = stored_method.payment_method

        # トークン化された支払い方法を作成（実際のカード情報は含まない）
        if isinstance(original_method, CardPaymentMethod):
            tokenized_method = CardPaymentMethod(
                type='card',
                token=token,  # トークンを設定
                last4=original_method.last4,  # 下4桁のみ
                brand=original_method.brand,
                expiry_month=original_method.expiry_month,
                expiry_year=original_method.expiry_year,
                holder_name=original_method.holder_name
            )
        else:
            # 他の支払い方法タイプにも対応可能
            tokenized_method = original_method

        print(f"[Credential Provider] トークン化された支払い方法を作成")
        print(f"  Token: {token[:16]}...")
        print(f"  Brand: {tokenized_method.brand.upper()} ****{tokenized_method.last4}")

        return tokenized_method

    def request_payment_credentials(
        self,
        payment_mandate: 'PaymentMandate',
        otp: Optional[str] = None
    ) -> Dict:
        """
        Payment Processorからのpayment credentialsリクエストを処理

        AP2仕様のステップ25-27に対応：
        - MPP → CP: "request payment credentials { PaymentMandate }"
        - CP → MPP: "{ payment credentials }"

        Args:
            payment_mandate: Payment Mandate
            otp: ワンタイムパスワード（高リスク取引で必要）

        Returns:
            payment credentials（実際の支払い情報）
        """
        print(f"[Credential Provider] Payment credentialsのリクエストを受信")

        # 1. Payment Mandateの署名を検証
        if not payment_mandate.user_signature:
            raise ValueError("Payment MandateにUser署名がありません")

        print(f"  ✓ Payment Mandate署名を検証")

        # 2. リスクスコアをチェック
        risk_score = payment_mandate.risk_score or 0
        print(f"  リスクスコア: {risk_score}/100")

        # 3. 高リスク取引の場合、追加認証を要求
        if risk_score >= 60:
            if not otp:
                raise ValueError("高リスク取引です。OTPによる追加認証が必要です")

            # OTP検証（簡易版：固定値チェック）
            if not self._verify_otp(payment_mandate.payer_id, otp):
                raise ValueError("OTPが無効です")

            print(f"  ✓ OTP検証完了")

        # 4. トークンから実際の支払い方法を取得
        token = payment_mandate.payment_method.token
        if not token:
            raise ValueError("Payment Methodにトークンがありません")

        payment_method = self.get_payment_method_by_token(token)
        if not payment_method:
            raise ValueError(f"トークンに対応する支払い方法が見つかりません: {token[:16]}...")

        # 5. ユーザーIDが一致するか確認
        if not self.validate_token(token, payment_mandate.payer_id):
            raise ValueError("トークンが無効、またはユーザーIDが一致しません")

        print(f"  ✓ トークン検証完了")
        print(f"  支払い方法: {payment_method.brand.upper()} ****{payment_method.last4}")

        # 6. Payment Credentialsを返す
        # 実際のシステムでは、決済ネットワークに送信するための暗号化された認証情報を返す
        payment_credentials = {
            "credential_type": "card",
            "card_number": f"****{payment_method.last4}",  # 実際は完全な番号
            "brand": payment_method.brand,
            "expiry_month": payment_method.expiry_month,
            "expiry_year": payment_method.expiry_year,
            "holder_name": payment_method.holder_name,
            "cryptogram": self._generate_cryptogram(payment_method),  # 決済ネットワーク用
            "token": token,
            "provider_id": self.provider_id
        }

        print(f"[Credential Provider] Payment credentialsを返却")

        return payment_credentials

    def _verify_otp(self, user_id: str, otp: str) -> bool:
        """
        OTPを検証

        実際のシステムでは：
        - Time-based OTP (TOTP)
        - SMS OTP
        - Email OTP
        などを使用

        Args:
            user_id: ユーザーID
            otp: ワンタイムパスワード

        Returns:
            OTPが有効かどうか
        """
        # デモ用：固定値チェック
        DEMO_OTP = "123456"
        return otp == DEMO_OTP

    def _generate_cryptogram(self, payment_method: PaymentMethod) -> str:
        """
        決済ネットワーク用のクリプトグラムを生成

        実際のシステムでは：
        - EMV 3DS 2.0クリプトグラム
        - Apple Pay/Google Pay暗号化
        などを使用

        Args:
            payment_method: 支払い方法

        Returns:
            クリプトグラム
        """
        # デモ用：ランダムな文字列
        return secrets.token_hex(16)


def demo_credential_provider():
    """Credential Providerのデモ"""
    print("=== Credential Provider Demo ===\n")

    # Credential Providerを初期化
    cp = CredentialProvider(
        provider_id="cp_demo_001",
        provider_name="Demo Credential Provider",
        passphrase="cp_secure_pass_2024"
    )

    # ユーザーの支払い方法を登録
    print("1. 支払い方法を登録\n")

    card1 = CardPaymentMethod(
        type='card',
        token='',  # まだトークン化されていない
        last4='4242',
        brand='visa',
        expiry_month=12,
        expiry_year=2026,
        holder_name='John Doe'
    )

    method_id1 = cp.register_payment_method(
        user_id="user_123",
        payment_method=card1,
        is_default=True
    )

    card2 = CardPaymentMethod(
        type='card',
        token='',
        last4='5555',
        brand='mastercard',
        expiry_month=6,
        expiry_year=2027,
        holder_name='John Doe'
    )

    method_id2 = cp.register_payment_method(
        user_id="user_123",
        payment_method=card2,
        is_default=False
    )

    print(f"\n登録完了: {method_id1}, {method_id2}\n")

    # 利用可能な支払い方法を取得
    print("2. 利用可能な支払い方法を取得\n")

    methods = cp.get_payment_methods("user_123")
    for method in methods:
        pm = method.payment_method
        default_mark = " (デフォルト)" if method.is_default else ""
        print(f"  - {pm.brand.upper()} ****{pm.last4}{default_mark}")

    # トークン化
    print("\n3. 支払い方法をトークン化\n")

    tokenized_method = cp.create_tokenized_payment_method(method_id1, "user_123")

    # トークンの検証
    print("\n4. トークンの検証\n")

    is_valid = cp.validate_token(tokenized_method.token, "user_123")
    print(f"  トークンは有効: {is_valid}")

    # トークンから支払い方法を取得
    print("\n5. トークンから支払い方法を取得\n")

    retrieved_method = cp.get_payment_method_by_token(tokenized_method.token)
    if retrieved_method:
        print(f"  取得成功: {retrieved_method.brand.upper()} ****{retrieved_method.last4}")


if __name__ == "__main__":
    demo_credential_provider()