'use client';

/**
 * v2/frontend/app/auth/register/page.tsx
 *
 * ユーザー登録画面（AP2仕様準拠）
 *
 * AP2仕様:
 * - HTTPセッション認証: メール/パスワード（AP2仕様外、ベストプラクティスに従う）
 * - email = payer_email（AP2仕様準拠）
 * - Mandate署名: WebAuthn/Passkey（Credential Provider）← AP2仕様準拠
 *
 * セキュリティ:
 * - Argon2idパスワードハッシュ化（サーバー側）
 * - パスワード強度検証
 * - HTTPS必須（本番環境）
 */

import { useState } from 'react';
import { useRouter } from 'next/navigation';

const API_BASE_URL = process.env.NEXT_PUBLIC_SHOPPING_AGENT_URL || 'http://localhost:8000';

export default function RegisterPage() {
  const router = useRouter();
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!username || !email || !password || !confirmPassword) {
      setError('全ての項目を入力してください。');
      return;
    }

    // パスワード一致確認
    if (password !== confirmPassword) {
      setError('パスワードが一致しません。');
      return;
    }

    // パスワード強度チェック（クライアント側）
    if (password.length < 8) {
      setError('パスワードは8文字以上である必要があります。');
      return;
    }

    setLoading(true);

    try {
      // AP2準拠: ユーザー登録
      // 1. サーバーでArgon2idハッシュ化
      // 2. JWT発行
      const response = await fetch(`${API_BASE_URL}/auth/register`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          username,
          email,
          password,
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Registration failed');
      }

      const result = await response.json();

      // JWTをlocalStorageに保存
      localStorage.setItem('ap2_access_token', result.access_token);
      localStorage.setItem('ap2_user', JSON.stringify(result.user));

      // 登録成功 → Passkey登録画面へ（AP2完全準拠）
      router.push('/auth/register-passkey');
    } catch (err: any) {
      console.error('[Register] Error:', err);
      setError(err.message || '登録に失敗しました。もう一度お試しください。');
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
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
            </svg>
          </div>
          <h1 className="text-3xl font-bold text-gray-900 mb-2">
            アカウント登録
          </h1>
          <p className="text-gray-600">
            AP2 Demo Shopping Agent
          </p>
          <p className="text-sm text-gray-500 mt-2">
            安全な支払い体験を始めましょう
          </p>
        </div>

        {/* フォーム */}
        <form onSubmit={handleSubmit} className="space-y-6">
          {/* ユーザー名 */}
          <div>
            <label htmlFor="username" className="block text-sm font-medium text-gray-700 mb-2">
              ユーザー名
            </label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="bugsbunny"
              className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all"
              disabled={loading}
              required
            />
          </div>

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
            <p className="text-xs text-gray-500 mt-1">
              ※ AP2プロトコル: 支払い時のpayer_emailとして使用されます
            </p>
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
              placeholder="8文字以上、大文字・小文字・数字を含む"
              className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all"
              disabled={loading}
              required
              minLength={8}
            />
            <p className="text-xs text-gray-500 mt-1">
              Argon2idで安全にハッシュ化されます（OWASP推奨）
            </p>
          </div>

          {/* パスワード確認 */}
          <div>
            <label htmlFor="confirmPassword" className="block text-sm font-medium text-gray-700 mb-2">
              パスワード（確認）
            </label>
            <input
              id="confirmPassword"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="パスワードを再入力"
              className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition-all"
              disabled={loading}
              required
              minLength={8}
            />
          </div>

          {/* エラーメッセージ */}
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">
              {error}
            </div>
          )}

          {/* 登録ボタン */}
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
                <span>登録中...</span>
              </>
            ) : (
              <>
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z" />
                </svg>
                <span>アカウント登録</span>
              </>
            )}
          </button>

          {/* ログインリンク */}
          <div className="text-center">
            <p className="text-sm text-gray-600">
              すでにアカウントをお持ちですか？{' '}
              <a href="/auth/login" className="text-indigo-600 hover:text-indigo-800 font-medium">
                ログイン
              </a>
            </p>
          </div>
        </form>

        {/* AP2仕様準拠の説明 */}
        <div className="mt-8 pt-6 border-t border-gray-200">
          <p className="text-xs text-gray-500 text-center">
            🔒 AP2プロトコル準拠：Argon2idパスワードハッシュ化（OWASP推奨）
            <br />
            支払い時はPasskey認証で安全に署名（Credential Provider）
          </p>
        </div>
      </div>
    </div>
  );
}
