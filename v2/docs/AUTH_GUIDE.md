# AP2完全準拠 認証実装ガイド

## 概要

v2 AP2 Shopping Agentは、**AP2プロトコル完全準拠**の認証アーキテクチャを採用しています。

## AP2完全準拠の認証アーキテクチャ

### なぜこのアーキテクチャなのか？

AP2プロトコル仕様を徹底的に調査した結果：

1. **HTTPセッション認証**: AP2仕様に含まれていない（実装の自由度あり）
2. **Mandate署名認証**: AP2仕様で必須（ハードウェアバックドキー使用）

そのため、以下のアーキテクチャを採用しました：

```
┌─────────────────────────────────────────────────────┐
│ Shopping Agent（HTTPセッション認証）                 │
│ - 方式: メール/パスワード + JWT                      │
│ - 目的: user_id取得、セッション管理                  │
│ - セキュリティ: Argon2id（OWASP推奨）                │
│ - AP2仕様: 範囲外（実装の自由度あり）                │
└─────────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────┐
│ Credential Provider（Mandate署名認証）★AP2必須★    │
│ - 方式: Passkey（WebAuthn/FIDO2）                   │
│ - 目的: Intent/Cart/Payment Mandateへの署名         │
│ - セキュリティ: ハードウェアバックドキー             │
│ - AP2仕様: 完全準拠                                  │
└─────────────────────────────────────────────────────┘
```

---

## 1. セットアップ手順

### 1.1 環境変数の設定

**v2/.env**ファイルを作成（または`.env.example`をコピー）:

```bash
# JWT設定（HTTPセッション認証）
JWT_SECRET_KEY=your_random_secret_key_at_least_32_characters_long_here
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=1440  # 24時間

# Credential Provider WebAuthn設定（Mandate署名認証）
WEBAUTHN_RP_ID=localhost  # 本番環境ではドメイン名に変更
WEBAUTHN_RP_NAME=AP2 Demo Credential Provider
```

**重要**: `JWT_SECRET_KEY`は必ず変更してください！

```bash
# ランダム文字列生成
openssl rand -hex 32
# または
python -c "import secrets; print(secrets.token_hex(32))"
```

### 1.2 依存パッケージのインストール

**バックエンド**:
```bash
cd v2
pip install -r requirements.txt
# または
uv sync
```

**フロントエンド**:
```bash
cd v2/frontend
npm install
```

### 1.3 データベースの初期化

```bash
cd v2
python -c "from common.database import init_db; init_db()"
```

これにより、`users`テーブル（パスワード認証用）と`passkey_credentials`テーブル（Mandate署名用）が作成されます。

---

## 2. 使い方

### 2.1 新規登録フロー

#### Step 1: メール/パスワード登録

1. **登録画面へ移動**: http://localhost:3000/auth/register
2. **情報入力**:
   - ユーザー名（例: `bugsbunny`）
   - メールアドレス（例: `bugsbunny@gmail.com`）- AP2 payer_emailとして使用
   - パスワード（8文字以上、大文字・小文字・数字を含む）
   - パスワード確認
3. **「アカウント登録」ボタンをクリック**
4. **自動的にチャット画面へリダイレクト**

**内部処理**:
- サーバー側でArgon2idハッシュ化（OWASP推奨）
- パスワード強度検証（大文字・小文字・数字、弱いパスワードチェック）
- JWTトークン発行（24時間有効）
- localStorageに保存

#### Step 2: Credential Provider用Passkey登録（AP2準拠）

5. **チャット画面で「支払い署名用Passkeyの設定」ダイアログが表示**
6. **「Passkeyを登録」ボタンをクリック**
   - または「スキップ」を選択（Mock認証を使用）
7. **ブラウザのPasskey登録ダイアログが表示**:
   - macOS: Touch IDまたはFace IDで認証
   - Windows: Windows Helloで認証
   - モバイル: 指紋・顔認証
8. **認証成功後、チャット画面で利用可能に**

**内部処理（AP2完全準拠）**:
- WebAuthn Registrationで公開鍵・秘密鍵ペアを生成
- 秘密鍵はデバイスのセキュアエンクレーブに保存（外部流出不可）
- 公開鍵をCredential Providerに送信してデータベースに保存
- Relying Party ID: `localhost:8003`

### 2.2 ログインフロー

1. **ログイン画面へ移動**: http://localhost:3000/auth/login
2. **メールアドレスとパスワードを入力**
3. **「ログイン」ボタンをクリック**
4. **自動的にチャット画面へリダイレクト**

**内部処理**:
- サーバー側でArgon2id検証（タイミング攻撃耐性あり）
- JWTトークン発行
- Credential Provider Passkeyの登録状態チェック

### 2.3 支払い時の認証フロー（AP2準拠）

1. ユーザーが商品を選択してカートを確定
2. 支払い方法選択
3. **Credential Provider Passkeyで署名**（AP2必須）
   - WebAuthn assertion生成
   - Intent/Cart/Payment Mandateへの署名
   - sign_counter検証（リプレイ攻撃対策）
4. Payment Processorへ送信
5. 決済完了

---

## 3. セキュリティ機能（AP2完全準拠 + ベストプラクティス）

### 3.1 HTTPセッション認証（Shopping Agent）

#### Argon2idパスワードハッシュ化

- **アルゴリズム**: Argon2id（2015 Password Hashing Competition優勝）
- **OWASP推奨パラメータ**:
  - time_cost: 2
  - memory_cost: 19456 (19 MiB)
  - parallelism: 1
- **特徴**:
  - メモリハード関数（GPU攻撃耐性）
  - サイドチャネル攻撃耐性
  - タイミング攻撃耐性（constant-time comparison）

**実装箇所**: `v2/common/auth.py:121-153`

#### パスワード強度検証

- 最低8文字
- 大文字・小文字・数字を含む
- 一般的な弱いパスワード（`password`, `12345678`等）を拒否

**実装箇所**: `v2/common/auth.py:76-118`

#### タイミング攻撃対策

ユーザーが存在しない場合でもハッシュ化処理を実行：

```python
if not user:
    # タイミング攻撃対策
    hash_password("dummy_password_for_timing_attack_resistance")
    raise HTTPException(status_code=401, detail="Invalid email or password")
```

**実装箇所**: `v2/services/shopping_agent/agent.py:330-336`

### 3.2 Mandate署名認証（Credential Provider - AP2準拠）

#### WebAuthn/Passkey認証

- **ハードウェアバックドキー使用**（AP2仕様準拠）
- **Relying Party ID**: `localhost:8003`（本番環境では専用ドメイン）
- **リプレイ攻撃対策**: sign_counter検証

**実装箇所**: `v2/services/credential_provider/provider.py:155`

#### リプレイ攻撃対策

WebAuthnの**sign_counter**を使用：
- 認証ごとにカウンターが増加
- サーバー側で前回のカウンターと比較
- カウンターが減少した場合は認証を拒否

### 3.3 JWT有効期限

- **デフォルト**: 24時間（1440分）
- **設定変更**: `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`環境変数で調整可能
- **有効期限切れ時**: ログイン画面へ自動リダイレクト

---

## 4. API仕様

### 4.1 ユーザー登録（メール/パスワード）

**エンドポイント**: `POST /auth/register`

**リクエスト**:
```json
{
  "username": "bugsbunny",
  "email": "bugsbunny@gmail.com",
  "password": "SecurePass123"
}
```

**レスポンス**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user": {
    "id": "usr_1234567890abcdef",
    "username": "bugsbunny",
    "email": "bugsbunny@gmail.com",
    "created_at": "2025-10-25T10:30:00Z",
    "is_active": true
  }
}
```

### 4.2 ユーザーログイン（メール/パスワード）

**エンドポイント**: `POST /auth/login`

**リクエスト**:
```json
{
  "email": "bugsbunny@gmail.com",
  "password": "SecurePass123"
}
```

**レスポンス**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user": {
    "id": "usr_1234567890abcdef",
    "username": "bugsbunny",
    "email": "bugsbunny@gmail.com",
    "created_at": "2025-10-25T10:30:00Z",
    "is_active": true
  }
}
```

### 4.3 Credential Provider Passkey登録（AP2準拠）

**エンドポイント**: `POST /register/passkey` (Credential Provider: localhost:8003)

**リクエスト**:
```json
{
  "user_id": "usr_1234567890abcdef",
  "user_email": "bugsbunny@gmail.com",
  "credential_id": "base64url_credential_id",
  "public_key_cose": "base64_cose_public_key",
  "attestation_object": "base64url_attestation",
  "client_data_json": "base64url_client_data",
  "transports": ["internal"]
}
```

**レスポンス**:
```json
{
  "success": true,
  "credential_id": "base64url_credential_id",
  "message": "Passkey registered successfully"
}
```

---

## 5. トラブルシューティング

### 5.1 パスワードが弱いと言われる

**エラー**: "Password must contain uppercase, lowercase, and digits"

**解決策**:
- 8文字以上
- 大文字を最低1文字含む
- 小文字を最低1文字含む
- 数字を最低1文字含む
- 例: `SecurePass123`

### 5.2 ログインに失敗する

**エラー**: "Invalid email or password"

**原因**:
1. メールアドレスまたはパスワードが間違っている
2. アカウントが無効化されている

**解決策**:
- 正しいメールアドレスとパスワードを入力
- 新規登録してアカウントを作成

### 5.3 Credential Provider Passkeyが登録できない

**エラー**: "お使いのブラウザはPasskey（WebAuthn）に対応していません"

**解決策**:
- Chrome、Safari、Edgeの最新版を使用
- HTTPSまたはlocalhostでアクセス
- ブラウザのWebAuthn機能が有効か確認

---

## 6. 本番環境デプロイ（AP2完全準拠）

### 6.1 必須設定項目

1. **JWT_SECRET_KEY**: ランダムな32文字以上の文字列
2. **WEBAUTHN_RP_ID（Credential Provider）**: `credentials.example.com`
3. **HTTPS**: 必須（WebAuthnはHTTPSまたはlocalhost以外では動作しません）
4. **データベース**: PostgreSQLまたはMySQLを推奨（SQLiteは開発用）

### 6.2 推奨デプロイ構成

```
Shopping Agent:      https://shop.example.com      (メール/パスワード認証)
Credential Provider: https://credentials.example.com (Passkey認証)
Frontend:            https://app.example.com
```

---

## 7. まとめ：AP2完全準拠の認証アーキテクチャ

### 7.1 なぜこのアーキテクチャを採用したか？

1. **AP2仕様準拠**: Mandate署名にハードウェアバックドキー（Passkey）を使用
2. **セキュリティベストプラクティス**: Argon2idパスワードハッシュ化（OWASP推奨）
3. **ユーザビリティ**: シンプルなメール/パスワードログイン + 支払い時のみPasskey
4. **実装の自由度**: AP2仕様外のHTTPセッション認証は自由に実装可能

### 7.2 認証の使い分け

| 認証 | 用途 | 方式 | AP2仕様 |
|------|------|------|---------|
| **Shopping Agent** | チャット画面へのアクセス | メール/パスワード + JWT | 範囲外（実装の自由度あり） |
| **Credential Provider** | Mandate署名の承認 | Passkey（WebAuthn） | 必須（ハードウェアバックドキー） |

### 7.3 セキュリティ実装のポイント

#### HTTPセッション認証（Shopping Agent）
- ✅ Argon2idパスワードハッシュ化（OWASP推奨パラメータ）
- ✅ パスワード強度検証（8文字以上、大文字・小文字・数字）
- ✅ タイミング攻撃対策（constant-time comparison）
- ✅ JWT有効期限管理（24時間、自動ログアウト）

#### Mandate署名認証（Credential Provider）
- ✅ WebAuthn/FIDO2標準準拠
- ✅ ハードウェアセキュアエンクレーブに秘密鍵保存
- ✅ リプレイ攻撃対策（sign_counter検証）
- ✅ AP2プロトコル完全準拠

---

## 8. 参考資料

- **AP2 Protocol**: https://ap2-protocol.org/specification/
- **OWASP Password Storage Cheat Sheet**: https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
- **Argon2 RFC**: https://datatracker.ietf.org/doc/html/rfc9106
- **WebAuthn W3C標準**: https://www.w3.org/TR/webauthn-2/
- **SimpleWebAuthn公式ドキュメント**: https://simplewebauthn.dev/

---

**最終更新**: 2025年10月25日
**バージョン**: 3.0（AP2完全準拠版 - メール/パスワード + Passkey）
