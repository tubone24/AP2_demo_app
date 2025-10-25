# Passkey認証実装ガイド（AP2完全準拠版）

## 概要

v2 AP2 Shopping Agentは、**AP2プロトコル完全準拠**のパスワードレスPasskey認証を採用しています。このガイドでは、AP2の2層認証アーキテクチャ、Passkey認証の仕組み、セットアップ方法、使い方を説明します。

---

## 1. AP2完全準拠の2層認証アーキテクチャ

### 1.1 なぜ2つのPasskeyが必要か？

AP2プロトコルとWebAuthn標準に完全準拠するため、**2つの独立したPasskey**を使用します：

| Layer | 認証対象 | Passkey用途 | Relying Party |
|-------|---------|------------|---------------|
| **Layer 1** | HTTPセッション認証 | Shopping Agentへのログイン | `localhost:8000` (Shopping Agent) |
| **Layer 2** | Mandate署名認証 | Intent/Cart/Payment Mandateへの署名 | `localhost:8003` (Credential Provider) |

**重要**: WebAuthn標準では、異なるRelying Party (RP)間で同一のPasskeyを共有することは**推奨されていません**。各サービス（RP）ごとに独立したPasskeyを使用することで、セキュリティとプライバシーが向上します。

### 1.2 Passkeyの特徴

- **パスワード不要**: 生体認証（Touch ID、Face ID、Windows Hello）で安全にログイン
- **フィッシング耐性**: パスワード流出のリスクがゼロ
- **デバイス固有**: ハードウェアバックドキーで秘密鍵を保護
- **W3C標準**: WebAuthn/FIDO2準拠の国際標準技術
- **複数Passkey対応**: パスワードマネージャー（1Password、iCloud Keychain等）で複数のPasskeyを一元管理可能

### 1.3 対応デバイス

| デバイス | 認証方法 | 対応状況 |
|---------|---------|---------|
| macOS | Touch ID / Face ID | ✅ 対応 |
| Windows | Windows Hello（指紋・顔・PIN） | ✅ 対応 |
| iOS/iPadOS | Face ID / Touch ID | ✅ 対応 |
| Android | 指紋認証・顔認証 | ✅ 対応 |
| FIDO2セキュリティキー | YubiKey等 | ✅ 対応 |

### 1.4 対応ブラウザ

- ✅ Chrome 67+
- ✅ Safari 14+
- ✅ Edge 18+
- ✅ Firefox 60+

---

## 2. 認証フロー全体像

### 2.1 初回登録フロー

```
1. ユーザーが登録画面でメールアドレスとユーザー名を入力
   ↓
2. [Layer 1] Shopping Agent用Passkey登録
   - Relying Party: localhost:8000
   - 用途: HTTPセッション認証（チャット画面へのアクセス）
   - JWT発行: 24時間有効
   ↓
3. チャット画面へリダイレクト
   ↓
4. [Layer 2] Credential Provider用Passkey登録プロンプト表示
   - Relying Party: localhost:8003
   - 用途: Mandate署名認証（支払い方法選択時）
   - ユーザーは「登録」または「スキップ」を選択可能
   ↓
5. 登録完了 - AP2完全準拠の2層認証が有効化
```

### 2.2 ログインフロー

```
1. ユーザーがログイン画面でメールアドレスを入力
   ↓
2. [Layer 1] Shopping Agent用Passkeyで認証
   - sign_counterによるリプレイ攻撃検証
   - JWT発行
   ↓
3. チャット画面へリダイレクト
   ↓
4. [Layer 2] Credential Provider用Passkeyの有無をチェック
   - 未登録の場合: 登録プロンプト表示
   - 登録済みの場合: そのまま利用可能
```

### 2.3 支払い時の認証フロー（AP2準拠）

```
1. ユーザーが商品を選択してカートを確定
   ↓
2. 支払い方法選択
   ↓
3. [Layer 2] Credential Provider用Passkeyで署名
   - WebAuthn assertion生成
   - Payment Mandateへの署名
   - リプレイ攻撃検証（sign_counter）
   ↓
4. Payment Processorへ送信
   ↓
5. 決済完了
```

---

## 3. セットアップ手順

### 3.1 環境変数の設定

**v2/.env**ファイルを作成（または`.env.example`をコピー）:

```bash
# Passkey認証 + JWT設定
JWT_SECRET_KEY=your_random_secret_key_at_least_32_characters_long_here
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=1440  # 24時間

# WebAuthn設定
WEBAUTHN_RP_ID=localhost  # 本番環境ではドメイン名に変更（例: shop.example.com）
WEBAUTHN_RP_NAME=AP2 Demo Shopping Agent
```

**重要**: `JWT_SECRET_KEY`は必ず変更してください！以下のコマンドでランダム文字列を生成できます：

```bash
# Linux/macOS
openssl rand -hex 32

# Python
python -c "import secrets; print(secrets.token_hex(32))"
```

### 3.2 依存パッケージのインストール

**バックエンド**:
```bash
cd v2
pip install -r requirements.txt
```

**フロントエンド**:
```bash
cd v2/frontend
npm install
```

### 3.3 データベースの初期化

```bash
cd v2
python -c "from common.database import init_db; init_db()"
```

これにより、`users`テーブルと`passkey_credentials`テーブルが作成されます。

---

## 4. 使い方

### 4.1 アプリケーションの起動

**バックエンド**（3つのターミナルで実行）:
```bash
# Shopping Agent（ポート8000）
cd v2/services/shopping_agent
python main.py

# Merchant Agent（ポート8001）
cd v2/services/merchant_agent
python main.py

# Payment Processor（ポート8002）
cd v2/services/payment_processor
python main.py
```

**フロントエンド**:
```bash
cd v2/frontend
npm run dev
```

ブラウザで http://localhost:3000 にアクセスします。

### 4.2 新規登録フロー（AP2完全準拠 2層認証）

#### Step 1: Shopping Agent用Passkey登録（Layer 1）

1. **登録画面へ移動**: http://localhost:3000/auth/register
2. **情報入力**:
   - ユーザー名（例: `bugsbunny`）
   - メールアドレス（例: `bugsbunny@gmail.com`）
3. **「Passkeyで登録」ボタンをクリック**
4. **ブラウザのPasskey登録ダイアログが表示**:
   - macOS: Touch IDまたはFace IDで認証
   - Windows: Windows Helloで認証
   - モバイル: 指紋・顔認証
5. **認証成功後、自動的にチャット画面へリダイレクト**

**内部処理（Layer 1）**:
- WebAuthn Registrationで公開鍵・秘密鍵ペアを生成
- 秘密鍵はデバイスのセキュアエンクレーブに保存（外部流出不可）
- 公開鍵をShopping Agentに送信してデータベースに保存
- JWTトークンを発行してlocalStorageに保存
- Relying Party ID: `localhost:8000`

#### Step 2: Credential Provider用Passkey登録（Layer 2）

6. **チャット画面で「追加認証の設定」ダイアログが表示**
7. **「Passkeyを登録」ボタンをクリック**
   - または「スキップ」を選択（後でMock認証を使用）
8. **ブラウザのPasskey登録ダイアログが再度表示**:
   - 同じ生体認証方法で認証
   - **別のPasskey**が生成される（WebAuthn標準準拠）
9. **認証成功後、チャット画面で利用可能に**

**内部処理（Layer 2）**:
- **新しい**WebAuthn Registrationで独立した公開鍵・秘密鍵ペアを生成
- 公開鍵をCredential Providerに送信してデータベースに保存
- Relying Party ID: `localhost:8003`（Shopping Agentとは**異なる**）
- localStorageに登録完了フラグを保存

**重要**: パスワードマネージャー（1Password、iCloud Keychain等）を使用している場合、2つのPasskeyは自動的に保存され、次回以降は選択するだけで認証できます。

### 4.3 ログインフロー

1. **ログイン画面へ移動**: http://localhost:3000/auth/login
2. **メールアドレス入力**（例: `bugsbunny@gmail.com`）
3. **「Passkeyでログイン」ボタンをクリック**
4. **ブラウザのPasskey認証ダイアログが表示**:
   - 登録時と同じデバイス認証方法で認証
5. **認証成功後、自動的にチャット画面へ**

**内部処理**:
- サーバーからchallengeを取得
- WebAuthn Authenticationでデバイス認証（秘密鍵で署名）
- サーバーが公開鍵で署名を検証
- sign_counterを検証してリプレイ攻撃を防止
- JWTトークンを発行してlocalStorageに保存

### 4.4 ログアウト

チャット画面右上の「ログアウト」ボタンをクリック:
- JWTトークンをlocalStorageから削除
- Credential Provider Passkey登録フラグはそのまま保持（再ログイン時に再利用）
- ログイン画面へリダイレクト

---

## 5. セキュリティ機能（AP2完全準拠）

### 5.1 2層認証によるセキュリティ強化

AP2プロトコルは、**異なる目的**で**異なる認証**を要求します：

| 認証層 | 目的 | 認証方法 | 攻撃対策 |
|-------|------|---------|---------|
| **Layer 1** | HTTPセッション認証 | Shopping Agent Passkey + JWT | セッションハイジャック対策 |
| **Layer 2** | Mandate署名認証 | Credential Provider Passkey | 否認防止 + リプレイ攻撃対策 |

**なぜ2層が必要か？**

- **Layer 1のみの場合**: JWTが盗まれると、不正な決済リクエストを送信される可能性がある
- **Layer 2追加により**: 支払い方法選択時に再度Passkey認証が必要なため、JWTだけでは決済できない
- **AP2仕様準拠**: Intent/Cart/Payment Mandateへの署名には、ユーザーの明示的な同意（Passkey認証）が必要

### 5.2 リプレイ攻撃対策

WebAuthnの**sign_counter**を使用：
- 認証ごとにカウンターが増加
- サーバー側で前回のカウンターと比較
- カウンターが減少した場合は認証を拒否（リプレイ攻撃と判定）

**実装箇所**: `v2/common/auth.py:236-247`

```python
# sign_counter検証
stored_sign_count = credential.sign_count
current_sign_count = authenticator_data.sign_count

if current_sign_count <= stored_sign_count:
    raise HTTPException(
        status_code=401,
        detail="Replay attack detected: sign_count did not increase"
    )
```

### 5.3 WebAuthn Relying Party分離によるセキュリティ

WebAuthn標準に従い、各サービスで**独立したRelying Party ID**を使用：

```
Shopping Agent (Layer 1):     rpId = "localhost:8000"
Credential Provider (Layer 2): rpId = "localhost:8003"
```

**メリット**:
- Passkey credentialのドメイン制限により、フィッシングサイトでは動作しない
- 各サービスの秘密鍵が独立しているため、一方が漏洩しても他方は安全
- WebAuthn仕様準拠により、ブラウザの標準セキュリティ機構を活用

### 5.4 JWT有効期限

- **デフォルト**: 24時間（1440分）
- **設定変更**: `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`環境変数で調整可能
- **有効期限切れ時**: ログイン画面へ自動リダイレクト
- **Layer 2**: JWT有効期限とは無関係に、Passkey認証が必要（二重保護）

### 5.5 CORS設定

本番環境では、`v2/services/shopping_agent/main.py`のCORS設定を変更：

```python
# 開発環境（現在の設定）
origins = ["http://localhost:3000"]

# 本番環境（例）
origins = ["https://shop.example.com"]
```

---

## 6. トラブルシューティング（AP2完全準拠版）

### 6.1 Passkey登録に失敗する

**症状**: 「お使いのブラウザはPasskey（WebAuthn）に対応していません」エラー

**解決策**:
- Chrome、Safari、Edgeの最新版を使用
- HTTPSまたはlocalhostでアクセス（WebAuthnはHTTPでは動作しません）
- ブラウザのWebAuthn機能が有効か確認

### 6.2 Credential Provider用Passkey登録がスキップされた

**症状**: 支払い時に「Mock認証」が使用される

**原因**: Layer 2のPasskeyを登録せずにスキップした

**解決策**:
- チャット画面で再度登録プロンプトを表示する機能は現在未実装
- 一時的な対処: localStorageをクリアして再登録
  ```javascript
  localStorage.removeItem('ap2_cp_passkey_registered');
  ```
  その後、ページをリロードすると再度プロンプトが表示されます

### 6.3 ログインに失敗する

**症状**: 「ログインに失敗しました」エラー

**原因**:
1. メールアドレスが未登録
2. 別のデバイス・ブラウザで登録したPasskeyを使用しようとしている
3. sign_counterが巻き戻った（リプレイ攻撃検知）
4. 誤ってCredential Provider用のPasskeyでShopping Agentにログインしようとしている

**解決策**:
- 正しいメールアドレスを入力
- 登録したデバイス・ブラウザでログイン
- Passkeyが複数ある場合、**Shopping Agent用（localhost:8000）**を選択
- パスワードマネージャーで確認: 正しいPasskeyを選択
- 新しいPasskeyを登録

### 6.4 「user_id not provided」エラー

**症状**: バックエンドログに「ValueError: user_id is required」

**原因**: JWT認証なしでチャットAPIにアクセスしようとしている

**解決策**:
1. ログイン画面からPasskeyでログイン
2. フロントエンドから`Authorization: Bearer <token>`ヘッダーが送信されているか確認
3. JWTトークンが有効期限内か確認（`localStorage.getItem('ap2_access_token')`）

### 6.5 JWTトークンがlocalStorageにない

**原因**: Passkey認証は成功したがJWT発行に失敗

**デバッグ**:
```bash
# バックエンドログを確認
cd v2/services/shopping_agent
tail -f logs/shopping_agent.log

# ブラウザのDevToolsコンソールを確認
localStorage.getItem('ap2_access_token')
```

**解決策**:
- `JWT_SECRET_KEY`が設定されているか確認
- バックエンドの再起動
- ブラウザのlocalStorageをクリアして再登録

### 6.6 支払い時にCredential Provider Passkeyが認識されない

**症状**: 支払い方法選択後、「Passkey not registered」エラー

**原因**:
1. Credential Provider用Passkeyを登録していない（スキップした）
2. Credential ProviderのデータベースにPasskeyが保存されていない
3. Shopping Agent用PasskeyとCredential Provider用Passkeyを混同している

**解決策**:
1. チャット画面でCredential Provider用Passkeyを登録
2. データベース確認:
   ```bash
   sqlite3 /app/v2/data/credential_provider.db "SELECT * FROM passkey_credentials;"
   ```
3. パスワードマネージャーで確認: **Credential Provider用（localhost:8003）**を選択

---

## 7. API仕様

### 7.1 Shopping Agent Passkey登録（Layer 1）

**エンドポイント**: `POST /auth/passkey/register/challenge`

**リクエスト**:
```json
{
  "username": "bugsbunny",
  "email": "bugsbunny@gmail.com"
}
```

**レスポンス**:
```json
{
  "challenge": "base64url_encoded_challenge",
  "user_id": "usr_1234567890abcdef",
  "rp_name": "AP2 Demo Shopping Agent",
  "rp_id": "localhost",
  "timeout": 60000
}
```

**エンドポイント**: `POST /auth/passkey/register`

**リクエスト**:
```json
{
  "username": "bugsbunny",
  "email": "bugsbunny@gmail.com",
  "credential_id": "base64url_credential_id",
  "public_key": "base64url_cose_public_key",
  "attestation_object": "base64url_attestation",
  "client_data_json": "base64url_client_data",
  "transports": ["internal"]
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
    "email": "bugsbunny@gmail.com"
  }
}
```

### 7.2 Shopping Agent Passkeyログイン（Layer 1）

**エンドポイント**: `POST /auth/passkey/login/challenge`

**リクエスト**:
```json
{
  "email": "bugsbunny@gmail.com"
}
```

**レスポンス**:
```json
{
  "challenge": "base64url_encoded_challenge",
  "rp_id": "localhost",
  "allowed_credentials": [
    {
      "id": "base64url_credential_id",
      "transports": ["internal"]
    }
  ],
  "timeout": 60000
}
```

**エンドポイント**: `POST /auth/passkey/login`

**リクエスト**:
```json
{
  "email": "bugsbunny@gmail.com",
  "credential_id": "base64url_credential_id",
  "authenticator_data": "base64url_authenticator_data",
  "client_data_json": "base64url_client_data",
  "signature": "base64url_signature",
  "user_handle": "base64url_user_handle"
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
    "email": "bugsbunny@gmail.com"
  }
}
```

### 7.3 Credential Provider Passkey登録（Layer 2）

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

**特記事項**:
- Shopping Agent登録とは**別のPasskey**を生成
- Relying Party ID: `localhost:8003`
- 支払い方法選択時のWebAuthn署名に使用

### 7.4 現在のユーザー情報取得

**エンドポイント**: `GET /auth/users/me`

**ヘッダー**:
```
Authorization: Bearer <access_token>
```

**レスポンス**:
```json
{
  "id": "usr_1234567890abcdef",
  "username": "bugsbunny",
  "email": "bugsbunny@gmail.com",
  "created_at": "2025-10-25T10:30:00Z",
  "is_active": true
}
```

---

## 8. 本番環境デプロイ（AP2完全準拠）

### 8.1 必須設定項目

1. **JWT_SECRET_KEY**: ランダムな32文字以上の文字列
2. **WEBAUTHN_RP_ID（Shopping Agent）**: `shop.example.com`
3. **WEBAUTHN_RP_ID（Credential Provider）**: `credentials.example.com`（Shopping Agentとは**異なるドメイン**を推奨）
4. **WEBAUTHN_RP_NAME**: サービス名（例: `My AP2 Shopping Service`）
5. **CORS設定**: フロントエンドのドメインを許可

**重要**: 本番環境では、Shopping AgentとCredential Providerを**異なるサブドメイン**にデプロイすることを推奨します：

```
Shopping Agent:      https://shop.example.com      (Layer 1)
Credential Provider: https://credentials.example.com (Layer 2)
Frontend:            https://app.example.com
```

これにより、WebAuthn標準に完全準拠し、各サービスのPasskeyが明確に分離されます。

### 8.2 HTTPS必須

WebAuthnはHTTPSまたはlocalhost以外では動作しません。本番環境では必ずHTTPSを使用してください。

### 8.3 データベース

本番環境では、SQLiteではなくPostgreSQLやMySQLの使用を推奨します：

```python
# v2/common/database.py
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost/ap2_prod")
```

**重要**: Shopping AgentとCredential Providerは**別々のデータベース**を使用します。Passkeyテーブルも分離されているため、データベースマイグレーション時は両方のデータベースを更新してください。

---

## 9. まとめ：AP2完全準拠の2層Passkey認証

### 9.1 なぜこのアーキテクチャを採用したか？

1. **AP2仕様準拠**: Intent/Cart/Payment Mandateへの署名には、ユーザーの明示的な同意が必要
2. **WebAuthn標準準拠**: 異なるRelying Party間でPasskeyを共有しない
3. **セキュリティ強化**: 2層認証により、JWTだけでは決済できない
4. **ユーザビリティ**: パスワードマネージャーで複数Passkeyを自動管理

### 9.2 Passkeyの使い分け

| Passkey | 用途 | 認証タイミング | rpId |
|---------|------|---------------|------|
| **Shopping Agent** | チャット画面へのアクセス | ログイン時 | `localhost:8000` |
| **Credential Provider** | 支払い方法選択の承認 | 支払い時 | `localhost:8003` |

### 9.3 今後の拡張性

この2層認証アーキテクチャは、以下のAP2仕様にも対応可能です：

- **Step-up認証**: 高額決済時の追加認証（既に実装済み）
- **Multi-factor Authentication**: 複数の認証方法の組み合わせ
- **Delegate Mandate**: 代理人による決済の承認
- **Recurring Payment**: 定期支払いの自動承認

---

## 10. 参考資料

- **AP2 Protocol**: https://ap2-protocol.org/specification/
- **WebAuthn W3C標準**: https://www.w3.org/TR/webauthn-2/
- **SimpleWebAuthn公式ドキュメント**: https://simplewebauthn.dev/
- **FIDO Alliance**: https://fidoalliance.org/
- **Passkey.org（ユーザー向け情報）**: https://www.passkeys.io/

---

**最終更新**: 2025年10月25日
**バージョン**: 2.0（AP2完全準拠版）
