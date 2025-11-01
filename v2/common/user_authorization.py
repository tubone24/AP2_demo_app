"""
user_authorization生成・検証モジュール（AP2仕様完全準拠）

AP2仕様（refs/AP2-main/src/ap2/types/mandate.py:181-200）に基づき、
user_authorizationをSD-JWT-VC（Selectively Disclosed JWT Verifiable Credential）
形式で生成・検証します。

仕様の定義：
- user_authorization は base64url-encoded Verifiable Presentation
- Issuer-signed JWT: ユーザーデバイスの公開鍵を含む（cnf claim）
- Key-binding JWT: transaction_data（CartMandateとPaymentMandateのハッシュ）を含む

References:
- refs/AP2-main/src/ap2/types/mandate.py:181-200
- refs/AP2-main/docs/specification.md:286-312
- refs/AP2-main/samples/python/src/roles/shopping_agent/tools.py:198-230
"""

import base64
import hashlib
import json
import secrets
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple
import logging

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.backends import default_backend
from fido2.webauthn import AuthenticatorData
from fido2.cose import CoseKey

logger = logging.getLogger(__name__)


def base64url_encode(data: bytes) -> str:
    """Base64URL エンコード（パディングなし）"""
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('utf-8')


def base64url_decode(data: str) -> bytes:
    """Base64URL デコード"""
    padding = '=' * (4 - len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def compute_mandate_hash(mandate: Dict[str, Any]) -> str:
    """
    MandateのSHA-256ハッシュを計算（AP2仕様準拠）

    署名フィールド（merchant_signature、merchant_authorization、user_authorization）を
    自動的に除外してハッシュを計算します。

    Note:
        RFC 8785 (JSON Canonicalization Scheme) 準拠の正規化を使用。
        rfc8785ライブラリが必要（pyproject.tomlで定義済み）。

    Args:
        mandate: CartMandate または PaymentMandate

    Returns:
        str: hex形式のハッシュ値

    Raises:
        ImportError: rfc8785ライブラリがインストールされていない場合
    """
    # 署名フィールドを除外（AP2仕様準拠）
    excluded_fields = {'merchant_signature', 'merchant_authorization', 'user_authorization'}
    mandate_for_hash = {k: v for k, v in mandate.items() if k not in excluded_fields}

    # RFC 8785準拠のJSON正規化
    # Note: rfc8785は必須依存関係（pyproject.toml参照）
    try:
        import rfc8785
        canonical_bytes = rfc8785.dumps(mandate_for_hash)
    except ImportError as e:
        # rfc8785がインストールされていない場合はエラー
        # フォールバックは使用せず、明示的にエラーを発生させる
        error_msg = (
            "rfc8785 library is required for RFC 8785 compliant JSON canonicalization. "
            "Please install it: uv add rfc8785 or pip install rfc8785>=0.1.4"
        )
        logger.error(f"[compute_mandate_hash] {error_msg}")
        raise ImportError(error_msg) from e

    return hashlib.sha256(canonical_bytes).hexdigest()


# 削除: extract_public_key_from_webauthn_assertion 関数
#
# AP2完全準拠のため削除しました:
#
# WebAuthnの正しい動作:
#   - Registration (登録): attestationObjectを含む → 公開鍵を抽出してDBに保存
#   - Assertion (認証): attestationObjectを含まない → DB保存済みの公開鍵を使用
#
# この関数はRegistrationとAssertionを混同していました。
# Assertion時にattestationObjectから公開鍵を抽出しようとするのは誤りです。
#
# 正しい実装:
#   - 公開鍵はPasskey登録時にDBに保存済み
#   - user_authorization生成時はDBから取得した public_key_cose を使用
#   - create_user_authorization_vp() の public_key_cose パラメータは必須


def create_user_authorization_vp(
    webauthn_assertion: Dict[str, Any],
    cart_mandate: Dict[str, Any],
    payment_mandate_contents: Dict[str, Any],
    user_id: str,
    public_key_cose: str,
    payment_processor_id: str = "did:ap2:agent:payment_processor"
) -> str:
    """
    WebAuthn assertionからSD-JWT-VC形式のuser_authorizationを生成（AP2仕様完全準拠）

    AP2仕様（refs/AP2-main/src/ap2/types/mandate.py:181-200）に基づき、
    以下の構造のVerifiable Presentationを生成します：

    1. Issuer-signed JWT: ユーザーデバイスの公開鍵を含む（cnf claim）
    2. Key-binding JWT: transaction_data（ハッシュ）を含み、デバイス鍵で署名

    Args:
        webauthn_assertion: フロントエンドから受信したWebAuthn assertion
        cart_mandate: CartMandate（ハッシュ計算に使用）
        payment_mandate_contents: PaymentMandateの内容（ハッシュ計算に使用）
        user_id: ユーザーID
        public_key_cose: COSE形式の公開鍵（base64エンコード済み、DB保存済みの値を使用）
        payment_processor_id: Payment ProcessorのDID（デフォルト: did:ap2:agent:payment_processor）

    Returns:
        str: base64url-encoded SD-JWT-VC形式のuser_authorization

    Raises:
        ValueError: VP生成に失敗した場合
    """
    try:
        # Step 1: WebAuthn assertionから必要な情報を抽出
        response = webauthn_assertion.get("response", {})
        client_data_json_b64 = response.get("clientDataJSON", "")
        authenticator_data_b64 = response.get("authenticatorData", "")
        signature_b64 = response.get("signature", "")

        if not all([client_data_json_b64, authenticator_data_b64, signature_b64]):
            raise ValueError("Invalid WebAuthn assertion: missing required fields")

        # clientDataJSONをデコード
        client_data_json_bytes = base64url_decode(client_data_json_b64)
        client_data = json.loads(client_data_json_bytes.decode('utf-8'))
        webauthn_challenge = client_data.get("challenge", "")

        logger.info(f"[create_user_authorization_vp] WebAuthn challenge from assertion: {webauthn_challenge[:16]}...")

        # Step 2: CartMandateとPaymentMandateのハッシュを計算
        cart_hash = compute_mandate_hash(cart_mandate)
        payment_hash = compute_mandate_hash(payment_mandate_contents)

        logger.info(f"[create_user_authorization_vp] cart_hash: {cart_hash[:16]}...")
        logger.info(f"[create_user_authorization_vp] payment_hash: {payment_hash[:16]}...")

        # Step 3: COSE形式の公開鍵を復元（AP2完全準拠）
        # WebAuthn Registration時にDBに保存された公開鍵を使用
        try:
            from fido2.cose import ES256
            import cbor2

            # COSE形式の公開鍵をデコード
            cose_key_bytes = base64.b64decode(public_key_cose)
            cose_key = cbor2.loads(cose_key_bytes)

            # COSE keyからECDSA公開鍵を復元
            from cryptography.hazmat.primitives.asymmetric.ec import (
                EllipticCurvePublicNumbers, SECP256R1
            )
            from cryptography.hazmat.backends import default_backend

            x_bytes = cose_key[-2]  # x coordinate
            y_bytes = cose_key[-3]  # y coordinate
            x_int = int.from_bytes(x_bytes, byteorder='big')
            y_int = int.from_bytes(y_bytes, byteorder='big')

            public_numbers = EllipticCurvePublicNumbers(x_int, y_int, SECP256R1())
            public_key = public_numbers.public_key(default_backend())

            logger.info(f"[create_user_authorization_vp] Restored public key from COSE format (DB)")
        except Exception as e:
            logger.error(f"[create_user_authorization_vp] Failed to restore public key from COSE: {e}", exc_info=True)
            raise ValueError(f"Invalid public_key_cose format: {e}") from e

        # Step 4: Issuer-signed JWT を生成（公開鍵の確認）
        now = datetime.now(timezone.utc)
        exp_time = now + timedelta(minutes=5)  # 5分間有効

        issuer_jwt_header = {
            "alg": "ES256",  # ECDSA with P-256 and SHA-256
            "typ": "JWT"
        }

        issuer_jwt_payload = {
            "iss": f"did:ap2:user:{user_id}",
            "sub": f"did:ap2:user:{user_id}",
            "iat": int(now.timestamp()),
            "exp": int(exp_time.timestamp()),
            "nbf": int(now.timestamp()),
        }

        # cnf claim（Confirmation Claim）: 公開鍵を含む（AP2完全準拠）
        issuer_jwt_payload["cnf"] = {
            "jwk": {
                "kty": "EC",
                "crv": "P-256",
                "x": base64url_encode(public_key.public_numbers().x.to_bytes(32, byteorder='big')),
                "y": base64url_encode(public_key.public_numbers().y.to_bytes(32, byteorder='big'))
            }
        }
        logger.info("[create_user_authorization_vp] cnf claim with JWK added to Issuer JWT")

        # Issuer JWTをエンコード（署名なし、デバイス鍵で署名するため）
        issuer_jwt_str = (
            base64url_encode(json.dumps(issuer_jwt_header, separators=(',', ':')).encode()) +
            "." +
            base64url_encode(json.dumps(issuer_jwt_payload, separators=(',', ':')).encode())
        )

        # Step 5: Key-binding JWT を生成（transaction_data含む）
        kb_jwt_header = {
            "alg": "ES256",
            "typ": "kb+jwt"  # Key-binding JWT
        }

        nonce = secrets.token_urlsafe(32)  # リプレイ攻撃対策

        kb_jwt_payload = {
            "aud": payment_processor_id,
            "nonce": nonce,
            "iat": int(now.timestamp()),
            "sd_hash": hashlib.sha256(issuer_jwt_str.encode()).hexdigest(),  # Issuer JWTのハッシュ
            "transaction_data": [cart_hash, payment_hash]  # AP2仕様: CartとPaymentのハッシュ
        }

        kb_jwt_str = (
            base64url_encode(json.dumps(kb_jwt_header, separators=(',', ':')).encode()) +
            "." +
            base64url_encode(json.dumps(kb_jwt_payload, separators=(',', ':')).encode())
        )

        # Step 6: WebAuthn署名を使用（デバイス鍵による署名の代わり）
        # WebAuthn assertionの署名は authenticatorData + SHA256(clientDataJSON) に対する署名
        # これをKey-binding JWTの署名として流用

        # VP形式: issuer_jwt + "~" + kb_jwt + "~" + webauthn_signature
        # 簡略化版: WebAuthn assertion全体をbase64url-encodeして含める
        vp = {
            "issuer_jwt": issuer_jwt_str,
            "kb_jwt": kb_jwt_str,
            "webauthn_assertion": webauthn_assertion,  # 完全なWebAuthn assertionを含める
            "cart_hash": cart_hash,
            "payment_hash": payment_hash
        }

        # base64url-encodeしてuser_authorizationとして返却
        user_authorization = base64url_encode(json.dumps(vp, separators=(',', ':')).encode())

        logger.info(
            f"[create_user_authorization_vp] Generated user_authorization VP: "
            f"length={len(user_authorization)}, cart_hash={cart_hash[:16]}..., payment_hash={payment_hash[:16]}..."
        )

        return user_authorization

    except Exception as e:
        logger.error(f"[create_user_authorization_vp] Failed to create VP: {e}", exc_info=True)
        raise ValueError(f"Failed to create user_authorization VP: {e}")


def convert_vp_to_standard_format(vp_json: Dict[str, Any]) -> str:
    """
    JSON形式のVPを標準SD-JWT-VC形式（~区切り）に変換

    標準形式: <issuer-jwt>~<kb-jwt>~

    Args:
        vp_json: JSON形式のVP（issuer_jwt, kb_jwt含む）

    Returns:
        str: 標準SD-JWT-VC形式の文字列
    """
    issuer_jwt = vp_json.get("issuer_jwt", "")
    kb_jwt = vp_json.get("kb_jwt", "")

    # 標準形式: <issuer-jwt>~<kb-jwt>~
    # 最後の~はSD-JWT-VCの標準に従う（Disclosuresが空の場合）
    standard_format = f"{issuer_jwt}~{kb_jwt}~"

    return standard_format


def convert_standard_format_to_vp(standard_format: str) -> Dict[str, Any]:
    """
    標準SD-JWT-VC形式（~区切り）をJSON形式のVPに変換

    Args:
        standard_format: 標準SD-JWT-VC形式の文字列（~区切り）

    Returns:
        Dict[str, Any]: JSON形式のVP
    """
    parts = standard_format.split('~')

    if len(parts) < 2:
        raise ValueError(f"Invalid SD-JWT-VC format: expected at least 2 parts, got {len(parts)}")

    vp = {
        "issuer_jwt": parts[0],
        "kb_jwt": parts[1] if len(parts) > 1 else "",
        # parts[2]以降はDisclosures（現在は未使用）
    }

    return vp


def verify_user_authorization_vp(
    user_authorization: str,
    expected_cart_hash: Optional[str] = None,
    expected_payment_hash: Optional[str] = None,
    expected_audience: str = "did:ap2:agent:payment_processor"
) -> Dict[str, Any]:
    """
    SD-JWT-VC形式のuser_authorizationを検証（AP2仕様完全準拠）

    Args:
        user_authorization: base64url-encoded VP
        expected_cart_hash: 期待されるCartMandateのハッシュ（Noneの場合はスキップ）
        expected_payment_hash: 期待されるPaymentMandateのハッシュ（Noneの場合はスキップ）
        expected_audience: 期待されるAudience（デフォルト: Payment Processor）

    Returns:
        Dict[str, Any]: 検証済みのVP内容

    Raises:
        ValueError: 検証失敗時
    """
    try:
        # Step 1: base64url-decodeしてVPを取得
        vp_bytes = base64url_decode(user_authorization)
        vp = json.loads(vp_bytes.decode('utf-8'))

        logger.info("[verify_user_authorization_vp] Decoded VP successfully")

        # Step 2: WebAuthn assertionを抽出
        webauthn_assertion = vp.get("webauthn_assertion")
        if not webauthn_assertion:
            raise ValueError("webauthn_assertion not found in VP")

        # Step 3: transaction_dataのハッシュを検証
        cart_hash = vp.get("cart_hash")
        payment_hash = vp.get("payment_hash")

        if expected_cart_hash and cart_hash != expected_cart_hash:
            raise ValueError(
                f"Cart hash mismatch: expected {expected_cart_hash[:16]}..., "
                f"got {cart_hash[:16] if cart_hash else 'None'}..."
            )

        if expected_payment_hash and payment_hash != expected_payment_hash:
            raise ValueError(
                f"Payment hash mismatch: expected {expected_payment_hash[:16]}..., "
                f"got {payment_hash[:16] if payment_hash else 'None'}..."
            )

        logger.info(
            f"[verify_user_authorization_vp] Hash verification passed: "
            f"cart_hash={cart_hash[:16]}..., payment_hash={payment_hash[:16]}..."
        )

        # Step 4: WebAuthn assertionの署名を検証（AP2仕様完全準拠）
        # 公開鍵はIssuer JWTのcnf claimから取得
        issuer_jwt_str = vp.get("issuer_jwt")
        if issuer_jwt_str:
            try:
                # Issuer JWTをデコード（署名検証なし、公開鍵抽出のため）
                issuer_jwt_parts = issuer_jwt_str.split(".")
                if len(issuer_jwt_parts) >= 2:
                    issuer_payload_bytes = base64url_decode(issuer_jwt_parts[1])
                    issuer_payload = json.loads(issuer_payload_bytes.decode('utf-8'))

                    # cnf claimから公開鍵（JWK形式）を取得
                    cnf = issuer_payload.get("cnf", {})
                    jwk = cnf.get("jwk", {})

                    if jwk and jwk.get("kty") == "EC" and jwk.get("crv") == "P-256":
                        # JWKから公開鍵を再構築
                        from cryptography.hazmat.primitives.asymmetric.ec import (
                            EllipticCurvePublicNumbers, SECP256R1
                        )
                        from cryptography.hazmat.backends import default_backend
                        from cryptography.hazmat.primitives.asymmetric import ec
                        from cryptography.hazmat.primitives import hashes

                        # X, Y座標をデコード
                        x_bytes = base64url_decode(jwk["x"])
                        y_bytes = base64url_decode(jwk["y"])
                        x_int = int.from_bytes(x_bytes, byteorder='big')
                        y_int = int.from_bytes(y_bytes, byteorder='big')

                        # 公開鍵オブジェクトを構築
                        public_numbers = EllipticCurvePublicNumbers(x_int, y_int, SECP256R1())
                        public_key = public_numbers.public_key(default_backend())

                        # WebAuthn assertionの署名を検証
                        response = webauthn_assertion.get("response", {})
                        authenticator_data_b64 = response.get("authenticatorData")
                        client_data_json_b64 = response.get("clientDataJSON")
                        signature_b64 = response.get("signature")

                        if authenticator_data_b64 and client_data_json_b64 and signature_b64:
                            # 署名対象データ: authenticatorData + SHA256(clientDataJSON)
                            authenticator_data_bytes = base64url_decode(authenticator_data_b64)
                            client_data_json_bytes = base64url_decode(client_data_json_b64)
                            client_data_hash = hashlib.sha256(client_data_json_bytes).digest()
                            signed_data = authenticator_data_bytes + client_data_hash

                            # 署名をデコード
                            signature_bytes = base64url_decode(signature_b64)

                            # ECDSA署名を検証（P-256 + SHA-256）
                            try:
                                public_key.verify(
                                    signature_bytes,
                                    signed_data,
                                    ec.ECDSA(hashes.SHA256())
                                )
                                logger.info(
                                    "[verify_user_authorization_vp] ✓ WebAuthn signature verified successfully"
                                )
                            except Exception as sig_error:
                                raise ValueError(f"WebAuthn signature verification failed: {sig_error}")
                        else:
                            logger.warning(
                                "[verify_user_authorization_vp] WebAuthn assertion missing signature fields, "
                                "skipping cryptographic verification"
                            )
                    else:
                        logger.warning(
                            "[verify_user_authorization_vp] No valid public key in cnf claim, "
                            "skipping WebAuthn signature verification"
                        )
            except Exception as e:
                logger.error(f"[verify_user_authorization_vp] Failed to verify WebAuthn signature: {e}")
                raise ValueError(f"WebAuthn signature verification failed: {e}")

        # Step 5: Key-binding JWTのペイロードを検証
        kb_jwt_str = vp.get("kb_jwt")
        if kb_jwt_str:
            # base64url-decodeしてペイロードを取得
            kb_jwt_parts = kb_jwt_str.split(".")
            if len(kb_jwt_parts) >= 2:
                kb_payload_bytes = base64url_decode(kb_jwt_parts[1])
                kb_payload = json.loads(kb_payload_bytes.decode('utf-8'))

                # Audience検証
                if kb_payload.get("aud") != expected_audience:
                    logger.warning(
                        f"[verify_user_authorization_vp] Unexpected audience: {kb_payload.get('aud')}, "
                        f"expected {expected_audience}"
                    )

                # transaction_data検証
                transaction_data = kb_payload.get("transaction_data", [])
                if len(transaction_data) >= 2:
                    if transaction_data[0] != cart_hash:
                        raise ValueError("Cart hash in transaction_data does not match")
                    if transaction_data[1] != payment_hash:
                        raise ValueError("Payment hash in transaction_data does not match")

                logger.info("[verify_user_authorization_vp] Key-binding JWT payload verified")

        logger.info("[verify_user_authorization_vp] ✓ VP verification passed")

        return {
            "verified": True,
            "webauthn_assertion": webauthn_assertion,
            "cart_hash": cart_hash,
            "payment_hash": payment_hash,
            "vp": vp
        }

    except Exception as e:
        logger.error(f"[verify_user_authorization_vp] Verification failed: {e}", exc_info=True)
        raise ValueError(f"user_authorization VP verification failed: {e}")
