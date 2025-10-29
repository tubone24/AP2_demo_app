# 支払い方法登録機能のテスト手順

## 概要

このドキュメントは、CP（Credential Provider）用のPasskey登録後に支払い方法を登録する機能のテスト手順を記載しています。

## 実装内容

### 1. フロントエンド（v2/frontend）

#### パスキー登録画面
- **ファイル**: `app/auth/register-passkey/page.tsx`
- **機能**:
  - CP用のPasskey登録
  - WebAuthn Registration Ceremony
  - 登録成功後、支払い方法登録フォームを表示

#### 支払い方法登録フォーム
- **ファイル**: `components/payment/AddPaymentMethodForm.tsx`
- **機能**:
  - カード情報入力（カード番号、名義人、有効期限、CVV、郵便番号）
  - カードブランド自動判定（Visa, Mastercard, Amex, JCB）
  - American Express の場合、自動的に `requires_step_up: true` を設定（3D Secure対応）
  - バリデーション機能
  - AP2完全準拠のリクエスト送信

#### Passkey認証ユーティリティ
- **ファイル**: `lib/passkey.ts`
- **機能**:
  - `registerCredentialProviderPasskey()` - CP用Passkey登録
  - `isCredentialProviderPasskeyRegistered()` - Passkey登録状態確認

### 2. バックエンド（v2/services/credential_provider）

#### Credential Provider API
- **ファイル**: `provider.py`
- **エンドポイント**:
  - `POST /register/passkey/challenge` - Passkey登録用challenge生成
  - `POST /register/passkey` - Passkey登録処理
  - `GET /payment-methods` - 支払い方法一覧取得
  - `POST /payment-methods` - 支払い方法追加（今回実装）
  - `POST /payment-methods/tokenize` - 支払い方法トークン化

#### データベース
- **ファイル**: `v2/common/database.py`
- **テーブル**:
  - `passkey_credentials` - Passkey認証情報
  - `payment_methods` - 支払い方法情報（AP2完全準拠）

### 3. AP2プロトコル準拠

- カード情報を含む完全な支払い方法データを保存
- American Expressの場合、Step-up認証（3D Secure）を自動設定
- トークン化API対応
- Credential Provider内部での永続化（SQLite）

## テスト手順

### 事前準備

1. **環境変数の確認**
   ```bash
   cd /Users/kagadminmac/project/ap2/v2

   # .envファイルが存在するか確認
   ls -la .env

   # フロントエンドの.envファイルを確認
   ls -la frontend/.env.local
   ```

2. **Dockerサービスの起動**
   ```bash
   cd /Users/kagadminmac/project/ap2/v2
   docker compose up -d
   ```

3. **サービスの起動確認**
   ```bash
   # すべてのサービスが起動しているか確認
   docker compose ps

   # Credential Providerのログを確認
   docker compose logs credential_provider --tail=50
   ```

4. **フロントエンドの起動**
   ```bash
   cd /Users/kagadminmac/project/ap2/v2/frontend
   npm run dev
   ```

### テストシナリオ1: 新規ユーザー登録からPasskey登録、支払い方法登録まで

#### Step 1: ユーザー登録
1. ブラウザで `http://localhost:3000/auth/register` にアクセス
2. メールアドレスとパスワードを入力してユーザー登録
3. 登録成功後、自動的にログイン

#### Step 2: CP用Passkey登録
1. `http://localhost:3000/auth/register-passkey` にアクセス
2. 「Passkeyを登録」ボタンをクリック
3. WebAuthn Registration Ceremonyが開始される
   - macOS: Touch IDプロンプトが表示される
   - Windows: Windows Helloプロンプトが表示される
4. 認証を完了する
5. 「✅ Passkey登録が完了しました！」メッセージが表示される

#### Step 3: 支払い方法登録フォームの表示
1. Passkey登録成功後、自動的に支払い方法登録ダイアログが表示される
2. フォームに以下の項目が表示されることを確認:
   - カード番号
   - カード名義人
   - 有効期限（月・年）
   - セキュリティコード
   - 郵便番号

#### Step 4: Visaカードの登録
1. 以下のテストカード情報を入力:
   ```
   カード番号: 4242 4242 4242 4242
   カード名義人: TARO YAMADA
   有効期限: 12/2026
   セキュリティコード: 123
   郵便番号: 100-0001
   ```
2. 「登録する」ボタンをクリック
3. 「✅ 支払い方法を登録しました」メッセージが表示される
4. 自動的にチャット画面（`/chat`）にリダイレクトされる

#### Step 5: データベース確認
```bash
# Credential Providerのログで登録確認
docker compose logs credential_provider --tail=100 | grep "add_payment_method"

# データベースに保存されているか確認
docker compose exec credential_provider sqlite3 /app/v2/data/credential_provider.db \
  "SELECT id, user_id, json_extract(payment_data, '$.brand') as brand, json_extract(payment_data, '$.last4') as last4 FROM payment_methods;"
```

### テストシナリオ2: American Expressカードの登録（Step-up認証フラグ）

#### Step 1-3: ユーザー登録〜Passkey登録（シナリオ1と同じ）

#### Step 4: American Expressカードの登録
1. 以下のテストカード情報を入力:
   ```
   カード番号: 3782 822463 10005
   カード名義人: HANAKO SUZUKI
   有効期限: 12/2027
   セキュリティコード: 1234
   郵便番号: 150-0001
   ```
2. 「登録する」ボタンをクリック
3. 「✅ 支払い方法を登録しました」メッセージが表示される

#### Step 5: Step-up認証フラグの確認
```bash
# データベースで requires_step_up フラグを確認
docker compose exec credential_provider sqlite3 /app/v2/data/credential_provider.db \
  "SELECT id, json_extract(payment_data, '$.brand') as brand, json_extract(payment_data, '$.requires_step_up') as requires_step_up FROM payment_methods WHERE json_extract(payment_data, '$.brand') = 'Amex';"
```

期待される出力:
```
pm_xxxxxxxx|Amex|1
```

### テストシナリオ3: エラーハンドリング

#### 無効なカード番号
1. カード番号に「1234」と入力
2. 「登録する」ボタンをクリック
3. エラーメッセージ「カード番号は13〜16桁で入力してください」が表示される

#### 空のカード名義人
1. カード番号に「4242 4242 4242 4242」と入力
2. カード名義人を空欄のまま
3. 「登録する」ボタンをクリック
4. エラーメッセージ「カード名義人を入力してください」が表示される

#### 無効な郵便番号
1. 郵便番号に「12345」と入力
2. 「登録する」ボタンをクリック
3. エラーメッセージ「郵便番号を正しく入力してください（例: 100-0001）」が表示される

### テストシナリオ4: スキップ機能

1. 支払い方法登録ダイアログで「後で登録」ボタンをクリック
2. ダイアログが閉じ、チャット画面（`/chat`）にリダイレクトされる
3. 支払い方法が登録されていないことを確認

## API動作確認

### Passkey登録APIの動作確認

```bash
# Challenge生成
curl -X POST http://localhost:8003/register/passkey/challenge \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test_user_001",
    "user_email": "test@example.com"
  }'
```

期待されるレスポンス:
```json
{
  "challenge": "...",
  "rp": {
    "id": "localhost",
    "name": "AP2 Credential Provider"
  },
  "user": {
    "id": "test_user_001",
    "name": "test@example.com",
    "displayName": "test@example.com"
  },
  "pubKeyCredParams": [...],
  "timeout": 60000,
  "attestation": "none",
  "authenticatorSelection": {...}
}
```

### 支払い方法一覧取得APIの動作確認

```bash
curl "http://localhost:8003/payment-methods?user_id=test_user_001"
```

期待されるレスポンス:
```json
{
  "user_id": "test_user_001",
  "payment_methods": [
    {
      "id": "pm_xxxxxxxx",
      "type": "basic-card",
      "brand": "Visa",
      "last4": "4242",
      "display_name": "Visaカード (****4242)",
      ...
    }
  ]
}
```

## トラブルシューティング

### Issue: Passkeyプロンプトが表示されない
**原因**: WebAuthnがサポートされていないブラウザ
**解決策**: Chrome, Safari, Edge, Firefoxの最新版を使用してください

### Issue: 支払い方法登録後、エラーが発生する
**原因**: Credential Providerが起動していない
**解決策**:
```bash
docker compose logs credential_provider
docker compose restart credential_provider
```

### Issue: データベースにデータが保存されない
**原因**: データベースファイルのパーミッション問題
**解決策**:
```bash
# データベースディレクトリの確認
docker compose exec credential_provider ls -la /app/v2/data/

# 必要に応じてパーミッション変更
docker compose exec credential_provider chmod 777 /app/v2/data/
```

## まとめ

この実装により、以下の機能が完全にAP2プロトコルに準拠した形で実装されました：

1. ✅ CP用Passkey登録（WebAuthn準拠）
2. ✅ 支払い方法登録フォーム（カード情報入力）
3. ✅ カードブランド自動判定
4. ✅ American Express の Step-up認証フラグ自動設定
5. ✅ バリデーション機能
6. ✅ データベース永続化（SQLite）
7. ✅ エラーハンドリング
8. ✅ スキップ機能

## 次のステップ

- [ ] 支払い方法の編集・削除機能
- [ ] 複数支払い方法の管理
- [ ] 支払い方法選択UI（チャット画面）
- [ ] Step-up認証フローの完全実装（3D Secure画面表示）
- [ ] トークン化APIの統合テスト
