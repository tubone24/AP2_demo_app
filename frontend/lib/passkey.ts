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
 * [DELETED] Shopping AgentのPasskey認証エンドポイントは削除されました
 *
 * AP2完全準拠:
 * - HTTPセッション認証（Layer 1）: メール/パスワード認証を使用
 * - Mandate署名認証（Layer 2）: Credential Provider経由でPasskey認証
 *
 * 使用する認証方法:
 * 1. ユーザー登録: POST /auth/register (メール/パスワード)
 * 2. ユーザーログイン: POST /auth/login (メール/パスワード)
 * 3. Mandate署名用Passkey登録: registerCredentialProviderPasskey() (Credential Provider)
 */

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
