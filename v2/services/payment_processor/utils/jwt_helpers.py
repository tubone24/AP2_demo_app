"""
v2/services/payment_processor/utils/jwt_helpers.py

JWT検証関連のヘルパーメソッド
"""

import base64
import json
import time
import logging
from typing import Dict, Any, tuple

logger = logging.getLogger(__name__)


class JWTHelpers:
    """JWT検証に関連するヘルパーメソッドを提供するクラス"""

    def __init__(self, key_manager):
        """
        Args:
            key_manager: キー管理のインスタンス
        """
        self.key_manager = key_manager

    @staticmethod
    def base64url_decode(data: str) -> bytes:
        """
        Base64urlデコード（パディング追加対応）

        Args:
            data: Base64url エンコードされた文字列

        Returns:
            bytes: デコードされたバイト列
        """
        # パディング追加（base64url は = パディングを省略）
        padding = '=' * (4 - len(data) % 4)
        return base64.urlsafe_b64decode(data + padding)

    def parse_jwt_parts(self, jwt_string: str) -> tuple[Dict[str, Any], Dict[str, Any], str, str, str]:
        """
        JWTを分解してheader、payload、署名部分を返す

        Args:
            jwt_string: JWT文字列

        Returns:
            tuple: (header, payload, header_b64, payload_b64, signature_b64)

        Raises:
            ValueError: JWT形式が不正な場合
        """
        # JWT形式の検証（header.payload.signature）
        jwt_parts = jwt_string.split('.')
        if len(jwt_parts) != 3:
            raise ValueError(
                f"Invalid JWT format: expected 3 parts (header.payload.signature), "
                f"got {len(jwt_parts)} parts"
            )

        header_b64, payload_b64, signature_b64 = jwt_parts

        # Base64urlデコード
        header_json = self.base64url_decode(header_b64).decode('utf-8')
        payload_json = self.base64url_decode(payload_b64).decode('utf-8')

        header = json.loads(header_json)
        payload = json.loads(payload_json)

        return header, payload, header_b64, payload_b64, signature_b64

    @staticmethod
    def validate_jwt_header(header: Dict[str, Any]) -> None:
        """
        JWTヘッダーを検証

        Args:
            header: JWTヘッダー

        Raises:
            ValueError: ヘッダー検証失敗時
        """
        if header.get("alg") != "ES256":
            logger.warning(
                f"[_validate_jwt_header] Unexpected algorithm: {header.get('alg')}, "
                f"expected ES256"
            )

        if not header.get("kid"):
            raise ValueError("Missing 'kid' (key ID) in JWT header")

        if header.get("typ") != "JWT":
            logger.warning(
                f"[_validate_jwt_header] Unexpected type: {header.get('typ')}, "
                f"expected JWT"
            )

    @staticmethod
    def validate_jwt_payload(payload: Dict[str, Any], expected_audience: str = "did:ap2:agent:payment_processor") -> None:
        """
        JWTペイロードを検証（User用）

        Args:
            payload: JWTペイロード
            expected_audience: 期待されるaudience

        Raises:
            ValueError: ペイロード検証失敗時
        """
        # 必須クレームの検証
        required_claims = ["iss", "aud", "iat", "exp", "nonce", "transaction_data"]
        for claim in required_claims:
            if claim not in payload:
                raise ValueError(f"Missing required claim in JWT payload: {claim}")

        # audience検証
        if payload.get("aud") != expected_audience:
            logger.warning(
                f"[_validate_jwt_payload] Unexpected audience: {payload.get('aud')}, "
                f"expected {expected_audience}"
            )

        # 有効期限検証
        current_timestamp = int(time.time())
        if payload.get("exp", 0) < current_timestamp:
            raise ValueError(
                f"JWT has expired: exp={payload.get('exp')}, "
                f"current={current_timestamp}"
            )

        # transaction_data検証
        transaction_data = payload.get("transaction_data", {})
        if not isinstance(transaction_data, dict):
            raise ValueError("transaction_data must be a dictionary")

        required_tx_fields = ["cart_mandate_hash", "payment_mandate_hash"]
        for field in required_tx_fields:
            if field not in transaction_data:
                raise ValueError(f"Missing required field in transaction_data: {field}")

    @staticmethod
    def validate_merchant_jwt_payload(payload: Dict[str, Any], expected_audience: str = "did:ap2:agent:payment_processor") -> None:
        """
        Merchant JWTペイロードを検証

        Args:
            payload: JWTペイロード
            expected_audience: 期待されるaudience

        Raises:
            ValueError: ペイロード検証失敗時
        """
        # 必須クレームの検証
        required_claims = ["iss", "sub", "aud", "iat", "exp", "jti", "cart_hash"]
        for claim in required_claims:
            if claim not in payload:
                raise ValueError(f"Missing required claim in JWT payload: {claim}")

        # iss と sub は同じであるべき（merchantが自分自身に署名）
        if payload.get("iss") != payload.get("sub"):
            logger.warning(
                f"[_validate_merchant_jwt_payload] iss and sub differ: "
                f"iss={payload.get('iss')}, sub={payload.get('sub')}"
            )

        # audience検証
        if payload.get("aud") != expected_audience:
            logger.warning(
                f"[_validate_merchant_jwt_payload] Unexpected audience: {payload.get('aud')}, "
                f"expected {expected_audience}"
            )

        # 有効期限検証
        current_timestamp = int(time.time())
        if payload.get("exp", 0) < current_timestamp:
            raise ValueError(
                f"JWT has expired: exp={payload.get('exp')}, "
                f"current={current_timestamp}"
            )

        # cart_hash検証（存在確認）
        cart_hash = payload.get("cart_hash")
        if not cart_hash or len(cart_hash) < 16:
            raise ValueError(f"Invalid cart_hash in JWT payload: {cart_hash}")

    def verify_jwt_signature(self, header: Dict[str, Any], header_b64: str, payload_b64: str, signature_b64: str) -> None:
        """
        JWT署名を検証（ES256: ECDSA with P-256 and SHA-256）

        Args:
            header: JWTヘッダー
            header_b64: Base64urlエンコードされたヘッダー
            payload_b64: Base64urlエンコードされたペイロード
            signature_b64: Base64urlエンコードされた署名

        Raises:
            ValueError: 署名検証失敗時
        """
        from v2.common.did_resolver import DIDResolver
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import hashes
        from cryptography.exceptions import InvalidSignature

        # KIDからDIDドキュメント経由で公開鍵を取得
        kid = header.get("kid")
        did_resolver = DIDResolver(self.key_manager)
        public_key_pem = did_resolver.resolve_public_key(kid)

        if not public_key_pem:
            raise ValueError(
                f"Public key not found for KID: {kid}. "
                f"Cannot verify JWT signature without public key."
            )

        try:
            # PEM形式の公開鍵を読み込み
            public_key = serialization.load_pem_public_key(
                public_key_pem.encode('utf-8')
            )

            # 署名対象データ（header_b64.payload_b64）
            message_to_verify = f"{header_b64}.{payload_b64}".encode('utf-8')

            # 署名をデコード
            signature_bytes = self.base64url_decode(signature_b64)

            # ECDSA署名を検証
            public_key.verify(
                signature_bytes,
                message_to_verify,
                ec.ECDSA(hashes.SHA256())
            )

            logger.info("[_verify_jwt_signature] ✓ JWT signature verified successfully")

        except InvalidSignature:
            raise ValueError("Invalid JWT signature: signature verification failed")
        except Exception as e:
            raise ValueError(f"JWT signature verification error: {e}")
