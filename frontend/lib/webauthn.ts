/**
 * WebAuthn/Passkey関連のヘルパー関数
 * demo_app_v2.mdのWebAuthn仕様に準拠
 */

import { WebAuthnAttestation } from "./types/chat";

// Base64URL エンコード
function bufferToBase64URL(buffer: ArrayBuffer | Uint8Array): string {
  const bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");
}

// Base64URL デコード
function base64URLToBuffer(base64url: string): ArrayBuffer {
  const base64 = base64url.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

// チャレンジ生成
export function generateChallenge(): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(32));
}

// Passkey認証（署名用）
export async function signWithPasskey(
  challenge: string,
  rpId: string = "localhost"
): Promise<WebAuthnAttestation> {
  if (!window.PublicKeyCredential) {
    throw new Error("WebAuthn is not supported in this browser");
  }

  // チャレンジをArrayBufferに変換
  const challengeBuffer = base64URLToBuffer(challenge);

  // AP2完全準拠：ユーザー検証は"required"（生体認証必須）
  // AP2仕様: Strong Authentication（WebAuthn Level 2準拠）
  const publicKeyCredentialRequestOptions: PublicKeyCredentialRequestOptions = {
    challenge: challengeBuffer,
    rpId,
    timeout: 60000,
    userVerification: "required", // AP2: 生体認証必須
  };

  try {
    console.log("[WebAuthn] Starting Passkey authentication with options:", {
      rpId,
      challengeLength: challenge.length,
      timeout: 60000,
    });

    const credential = (await navigator.credentials.get({
      publicKey: publicKeyCredentialRequestOptions,
    })) as PublicKeyCredential | null;

    if (!credential) {
      throw new Error("No credential returned");
    }

    console.log("[WebAuthn] Passkey authentication successful");

    const response = credential.response as AuthenticatorAssertionResponse;

    // WebAuthnAttestation形式に変換
    const attestation: WebAuthnAttestation = {
      id: credential.id,
      rawId: bufferToBase64URL(credential.rawId),
      response: {
        clientDataJSON: bufferToBase64URL(response.clientDataJSON),
        authenticatorData: bufferToBase64URL(response.authenticatorData),
        signature: bufferToBase64URL(response.signature),
        userHandle: response.userHandle
          ? bufferToBase64URL(response.userHandle)
          : undefined,
      },
      type: "public-key",
      attestation_type: "passkey",
      challenge,
    };

    return attestation;
  } catch (error: any) {
    console.error("[WebAuthn] Authentication error:", error);

    let errorMessage = "Passkey認証に失敗しました";
    if (error.name === "NotAllowedError") {
      errorMessage = "認証がキャンセルされました。もう一度お試しください。";
    } else if (error.name === "InvalidStateError") {
      errorMessage = "Passkeyが登録されていません。先にPasskeyを登録してください。";
    } else if (error.name === "NotSupportedError") {
      errorMessage = "このブラウザはPasskeyをサポートしていません。";
    } else if (error.message) {
      errorMessage = `Passkey認証エラー: ${error.message}`;
    }

    throw new Error(errorMessage);
  }
}

// Passkey登録（初回登録用）
export async function registerPasskey(
  userId: string,
  userName: string,
  rpId: string = "localhost",
  rpName: string = "AP2 Demo App v2"
): Promise<WebAuthnAttestation> {
  if (!window.PublicKeyCredential) {
    throw new Error("WebAuthn is not supported in this browser");
  }

  const challenge = generateChallenge();

  const publicKeyCredentialCreationOptions: PublicKeyCredentialCreationOptions = {
    challenge: challenge as BufferSource,
    rp: {
      name: rpName,
      id: rpId,
    },
    user: {
      id: new TextEncoder().encode(userId),
      name: userName,
      displayName: userName,
    },
    pubKeyCredParams: [
      { alg: -7, type: "public-key" }, // ES256
      { alg: -257, type: "public-key" }, // RS256
    ],
    authenticatorSelection: {
      authenticatorAttachment: "platform",
      userVerification: "required",
      requireResidentKey: true,
    },
    timeout: 60000,
    attestation: "direct",
  };

  try {
    const credential = (await navigator.credentials.create({
      publicKey: publicKeyCredentialCreationOptions,
    })) as PublicKeyCredential | null;

    if (!credential) {
      throw new Error("No credential returned");
    }

    const response = credential.response as AuthenticatorAttestationResponse;

    // transportを取得
    const transports = response.getTransports ? response.getTransports() : [];

    // attestationObjectを送信（バックエンドで公開鍵を抽出）
    const attestationObject = bufferToBase64URL(response.attestationObject);

    // WebAuthnAttestation形式に変換（登録用の追加情報を含む）
    const attestation: WebAuthnAttestation = {
      id: credential.id,
      rawId: bufferToBase64URL(credential.rawId),
      response: {
        clientDataJSON: bufferToBase64URL(response.clientDataJSON),
        authenticatorData: attestationObject,
        signature: "", // 登録時は署名なし
      },
      type: "public-key",
      attestation_type: "registration",
      challenge: bufferToBase64URL(challenge),
      // 登録専用フィールド
      attestationObject,  // バックエンドで公開鍵を抽出
      transports,
    };

    return attestation;
  } catch (error: any) {
    console.error("WebAuthn registration error:", error);
    throw new Error(`Passkey registration failed: ${error.message}`);
  }
}
