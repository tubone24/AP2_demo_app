"""
v2/services/merchant/utils/jwt_helpers.py

JWT生成関連のヘルパーメソッド
"""

import base64
import json
import uuid
import logging
from typing import Dict, Any
from datetime import datetime, timezone
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

logger = logging.getLogger(__name__)


class JWTHelpers:
    """JWT生成に関連するヘルパーメソッドを提供するクラス"""

    def __init__(self, key_manager):
        """
        Args:
            key_manager: キー管理のインスタンス
        """
        self.key_manager = key_manager

    @staticmethod
    def build_jwt_header(merchant_id: str) -> Dict[str, str]:
        """
        JWTヘッダーを構築

        Args:
            merchant_id: Merchant ID

        Returns:
            Dict[str, str]: JWTヘッダー
        """
        return {
            "alg": "ES256",  # ECDSA with SHA-256
            "kid": f"{merchant_id}#key-1",  # Key ID
            "typ": "JWT"
        }

    @staticmethod
    def build_merchant_jwt_payload(merchant_id: str, cart_hash: str) -> Dict[str, Any]:
        """
        Merchant用JWTペイロードを構築

        Args:
            merchant_id: Merchant ID
            cart_hash: CartContentsのハッシュ

        Returns:
            Dict[str, Any]: JWTペイロード
        """
        now = datetime.now(timezone.utc)

        # AP2準拠: JWTの有効期限は1時間（3600秒）に設定
        # CartMandateのcart_expiry（15分）とは独立して、署名の有効性を保証
        return {
            "iss": merchant_id,  # Issuer: Merchant
            "sub": merchant_id,  # Subject: Merchant (same as issuer)
            "aud": "did:ap2:agent:payment_processor",  # Audience: Payment Processor
            "iat": int(now.timestamp()),  # Issued At
            "exp": int(now.timestamp()) + 3600,  # Expiry: 1時間後（AP2準拠）
            "jti": str(uuid.uuid4()),  # JWT ID（リプレイ攻撃防止）
            "cart_hash": cart_hash  # CartContentsのハッシュ
        }

    @staticmethod
    def base64url_encode_jwt_part(data: Dict[str, Any]) -> str:
        """
        JWTパート（header/payload）をBase64urlエンコード

        Args:
            data: エンコードするデータ

        Returns:
            str: Base64urlエンコードされた文字列
        """
        json_str = json.dumps(data, separators=(',', ':'))
        return base64.urlsafe_b64encode(json_str.encode('utf-8')).rstrip(b'=').decode('utf-8')

    def sign_jwt_message(self, message: str, key_id: str) -> str:
        """
        JWTメッセージに署名

        Args:
            message: 署名対象メッセージ（header_b64.payload_b64）
            key_id: 秘密鍵のID

        Returns:
            str: Base64urlエンコードされた署名

        Raises:
            ValueError: 署名失敗時
        """
        try:
            private_key = self.key_manager.get_private_key(key_id)

            if private_key is None:
                raise ValueError(f"Merchant private key not found: {key_id}")

            # ECDSA署名（ES256: ECDSA with SHA-256）
            signature_bytes = private_key.sign(
                message.encode('utf-8'),
                ec.ECDSA(hashes.SHA256())
            )

            # Base64URLエンコード（パディングなし）
            return base64.urlsafe_b64encode(signature_bytes).rstrip(b'=').decode('utf-8')

        except Exception as e:
            logger.error(f"[_sign_jwt_message] Failed to generate signature: {e}")
            raise ValueError(f"Failed to sign JWT message: {e}")

    def generate_merchant_authorization_jwt(
        self,
        cart_hash: str,
        merchant_id: str
    ) -> str:
        """
        AP2仕様準拠のmerchant_authorization JWTを生成

        Args:
            cart_hash: CartContentsのハッシュ
            merchant_id: Merchant ID

        Returns:
            str: JWT文字列

        Raises:
            ValueError: JWT生成失敗時
        """
        try:
            # 2. JWTヘッダーを構築
            jwt_header = self.build_jwt_header(merchant_id)

            # 3. JWTペイロードを構築
            jwt_payload = self.build_merchant_jwt_payload(merchant_id, cart_hash)

            # 4. Base64URLエンコード
            header_b64 = self.base64url_encode_jwt_part(jwt_header)
            payload_b64 = self.base64url_encode_jwt_part(jwt_payload)

            # 5. 署名対象メッセージ
            message_to_sign = f"{header_b64}.{payload_b64}"

            # 6. ECDSA署名（ES256）
            signature_b64 = self.sign_jwt_message(message_to_sign, merchant_id)

            # 7. JWT完成
            merchant_authorization_jwt = f"{header_b64}.{payload_b64}.{signature_b64}"

            logger.info(
                f"[_generate_merchant_authorization_jwt] ✓ JWT generated successfully: "
                f"length={len(merchant_authorization_jwt)}, "
                f"cart_hash={cart_hash[:16]}..., "
                f"merchant_id={merchant_id}"
            )

            return merchant_authorization_jwt

        except Exception as e:
            logger.error(f"[_generate_merchant_authorization_jwt] Failed to generate JWT: {e}")
            raise ValueError(f"Failed to generate merchant authorization JWT: {e}")
