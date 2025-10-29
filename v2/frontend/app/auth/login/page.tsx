'use client';

/**
 * v2/frontend/app/auth/login/page.tsx
 *
 * ユーザーログイン画面（AP2仕様準拠）
 *
 * AP2仕様:
 * - HTTPセッション認証: メール/パスワード（AP2仕様外、ベストプラクティスに従う）
 * - email = payer_email（AP2仕様準拠）
 * - Mandate署名: WebAuthn/Passkey（Credential Provider）← AP2仕様準拠
 *
 * セキュリティ:
 * - Argon2id検証（サーバー側、タイミング攻撃耐性）
 * - HTTPS必須（本番環境）
 */

import { useState } from 'react';
import { useRouter } from 'next/navigation';

const API_BASE_URL = process.env.NEXT_PUBLIC_SHOPPING_AGENT_URL || 'http://localhost:8000';

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!email || !password) {
      setError('メールアドレスとパスワードを入力してください。');
      return;
    }

    setLoading(true);

    try {
      // AP2準拠: ユーザーログイン
      // 1. サーバーでArgon2id検証（タイミング攻撃耐性）
      // 2. JWT発行
      const response = await fetch(`${API_BASE_URL}/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          email,
          password,
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Login failed');
      }

      const result = await response.json();

      // JWTをlocalStorageに保存
      localStorage.setItem('ap2_access_token', result.access_token);
      localStorage.setItem('ap2_user', JSON.stringify(result.user));

      // sessionStorageにもuser_idを保存（支払い方法管理用）
      if (result.user && result.user.id) {
        sessionStorage.setItem('user_id', result.user.id);
      }

      // ログイン成功 → チャット画面へ
      router.push('/chat');
    } catch (err: any) {
      console.error('[Login] Error:', err);
      setError(err.message || 'ログインに失敗しました。もう一度お試しください。');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-100 px-4">
      <div className="max-w-md w-full bg-white rounded-2xl shadow-xl p-8">
        {/* ヘッダー */}
        <div className="text-center mb-8">
          <div className="inline-block p-3 bg-indigo-100 rounded-full mb-4">
            <svg className="w-8 h-8 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 16l-4-4m0 0l4-4m-4 4h14m-5 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h7a3 3 0 013 3v1" />
            </svg>
          </div>
          <h1 className="text-3xl font-bold text-gray-900 mb-2">
            ログイン
          </h1>
          <p className="text-gray-600">
            AP2 Demo Shopping Agent
          </p>
          <p className="text-sm text-gray-500 mt-2">
            安全な支払い体験を続けましょう
          </p>
        </div>

        {/* フォーム */}
        <form onSubmit={handleSubmit} className="space-y-6">
          {/* メールアドレス */}
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-2">
              メールアドレス
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="bugsbunny@gmail.com"
              className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all"
              disabled={loading}
              required
            />
          </div>

          {/* パスワード */}
          <div>
            <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-2">
              パスワード
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="パスワードを入力"
              className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all"
              disabled={loading}
              required
            />
          </div>

          {/* エラーメッセージ */}
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">
              {error}
            </div>
          )}

          {/* ログインボタン */}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-medium py-3 px-4 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {loading ? (
              <>
                <svg className="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <span>ログイン中...</span>
              </>
            ) : (
              <>
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 16l-4-4m0 0l4-4m-4 4h14m-5 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h7a3 3 0 013 3v1" />
                </svg>
                <span>ログイン</span>
              </>
            )}
          </button>

          {/* 登録リンク */}
          <div className="text-center">
            <p className="text-sm text-gray-600">
              アカウントをお持ちでないですか？{' '}
              <a href="/auth/register" className="text-indigo-600 hover:text-indigo-800 font-medium">
                新規登録
              </a>
            </p>
          </div>
        </form>

        {/* AP2仕様準拠の説明 */}
        <div className="mt-8 pt-6 border-t border-gray-200">
          <p className="text-xs text-gray-500 text-center">
            🔒 AP2プロトコル準拠：Argon2id検証（タイミング攻撃耐性）
            <br />
            支払い時はPasskey認証で安全に署名（Credential Provider）
          </p>
        </div>
      </div>
    </div>
  );
}
