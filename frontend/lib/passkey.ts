/**
 * v2/frontend/lib/passkey.ts
 *
 * Passkey/WebAuthn認証ユーティリティ（AP2仕様準拠）
 *
 * AP2アーキテクチャ:
 * - トラステッドサーフェス: ブラウザのWebAuthn API
 * - ハードウェアバックドキー: デバイスの認証器（Touch ID, Windows Hello等）
 * - 否認不可性: COSE公開鍵による署名検証
 */

import {
  startRegistration,
  startAuthentication,
} from '@simplewebauthn/browser';

// バックエンドAPIのベースURL
const API_BASE_URL = process.env.NEXT_PUBLIC_SHOPPING_AGENT_URL || 'http://localhost:8000';

/**
 * Passkey登録フロー（AP2仕様準拠）
 *
 * AP2要件:
 * - ユーザー同意の明示的な取得
 * - ハードウェアバックドキーによる署名
 * - email = payer_email（オプション、PII保護）
 *
 * @param username - ユーザー名
 * @param email - メールアドレス（AP2 payer_emailとして使用）
 * @returns JWT トークンとユーザー情報
 */
export async function registerPasskey(username: string, email: string) {
  try {
    // Step 1: サーバーからchallengeを取得
    const challengeResponse = await fetch(`${API_BASE_URL}/auth/passkey/register/challenge`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ username, email }),
    });

    if (!challengeResponse.ok) {
      const error = await challengeResponse.json();
      throw new Error(error.detail || 'Failed to get registration challenge');
    }

    const challengeData = await challengeResponse.json();

    // Step 2: WebAuthn Registration（ブラウザのネイティブAPI）
    // AP2仕様: "ハードウェアバックドキーを使用して署名"
    const credential = await startRegistration({
      challenge: challengeData.challenge,
      rp: {
        name: challengeData.rp_name,
        id: challengeData.rp_id,
      },
      user: {
        id: challengeData.user_id,
        name: email,
        displayName: username,
      },
      pubKeyCredParams: [
        { alg: -7, type: 'public-key' },  // ES256 (ECDSA)
        { alg: -257, type: 'public-key' }, // RS256 (RSA)
      ],
      timeout: challengeData.timeout,
      attestation: 'none', // AP2: プライバシー保護のため attestation は none
      authenticatorSelection: {
        authenticatorAttachment: 'platform', // 優先的にplatform authenticator（Touch ID等）
        userVerification: 'preferred',
        residentKey: 'preferred', // Discoverable Credential（パスワードレス）
      },
    });

    // Step 3: サーバーに登録リクエスト送信
    const registerResponse = await fetch(`${API_BASE_URL}/auth/passkey/register`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        username,
        email,
        credential_id: credential.id,
        public_key: credential.response.publicKey || '',
        attestation_object: credential.response.attestationObject,
        client_data_json: credential.response.clientDataJSON,
        transports: credential.response.transports || [],
      }),
    });

    if (!registerResponse.ok) {
      const error = await registerResponse.json();
      throw new Error(error.detail || 'Failed to register Passkey');
    }

    const result = await registerResponse.json();

    // JWTをlocalStorageに保存
    localStorage.setItem('ap2_access_token', result.access_token);
    localStorage.setItem('ap2_user', JSON.stringify(result.user));

    return result;
  } catch (error: any) {
    console.error('[Passkey Registration] Error:', error);
    throw error;
  }
}

/**
 * Passkeyログインフロー（AP2仕様準拠）
 *
 * AP2要件:
 * - トラステッドサーフェスでの認証
 * - リプレイ攻撃対策（sign_counter）
 * - email = payer_email
 *
 * @param email - メールアドレス
 * @returns JWT トークンとユーザー情報
 */
export async function loginPasskey(email: string) {
  try {
    // Step 1: サーバーからchallengeを取得
    const challengeResponse = await fetch(`${API_BASE_URL}/auth/passkey/login/challenge`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email }),
    });

    if (!challengeResponse.ok) {
      const error = await challengeResponse.json();
      throw new Error(error.detail || 'Failed to get login challenge');
    }

    const challengeData = await challengeResponse.json();

    // Step 2: WebAuthn Authentication
    // AP2仕様: "ユーザーは信頼できるサーフェスで認証"
    const credential = await startAuthentication({
      challenge: challengeData.challenge,
      rpId: challengeData.rp_id,
      allowCredentials: challengeData.allowed_credentials.map((cred: any) => ({
        id: cred.id,
        type: 'public-key',
        transports: cred.transports,
      })),
      timeout: challengeData.timeout,
      userVerification: 'preferred',
    });

    // Step 3: サーバーにログインリクエスト送信
    const loginResponse = await fetch(`${API_BASE_URL}/auth/passkey/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        email,
        credential_id: credential.id,
        authenticator_data: credential.response.authenticatorData,
        client_data_json: credential.response.clientDataJSON,
        signature: credential.response.signature,
        user_handle: credential.response.userHandle || null,
      }),
    });

    if (!loginResponse.ok) {
      const error = await loginResponse.json();
      throw new Error(error.detail || 'Failed to login with Passkey');
    }

    const result = await loginResponse.json();

    // JWTをlocalStorageに保存
    localStorage.setItem('ap2_access_token', result.access_token);
    localStorage.setItem('ap2_user', JSON.stringify(result.user));

    return result;
  } catch (error: any) {
    console.error('[Passkey Login] Error:', error);
    throw error;
  }
}

/**
 * ログアウト
 */
export function logout() {
  localStorage.removeItem('ap2_access_token');
  localStorage.removeItem('ap2_user');
}

/**
 * 現在のユーザー情報を取得
 */
export function getCurrentUser() {
  const userStr = localStorage.getItem('ap2_user');
  if (!userStr) return null;

  try {
    return JSON.parse(userStr);
  } catch {
    return null;
  }
}

/**
 * 認証状態をチェック
 */
export function isAuthenticated(): boolean {
  return !!localStorage.getItem('ap2_access_token');
}

/**
 * アクセストークンを取得
 */
export function getAccessToken(): string | null {
  return localStorage.getItem('ap2_access_token');
}

/**
 * APIリクエストヘッダーにAuthorizationを追加
 */
export function getAuthHeaders(): HeadersInit {
  const token = getAccessToken();
  if (!token) return {};

  return {
    Authorization: `Bearer ${token}`,
  };
}

/**
 * WebAuthn対応ブラウザかチェック
 */
export function isWebAuthnSupported(): boolean {
  return !!(
    window.PublicKeyCredential &&
    navigator.credentials &&
    navigator.credentials.create
  );
}

/**
 * Credential Provider用Passkey登録フロー（AP2仕様準拠 Layer 2認証）
 *
 * AP2アーキテクチャ:
 * - Layer 1: Shopping Agent（HTTPセッション認証）
 * - Layer 2: Credential Provider（Mandate署名認証）
 *
 * WebAuthn標準準拠:
 * - 各Relying Party (RP)ごとに独立したPasskeyを使用
 * - rpIdが異なるため、同一のcredentialを共有できない
 *
 * @param userId - ユーザーID
 * @param userEmail - メールアドレス
 * @returns 登録結果
 */
export async function registerCredentialProviderPasskey(userId: string, userEmail: string) {
  const CP_URL = process.env.NEXT_PUBLIC_CREDENTIAL_PROVIDER_URL || 'http://localhost:8003';

  try {
    // Step 1: サーバーからchallengeを取得（AP2完全準拠）
    const challengeResponse = await fetch(`${CP_URL}/register/passkey/challenge`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        user_id: userId,
        user_email: userEmail,
      }),
    });

    if (!challengeResponse.ok) {
      const error = await challengeResponse.json();
      throw new Error(error.detail || 'Failed to get registration challenge');
    }

    const challengeData = await challengeResponse.json();

    // Step 2: WebAuthn Registration（ブラウザのネイティブAPI）
    // AP2完全準拠：サーバーから取得したchallengeを使用
    const credential = await startRegistration(challengeData);

    // Step 3: Credential Providerに登録リクエスト送信
    const registerResponse = await fetch(`${CP_URL}/register/passkey`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        user_id: userId,
        user_email: userEmail,
        credential_id: credential.id,
        public_key_cose: credential.response.publicKey || '',
        attestation_object: credential.response.attestationObject,
        client_data_json: credential.response.clientDataJSON,
        transports: credential.response.transports || [],
      }),
    });

    if (!registerResponse.ok) {
      const error = await registerResponse.json();
      throw new Error(error.detail || 'Failed to register Credential Provider Passkey');
    }

    const result = await registerResponse.json();

    // 登録成功をlocalStorageに記録
    localStorage.setItem('ap2_cp_passkey_registered', 'true');

    return result;
  } catch (error: any) {
    console.error('[Credential Provider Passkey Registration] Error:', error);
    throw error;
  }
}

/**
 * Credential Provider用Passkeyが登録されているかチェック
 */
export function isCredentialProviderPasskeyRegistered(): boolean {
  return localStorage.getItem('ap2_cp_passkey_registered') === 'true';
}
