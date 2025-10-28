"""
v2/services/shopping_agent/utils/signature_handlers.py

WebAuthn署名・Attestation検証処理のヘルパーメソッド
"""

import logging
from typing import Dict, Any, Optional
import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)


class SignatureHandlers:
    """WebAuthn署名検証に関連するヘルパーメソッドを提供するクラス"""

    @staticmethod
    async def verify_cart_signature_with_cp(
        http_client: httpx.AsyncClient,
        credential_provider_url: str,
        cart_mandate: Dict[str, Any],
        webauthn_assertion: Dict[str, Any],
        user_id: str
    ) -> Dict[str, Any]:
        """
        Credential ProviderでCartMandate用のWebAuthn署名を検証

        Args:
            http_client: HTTPクライアント
            credential_provider_url: Credential Provider URL
            cart_mandate: CartMandate
            webauthn_assertion: WebAuthn assertion
            user_id: ユーザーID

        Returns:
            Dict[str, Any]: 検証結果

        Raises:
            HTTPException: 検証失敗時
        """
        logger.info(
            f"[SignatureHandlers] Verifying CartMandate WebAuthn signature: user_id={user_id}"
        )

        try:
            # Credential Providerに署名検証をリクエスト（AP2完全準拠）
            # /verify/attestation エンドポイントを使用
            # payment_mandateフィールドにcart_mandateを渡す（検証ロジックは共通）
            verification_response = await http_client.post(
                f"{credential_provider_url}/verify/attestation",
                json={
                    "payment_mandate": cart_mandate,  # 検証対象のMandate
                    "attestation": webauthn_assertion   # WebAuthn assertion
                }
            )

            logger.info(
                f"[SignatureHandlers] Sent WebAuthn verification request to Credential Provider: "
                f"user_id={user_id}"
            )

            if verification_response.status_code != 200:
                logger.error(
                    f"[SignatureHandlers] WebAuthn verification failed: "
                    f"status={verification_response.status_code}"
                )
                raise HTTPException(
                    status_code=400,
                    detail="WebAuthn signature verification failed"
                )

            verification_result = verification_response.json()

            if not verification_result.get("verified"):
                logger.error(
                    f"[SignatureHandlers] WebAuthn verification returned false: "
                    f"{verification_result.get('details')}"
                )
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid WebAuthn signature: {verification_result.get('details', {}).get('error')}"
                )

            logger.info(
                f"[SignatureHandlers] ✅ WebAuthn signature verified successfully: "
                f"counter={verification_result.get('details', {}).get('counter')}, "
                f"attestation_type={verification_result.get('details', {}).get('attestation_type')}"
            )

            return verification_result

        except httpx.HTTPError as e:
            logger.error(
                f"[SignatureHandlers] Failed to communicate with Credential Provider: {e}",
                exc_info=True
            )
            raise HTTPException(
                status_code=503,
                detail=f"Credential Provider unavailable: {e}"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                f"[SignatureHandlers] WebAuthn verification error: {e}",
                exc_info=True
            )
            raise HTTPException(
                status_code=500,
                detail=f"WebAuthn verification failed: {e}"
            )

    @staticmethod
    async def verify_payment_attestation_with_cp(
        http_client: httpx.AsyncClient,
        credential_provider_url: str,
        payment_mandate: Dict[str, Any],
        attestation: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Credential ProviderでPaymentMandate用のWebAuthn attestationを検証

        Args:
            http_client: HTTPクライアント
            credential_provider_url: Credential Provider URL
            payment_mandate: PaymentMandate
            attestation: WebAuthn attestation

        Returns:
            Dict[str, Any]: 検証結果（verified, token, detailsなど）

        Raises:
            Exception: 検証失敗時
        """
        logger.info(
            f"[SignatureHandlers] Verifying PaymentMandate attestation: "
            f"payment_id={payment_mandate.get('id')}"
        )

        try:
            verification_response = await http_client.post(
                f"{credential_provider_url}/verify/attestation",
                json={
                    "payment_mandate": payment_mandate,
                    "attestation": attestation
                }
            )
            verification_response.raise_for_status()
            verification_result = verification_response.json()

            if verification_result.get("verified"):
                logger.info(
                    f"[SignatureHandlers] ✅ PaymentMandate attestation verified: "
                    f"payment_id={payment_mandate.get('id')}"
                )
            else:
                logger.warning(
                    f"[SignatureHandlers] ❌ PaymentMandate attestation verification failed: "
                    f"details={verification_result.get('details')}"
                )

            return verification_result

        except httpx.HTTPError as e:
            logger.error(
                f"[SignatureHandlers] HTTP error during attestation verification: {e}",
                exc_info=True
            )
            raise
        except Exception as e:
            logger.error(
                f"[SignatureHandlers] Error during attestation verification: {e}",
                exc_info=True
            )
            raise

    @staticmethod
    async def retrieve_public_key_from_cp(
        http_client: httpx.AsyncClient,
        credential_provider_url: str,
        credential_id: str,
        user_id: str,
        timeout: float = 10.0
    ) -> Optional[str]:
        """
        Credential ProviderからWebAuthn公開鍵を取得

        Args:
            http_client: HTTPクライアント
            credential_provider_url: Credential Provider URL
            credential_id: Credential ID
            user_id: ユーザーID
            timeout: リクエストタイムアウト（秒）

        Returns:
            Optional[str]: COSE形式の公開鍵（取得失敗時はNone）
        """
        if not credential_id:
            logger.warning("[SignatureHandlers] No credential_id provided")
            return None

        try:
            logger.info(
                f"[SignatureHandlers] Retrieving public key from Credential Provider: "
                f"credential_id={credential_id[:16]}..., user_id={user_id}"
            )

            public_key_response = await http_client.post(
                f"{credential_provider_url}/passkey/get-public-key",
                json={"credential_id": credential_id, "user_id": user_id},
                timeout=timeout
            )
            public_key_response.raise_for_status()
            public_key_data = public_key_response.json()
            public_key_cose = public_key_data.get("public_key_cose")

            logger.info(
                f"[SignatureHandlers] ✅ Public key retrieved: "
                f"credential_id={credential_id[:16]}..."
            )

            return public_key_cose

        except httpx.HTTPError as e:
            logger.warning(
                f"[SignatureHandlers] HTTP error retrieving public key: {e}"
            )
            return None
        except Exception as e:
            logger.warning(
                f"[SignatureHandlers] Failed to retrieve public key from CP: {e}"
            )
            return None
