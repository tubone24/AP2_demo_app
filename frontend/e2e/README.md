# E2E Tests with Playwright

このディレクトリには、AP2 Demo Appのエンドツーエンド（E2E）テストが含まれています。

## セットアップ

Playwrightのテストを実行する前に、依存関係をインストールしてください。

```bash
cd frontend
npm install
npx playwright install chromium
```

## テストの実行

### ローカル環境でテストを実行

開発サーバーを自動的に起動してテストを実行します。

```bash
npm run test:e2e
```

### UIモードでテストを実行

Playwright UI モードでテストを実行すると、テストの実行をインタラクティブに確認できます。

```bash
npm run test:e2e:ui
```

### ヘッドレスモードを無効にしてテストを実行

ブラウザの動作を視覚的に確認しながらテストを実行します。

```bash
npm run test:e2e:headed
```

### レポートの表示

テスト実行後にHTMLレポートを表示します。

```bash
npm run test:e2e:report
```

## テストシナリオ

### home.spec.ts
- ホームページの表示確認
- ナビゲーションリンクの動作確認
- ページ遷移のテスト

### auth.spec.ts
- ログインフォームの表示確認
- フォームバリデーションのテスト
- ログインエラーハンドリングのテスト
- ページ遷移のテスト

### example.spec.ts
- 基本的なページ読み込みテスト
- シンプルな動作確認

## data-testid属性

テストの信頼性を高めるため、主要なUI要素には`data-testid`属性を追加しています。

### 命名規則

- ページ全体: `{page-name}-page` (例: `home-page`, `login-page`)
- フォーム: `{form-name}-form` (例: `login-form`)
- 入力フィールド: `{field-name}-input` (例: `login-email-input`)
- ボタン: `{action}-button` (例: `login-submit-button`)
- ナビゲーション: `nav-{target}` (例: `nav-shopping-chat`)
- 商品カード: `product-card-{id}` (例: `product-card-123`)

## トラブルシューティング

### テストが失敗する場合

1. サーバーが起動しているか確認してください
2. ポート3000が使用可能か確認してください
3. Playwrightブラウザが正しくインストールされているか確認してください

```bash
npx playwright install chromium
```

## 参考資料

- [Playwright Documentation](https://playwright.dev/)
- [Playwright Test API](https://playwright.dev/docs/api/class-test)
- [Best Practices](https://playwright.dev/docs/best-practices)
