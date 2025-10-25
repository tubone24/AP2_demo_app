'use client';

/**
 * v2/frontend/app/auth/register-passkey/page.tsx
 *
 * Credential Provider用Passkey登録専用画面（AP2完全準拠）
 *
 * AP2仕様:
 * - Mandate署名用のハードウェアバックドキー登録
 * - Credential Providerで公開鍵を管理
 * - WebAuthn/FIDO2標準準拠
 *
 * セキュリティ:
 * - サーバー側でchallenge生成（リプレイ攻撃対策）
 * - ハードウェアセキュアエンクレーブに秘密鍵保存
 * - Relying Party: Credential Provider（localhost:8003）
 */

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import {
  isAuthenticated,
  getCurrentUser,
  isCredentialProviderPasskeyRegistered,
  registerCredentialProviderPasskey
} from '@/lib/passkey';

export default function RegisterPasskeyPage() {
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [alreadyRegistered, setAlreadyRegistered] = useState(false);

  useEffect(() => {
    // JWT認証チェック
    if (!isAuthenticated()) {
      router.push('/auth/login');
      return;
    }

    const user = getCurrentUser();
    if (user) {
      setCurrentUser(user);

      // 既にPasskeyが登録されているかチェック
      if (isCredentialProviderPasskeyRegistered()) {
        setAlreadyRegistered(true);
      }
    }
  }, [router]);

  const handleRegister = async () => {
    if (!currentUser) {
      setError('ユーザー情報が見つかりません');
      return;
    }

    setLoading(true);
    setError('');

    try {
      // AP2完全準拠: Credential Provider用Passkey登録
      // 1. サーバーからchallenge取得
      // 2. WebAuthn Registration
      // 3. 公開鍵をCredential Providerに送信
      await registerCredentialProviderPasskey(currentUser.id, currentUser.email);

      setSuccess(true);

      // 3秒後にチャット画面へリダイレクト
      setTimeout(() => {
        router.push('/chat');
      }, 3000);
    } catch (err: any) {
      console.error('[Register Passkey] Error:', err);
      setError(err.message || 'Passkey登録に失敗しました。もう一度お試しください。');
    } finally {
      setLoading(false);
    }
  };

  const handleSkip = () => {
    router.push('/chat');
  };

  if (!currentUser) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-muted-foreground">読み込み中...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-100 px-4">
      <div className="max-w-md w-full bg-white rounded-2xl shadow-xl p-8">
        {/* ヘッダー */}
        <div className="text-center mb-8">
          <div className="inline-block p-3 bg-indigo-100 rounded-full mb-4">
            <svg className="w-8 h-8 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
          </div>
          <h1 className="text-3xl font-bold text-gray-900 mb-2">
            🔐 支払い署名用Passkeyの設定
          </h1>
          <p className="text-gray-600">
            AP2 Credential Provider
          </p>
          <p className="text-sm text-gray-500 mt-2">
            安全な支払い承認のためのハードウェアキー
          </p>
        </div>

        {alreadyRegistered && !success && (
          <div className="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded-lg mb-6 text-sm">
            ✅ Passkeyは既に登録されています
          </div>
        )}

        {success && (
          <div className="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded-lg mb-6 text-sm">
            ✅ Passkey登録が完了しました！チャット画面にリダイレクトします...
          </div>
        )}

        {/* AP2仕様説明 */}
        <div className="bg-muted p-4 rounded-lg mb-6 space-y-3 text-sm">
          <div>
            <strong>✅ HTTPセッション認証（完了）</strong>
            <div className="text-muted-foreground">
              メール/パスワードでログイン済み
              <br />
              ユーザー: {currentUser.email}
            </div>
          </div>
          <div>
            <strong>🔒 Mandate署名認証（AP2必須）</strong>
            <div className="text-muted-foreground">
              支払い承認用Passkey（Credential Provider）
              <br />
              ハードウェアバックドキー使用
            </div>
          </div>
        </div>

        {/* WebAuthn対応確認 */}
        <div className="mb-6">
          <p className="text-sm text-muted-foreground mb-2">
            <strong>対応認証方法：</strong>
          </p>
          <ul className="text-xs text-muted-foreground space-y-1">
            <li>• macOS: Touch ID / Face ID</li>
            <li>• Windows: Windows Hello</li>
            <li>• Android/iOS: 指紋認証 / 顔認証</li>
          </ul>
        </div>

        {/* エラーメッセージ */}
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg mb-6 text-sm">
            {error}
          </div>
        )}

        {/* アクションボタン */}
        <div className="space-y-3">
          <button
            onClick={handleRegister}
            disabled={loading || success || alreadyRegistered}
            className="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-medium py-3 px-4 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {loading ? (
              <>
                <svg className="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <span>Passkey登録中...</span>
              </>
            ) : alreadyRegistered ? (
              <span>登録済み</span>
            ) : (
              <>
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                </svg>
                <span>Passkeyを登録</span>
              </>
            )}
          </button>

          <button
            onClick={handleSkip}
            disabled={loading}
            className="w-full bg-muted text-muted-foreground hover:bg-muted/80 px-4 py-3 rounded-lg font-medium disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {alreadyRegistered ? 'チャット画面へ' : '後で登録する'}
          </button>
        </div>

        {/* AP2仕様準拠の説明 */}
        <div className="mt-8 pt-6 border-t border-gray-200">
          <p className="text-xs text-gray-500 text-center">
            🔒 AP2プロトコル完全準拠
            <br />
            サーバー側でchallenge生成（リプレイ攻撃対策）
            <br />
            ハードウェアセキュアエンクレーブに秘密鍵保存
            <br />
            Intent/Cart/Payment Mandateへの署名に使用
          </p>
        </div>
      </div>
    </div>
  );
}
