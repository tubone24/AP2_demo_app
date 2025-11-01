"""JWT生成・検証ユーティリティ (AP2プロトコル準拠)

このモジュールは、以下の機能を提供します:
1. merchant_authorization JWT生成・検証
2. user_authorization SD-JWT-VC生成・検証
3. Canonical JSONハッシュ計算

参照:
- AP2仕様書: refs/AP2-main/docs/specification.md
- RFC 8785: JSON Canonicalization Scheme
"""

import hashlib
import uuid
import base64
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, TYPE_CHECKING

import rfc8785
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, utils as asym_utils
from cryptography.hazmat.primitives import hashes

# 循環インポート回避のためTYPE_CHECKINGを使用
if TYPE_CHECKING:
    from common.crypto import SignatureManager, KeyManager


def compute_canonical_hash(data: Dict[str, Any]) -> str:
    """Canonical JSON表現のSHA-256ハッシュを計算

    RFC 8785に準拠したJSON正規化を使用します。

    Args:
        data: ハッシュ化するPython辞書

    Returns:
        Canonical JSON表現のSHA-256ハッシュ（base64url-encoded）
    """
    # RFC 8785に準拠したCanonical JSON表現を生成
    canonical_json_bytes = rfc8785.dumps(data)

    # SHA-256ハッシュを計算
    hash_digest = hashlib.sha256(canonical_json_bytes).digest()

    # base64url-encodeして返却
    return base64.urlsafe_b64encode(hash_digest).decode('utf-8').rstrip('=')


class MerchantAuthorizationJWT:
    """Merchant Authorization JWT生成・検証クラス

    CartMandateのmerchant_authorizationフィールドに使用されるJWTを生成・検証します。

    JWTペイロード:
    - iss (issuer): Merchantの識別子
    - sub (subject): Merchantの識別子
    - aud (audience): Payment Processorなどの受信者
    - iat (issued at): JWTの作成タイムスタンプ
    - exp (expiration): JWTの有効期限（5-15分推奨）
    - jti (JWT ID): リプレイ攻撃対策用ユニークID
    - cart_hash: CartContentsのCanonical JSONハッシュ
    """

    def __init__(
        self,
        signature_manager: "SignatureManager",
        key_manager: "KeyManager"
    ):
        self.signature_manager = signature_manager
        self.key_manager = key_manager

    def generate(
        self,
        merchant_id: str,
        cart_contents: Dict[str, Any],
        audience: str = "payment_processor",
        expiration_minutes: int = 10,
        algorithm: str = "ECDSA",
        key_id: str = None
    ) -> str:
        """Merchant Authorization JWTを生成

        Args:
            merchant_id: Merchantの識別子（issuerおよびsubjectとして使用）
            cart_contents: CartContentsオブジェクトの辞書表現
            audience: 受信者の識別子（デフォルト: "payment_processor"）
            expiration_minutes: 有効期限（分）（デフォルト: 10分）
            algorithm: 署名アルゴリズム（"ECDSA" または "ED25519"）
            key_id: 署名に使用する鍵のID（デフォルト: merchant_idを使用）

        Returns:
            base64url-encoded JWT文字列
        """
        # AP2完全準拠: key_idが指定されていない場合はmerchant_idを使用
        signing_key_id = key_id if key_id is not None else merchant_id

        # AP2完全準拠: cart_contentsのハッシュを計算（後方互換性のため残す）
        cart_hash = compute_canonical_hash(cart_contents)

        # 現在時刻
        now = datetime.now(timezone.utc)
        iat = int(now.timestamp())
        exp = int((now + timedelta(minutes=expiration_minutes)).timestamp())

        # JWTペイロード
        payload = {
            "iss": merchant_id,
            "sub": merchant_id,
            "aud": audience,
            "iat": iat,
            "exp": exp,
            "jti": str(uuid.uuid4()),
            "cart_hash": cart_hash
        }

        # Headerを生成
        # AP2完全準拠: kidにはDID#fragmentフォーマットが必要
        # ECDSA用は#key-1、Ed25519用は#key-2
        key_fragment = "#key-1" if algorithm == "ECDSA" else "#key-2"
        kid_with_fragment = signing_key_id if "#" in signing_key_id else f"{signing_key_id}{key_fragment}"

        header = {
            "alg": "ES256" if algorithm == "ECDSA" else "EdDSA",
            "typ": "JWT",
            "kid": kid_with_fragment  # AP2完全準拠: DID#fragment形式
        }

        # Header.Payloadをbase64url-encode
        header_b64 = base64.urlsafe_b64encode(
            rfc8785.dumps(header)
        ).decode('utf-8').rstrip('=')

        payload_b64 = base64.urlsafe_b64encode(
            rfc8785.dumps(payload)
        ).decode('utf-8').rstrip('=')

        # 署名対象データ
        signing_input = f"{header_b64}.{payload_b64}"

        # AP2完全準拠: JWT署名では生データに対して直接ECDSA署名を行う（二重ハッシュ化を避ける）
        private_key = self.key_manager.get_private_key(signing_key_id, algorithm=algorithm)
        if private_key is None:
            raise ValueError(f"秘密鍵が見つかりません: {signing_key_id} (algorithm: {algorithm})")

        # ECDSA署名を生成（ec.ECDSA()が内部でSHA256ハッシュ化を行う）
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import hashes

        # pyca/cryptographyはDER形式の署名を返す
        der_signature = private_key.sign(
            signing_input.encode('utf-8'),
            ec.ECDSA(hashes.SHA256())
        )

        # RFC 7515準拠: DER形式からraw R || S (64バイト)形式に変換
        r, s = asym_utils.decode_dss_signature(der_signature)
        # P-256の場合、RとSは各32バイト（256ビット）
        r_bytes = r.to_bytes(32, byteorder='big')
        s_bytes = s.to_bytes(32, byteorder='big')
        raw_signature = r_bytes + s_bytes  # 64バイト

        # 署名をbase64url-encode
        signature_b64 = base64.urlsafe_b64encode(raw_signature).decode('utf-8').rstrip('=')

        # JWT = Header.Payload.Signature
        jwt = f"{header_b64}.{payload_b64}.{signature_b64}"

        return jwt

    def generate_with_hash(
        self,
        merchant_id: str,
        cart_hash: str,
        audience: str = "payment_processor",
        expiration_minutes: int = 10,
        algorithm: str = "ECDSA",
        key_id: str = None
    ) -> str:
        """Merchant Authorization JWTを生成（cart_hashを直接指定）

        AP2完全準拠: CartMandate全体のハッシュを受け取ってJWT生成

        Args:
            merchant_id: Merchantの識別子（issuerおよびsubjectとして使用）
            cart_hash: CartMandateのcanonical hash（compute_mandate_hashで計算済み）
            audience: 受信者の識別子（デフォルト: "payment_processor"）
            expiration_minutes: 有効期限（分）（デフォルト: 10分）
            algorithm: 署名アルゴリズム（"ECDSA" または "ED25519"）
            key_id: 署名に使用する鍵のID（デフォルト: merchant_idを使用）

        Returns:
            base64url-encoded JWT文字列
        """
        # AP2完全準拠: key_idが指定されていない場合はmerchant_idを使用
        signing_key_id = key_id if key_id is not None else merchant_id

        # 現在時刻
        now = datetime.now(timezone.utc)
        iat = int(now.timestamp())
        exp = int((now + timedelta(minutes=expiration_minutes)).timestamp())

        # JWTペイロード
        payload = {
            "iss": merchant_id,
            "sub": merchant_id,
            "aud": audience,
            "iat": iat,
            "exp": exp,
            "jti": str(uuid.uuid4()),
            "cart_hash": cart_hash
        }

        # JWTヘッダー（AP2完全準拠: kidにはDID#fragmentフォーマットが必要）
        key_fragment = "#key-1" if algorithm == "ECDSA" else "#key-2"
        kid_with_fragment = signing_key_id if "#" in signing_key_id else f"{signing_key_id}{key_fragment}"

        header = {
            "alg": "ES256" if algorithm == "ECDSA" else "EdDSA",
            "typ": "JWT",
            "kid": kid_with_fragment
        }

        # RFC 8785準拠のJSON正規化してbase64url-encode
        header_b64 = base64.urlsafe_b64encode(
            rfc8785.dumps(header)
        ).decode('utf-8').rstrip('=')

        payload_b64 = base64.urlsafe_b64encode(
            rfc8785.dumps(payload)
        ).decode('utf-8').rstrip('=')

        # 署名対象データ
        signing_input = f"{header_b64}.{payload_b64}"

        # AP2完全準拠: JWT署名では生データに対して直接ECDSA署名を行う（二重ハッシュ化を避ける）
        private_key = self.key_manager.get_private_key(signing_key_id, algorithm=algorithm)
        if private_key is None:
            raise ValueError(f"秘密鍵が見つかりません: {signing_key_id} (algorithm: {algorithm})")

        # ECDSA署名を生成（ec.ECDSA()が内部でSHA256ハッシュ化を行う）
        # pyca/cryptographyはDER形式の署名を返す
        der_signature = private_key.sign(
            signing_input.encode('utf-8'),
            ec.ECDSA(hashes.SHA256())
        )

        # RFC 7515準拠: DER形式からraw R || S (64バイト)形式に変換
        r, s = asym_utils.decode_dss_signature(der_signature)
        # P-256の場合、RとSは各32バイト（256ビット）
        r_bytes = r.to_bytes(32, byteorder='big')
        s_bytes = s.to_bytes(32, byteorder='big')
        raw_signature = r_bytes + s_bytes  # 64バイト

        # 署名をbase64url-encode
        signature_b64 = base64.urlsafe_b64encode(raw_signature).decode('utf-8').rstrip('=')

        # JWT = Header.Payload.Signature
        jwt = f"{header_b64}.{payload_b64}.{signature_b64}"

        return jwt

    def verify(
        self,
        jwt: str,
        expected_cart_mandate: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Merchant Authorization JWTを検証

        AP2完全準拠: CartMandate全体（署名フィールドを除く）をハッシュ化して検証

        Args:
            jwt: 検証対象のJWT文字列
            expected_cart_mandate: 期待されるCartMandateオブジェクトの辞書表現

        Returns:
            検証済みのJWTペイロード

        Raises:
            ValueError: JWT検証失敗時
        """
        # JWTを分割
        parts = jwt.split('.')
        if len(parts) != 3:
            raise ValueError(f"Invalid JWT format: expected 3 parts, got {len(parts)}")

        header_b64, payload_b64, signature_b64 = parts

        # Base64url-decode
        # Paddingを追加
        header_b64_padded = header_b64 + '=' * (4 - len(header_b64) % 4)
        payload_b64_padded = payload_b64 + '=' * (4 - len(payload_b64) % 4)
        signature_b64_padded = signature_b64 + '=' * (4 - len(signature_b64) % 4)

        import json
        header = json.loads(base64.urlsafe_b64decode(header_b64_padded))
        payload = json.loads(base64.urlsafe_b64decode(payload_b64_padded))
        signature_bytes = base64.urlsafe_b64decode(signature_b64_padded)

        # AP2完全準拠: CartMandate全体（署名フィールドを除く）のハッシュを計算して検証
        from v2.common.user_authorization import compute_mandate_hash
        expected_cart_hash = compute_mandate_hash(expected_cart_mandate)
        if payload.get('cart_hash') != expected_cart_hash:
            raise ValueError(
                f"cart_hash mismatch: expected {expected_cart_hash}, "
                f"got {payload.get('cart_hash')}"
            )

        # 有効期限を検証
        now = int(datetime.now(timezone.utc).timestamp())
        if payload.get('exp', 0) < now:
            raise ValueError(f"JWT expired at {payload.get('exp')}")

        # 署名を検証（SignatureManagerを使用）
        signing_input = f"{header_b64}.{payload_b64}"

        # ヘッダーからkidとalgを取得
        kid = header.get('kid')
        alg = header.get('alg')

        if not kid:
            raise ValueError("JWT header missing 'kid' field")

        # SignatureオブジェクトをAP2準拠形式で構築
        from common.models import Signature

        # 公開鍵を取得（kidから）
        try:
            public_key = self.key_manager.load_public_key(kid)
            public_key_b64 = self.key_manager.public_key_to_base64(public_key)
        except Exception as e:
            raise ValueError(f"Failed to load public key for kid={kid}: {e}")

        # アルゴリズム名を変換（ES256 -> ECDSA, EdDSA -> Ed25519）
        algorithm = "ECDSA" if alg == "ES256" else "Ed25519"

        # RFC 7515準拠: raw R || S (64バイト)形式からDER形式に変換
        if len(signature_bytes) != 64:
            raise ValueError(f"Invalid ES256 signature length: expected 64 bytes, got {len(signature_bytes)}")

        # 前半32バイト = R、後半32バイト = S
        r_bytes = signature_bytes[:32]
        s_bytes = signature_bytes[32:]
        r = int.from_bytes(r_bytes, byteorder='big')
        s = int.from_bytes(s_bytes, byteorder='big')

        # DER形式に変換
        der_signature = asym_utils.encode_dss_signature(r, s)

        # AP2完全準拠: JWT検証では生データに対して直接ECDSA署名検証を行う（二重ハッシュ化を避ける）
        try:
            # ECDSA署名を検証（ec.ECDSA()が内部でSHA256ハッシュ化を行う）
            public_key.verify(
                der_signature,
                signing_input.encode('utf-8'),
                ec.ECDSA(hashes.SHA256())
            )
        except Exception as e:
            raise ValueError(f"JWT signature verification failed for kid={kid}: {e}")

        return payload


class UserAuthorizationSDJWT:
    """User Authorization SD-JWT-VC生成・検証クラス

    PaymentMandateのuser_authorizationフィールドに使用されるSD-JWT-VCを生成・検証します。

    SD-JWT-VC構成:
    1. Issuer-signed JWT: 'cnf' claimを承認
    2. Key-binding JWT:
       - aud (audience)
       - nonce: リプレイ攻撃対策
       - sd_hash: Issuer-signed JWTのハッシュ
       - transaction_data: CartMandateとPaymentMandateContentsのハッシュ配列
    """

    def __init__(
        self,
        signature_manager: "SignatureManager",
        key_manager: "KeyManager"
    ):
        self.signature_manager = signature_manager
        self.key_manager = key_manager

    def generate(
        self,
        user_id: str,
        cart_mandate: Dict[str, Any],
        payment_mandate_contents: Dict[str, Any],
        audience: str,
        nonce: str,
        algorithm: str = "ECDSA"
    ) -> str:
        """User Authorization SD-JWT-VCを生成

        Args:
            user_id: ユーザーの識別子
            cart_mandate: CartMandateオブジェクトの辞書表現
            payment_mandate_contents: PaymentMandateContentsオブジェクトの辞書表現
            audience: オーディエンス（Payment Processorなど）
            nonce: リプレイ攻撃対策用nonce
            algorithm: 署名アルゴリズム（"ECDSA" または "ED25519"）

        Returns:
            標準SD-JWT-VC形式文字列（~区切り）: <issuer-jwt>~<kb-jwt>~
        """
        # 1. Issuer-signed JWTを生成
        issuer_payload = {
            "iss": user_id,
            "sub": user_id,
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "cnf": {
                "kid": user_id
            }
        }

        issuer_header = {
            "alg": "ES256" if algorithm == "ECDSA" else "EdDSA",
            "typ": "JWT",
            "kid": user_id
        }

        issuer_header_b64 = base64.urlsafe_b64encode(
            rfc8785.dumps(issuer_header)
        ).decode('utf-8').rstrip('=')

        issuer_payload_b64 = base64.urlsafe_b64encode(
            rfc8785.dumps(issuer_payload)
        ).decode('utf-8').rstrip('=')

        issuer_signing_input = f"{issuer_header_b64}.{issuer_payload_b64}"

        issuer_signature = self.signature_manager.sign_data(
            issuer_signing_input.encode('utf-8'),
            user_id,
            algorithm=algorithm
        )

        issuer_signature_b64 = base64.urlsafe_b64encode(
            bytes.fromhex(issuer_signature.signature)
        ).decode('utf-8').rstrip('=')

        issuer_jwt = f"{issuer_header_b64}.{issuer_payload_b64}.{issuer_signature_b64}"

        # 2. Key-binding JWTを生成
        # transaction_dataハッシュを計算
        cart_hash = compute_canonical_hash(cart_mandate)
        payment_hash = compute_canonical_hash(payment_mandate_contents)

        # sd_hashを計算（Issuer-signed JWTのハッシュ）
        sd_hash = base64.urlsafe_b64encode(
            hashlib.sha256(issuer_jwt.encode('utf-8')).digest()
        ).decode('utf-8').rstrip('=')

        kb_payload = {
            "aud": audience,
            "nonce": nonce,
            "sd_hash": sd_hash,
            "transaction_data": [cart_hash, payment_hash]
        }

        kb_header = {
            "alg": "ES256" if algorithm == "ECDSA" else "EdDSA",
            "typ": "kb+jwt",
            "kid": user_id
        }

        kb_header_b64 = base64.urlsafe_b64encode(
            rfc8785.dumps(kb_header)
        ).decode('utf-8').rstrip('=')

        kb_payload_b64 = base64.urlsafe_b64encode(
            rfc8785.dumps(kb_payload)
        ).decode('utf-8').rstrip('=')

        kb_signing_input = f"{kb_header_b64}.{kb_payload_b64}"

        kb_signature = self.signature_manager.sign_data(
            kb_signing_input.encode('utf-8'),
            user_id,
            algorithm=algorithm
        )

        kb_signature_b64 = base64.urlsafe_b64encode(
            bytes.fromhex(kb_signature.signature)
        ).decode('utf-8').rstrip('=')

        kb_jwt = f"{kb_header_b64}.{kb_payload_b64}.{kb_signature_b64}"

        # 3. 標準SD-JWT-VC形式を返却: <issuer-jwt>~<kb-jwt>~
        return f"{issuer_jwt}~{kb_jwt}~"

    def verify(
        self,
        sd_jwt_vc: str,
        expected_cart_mandate: Dict[str, Any],
        expected_payment_mandate_contents: Dict[str, Any],
        expected_nonce: str
    ) -> Dict[str, Any]:
        """User Authorization SD-JWT-VCを検証

        Args:
            sd_jwt_vc: 検証対象のSD-JWT-VC文字列（~区切り）
            expected_cart_mandate: 期待されるCartMandateオブジェクトの辞書表現
            expected_payment_mandate_contents: 期待されるPaymentMandateContentsオブジェクトの辞書表現
            expected_nonce: 期待されるnonce

        Returns:
            検証済みのKey-binding JWTペイロード

        Raises:
            ValueError: SD-JWT-VC検証失敗時
        """
        # SD-JWT-VC形式を分割: <issuer-jwt>~<kb-jwt>~
        parts = sd_jwt_vc.split('~')
        if len(parts) < 2:
            raise ValueError(f"Invalid SD-JWT-VC format: expected at least 2 parts, got {len(parts)}")

        issuer_jwt = parts[0]
        kb_jwt = parts[1]

        # Key-binding JWTを検証
        kb_parts = kb_jwt.split('.')
        if len(kb_parts) != 3:
            raise ValueError(f"Invalid Key-binding JWT format: expected 3 parts, got {len(kb_parts)}")

        kb_header_b64, kb_payload_b64, kb_signature_b64 = kb_parts

        # Base64url-decode（Paddingを追加）
        kb_header_b64_padded = kb_header_b64 + '=' * (4 - len(kb_header_b64) % 4)
        kb_payload_b64_padded = kb_payload_b64 + '=' * (4 - len(kb_payload_b64) % 4)

        import json
        kb_payload = json.loads(base64.urlsafe_b64decode(kb_payload_b64_padded))

        # nonceを検証
        if kb_payload.get('nonce') != expected_nonce:
            raise ValueError(
                f"nonce mismatch: expected {expected_nonce}, "
                f"got {kb_payload.get('nonce')}"
            )

        # transaction_dataを検証
        expected_cart_hash = compute_canonical_hash(expected_cart_mandate)
        expected_payment_hash = compute_canonical_hash(expected_payment_mandate_contents)
        expected_transaction_data = [expected_cart_hash, expected_payment_hash]

        if kb_payload.get('transaction_data') != expected_transaction_data:
            raise ValueError(
                f"transaction_data mismatch: expected {expected_transaction_data}, "
                f"got {kb_payload.get('transaction_data')}"
            )

        # sd_hashを検証
        expected_sd_hash = base64.urlsafe_b64encode(
            hashlib.sha256(issuer_jwt.encode('utf-8')).digest()
        ).decode('utf-8').rstrip('=')

        if kb_payload.get('sd_hash') != expected_sd_hash:
            raise ValueError(
                f"sd_hash mismatch: expected {expected_sd_hash}, "
                f"got {kb_payload.get('sd_hash')}"
            )

        # Key-binding JWTの署名を検証（SignatureManagerを使用）
        kb_header_b64_padded = kb_header_b64 + '=' * (4 - len(kb_header_b64) % 4)
        kb_header = json.loads(base64.urlsafe_b64decode(kb_header_b64_padded))

        kb_signature_b64_padded = kb_signature_b64 + '=' * (4 - len(kb_signature_b64) % 4)
        kb_signature_bytes = base64.urlsafe_b64decode(kb_signature_b64_padded)

        # ヘッダーからkidとalgを取得
        kid = kb_header.get('kid')
        alg = kb_header.get('alg')

        if not kid:
            raise ValueError("Key-binding JWT header missing 'kid' field")

        # SignatureオブジェクトをAP2準拠形式で構築
        from common.models import Signature

        # 公開鍵を取得（kidから）
        try:
            public_key = self.key_manager.load_public_key(kid)
            public_key_b64 = self.key_manager.public_key_to_base64(public_key)
        except Exception as e:
            raise ValueError(f"Failed to load public key for kid={kid}: {e}")

        # アルゴリズム名を変換（ES256 -> ECDSA, EdDSA -> Ed25519）
        algorithm = "ECDSA" if alg == "ES256" else "Ed25519"

        kb_signature_obj = Signature(
            algorithm=algorithm,
            key_id=kid,
            public_key=public_key_b64,
            signature=kb_signature_bytes.hex()  # hex形式で格納
        )

        # 署名対象データ
        kb_signing_input = f"{kb_header_b64}.{kb_payload_b64}"

        # SignatureManagerで検証（signing_inputをbytesで渡す）
        is_valid = self.signature_manager.verify_signature(
            kb_signing_input.encode('utf-8'),
            kb_signature_obj
        )

        if not is_valid:
            raise ValueError(f"Key-binding JWT signature verification failed for kid={kid}")

        return kb_payload
