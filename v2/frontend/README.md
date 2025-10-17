# AP2 Demo App v2 - Frontend

Next.js App Router + TypeScript + TailwindCSS + shadcn/ui

## セットアップ

```bash
# 依存関係インストール
npm install

# 開発サーバー起動
npm run dev

# ビルド
npm run build

# プロダクションサーバー起動
npm start
```

## 環境変数

`.env.example`を`.env.local`にコピーして設定してください：

```bash
cp .env.example .env.local
```

## プロジェクト構造

```
frontend/
├── app/                    # Next.js App Router
│   ├── layout.tsx          # ルートレイアウト
│   ├── page.tsx            # ホーム
│   ├── chat/               # Chat UI
│   └── merchant/           # Merchant管理画面
├── components/             # Reactコンポーネント
│   ├── ui/                 # shadcn/uiコンポーネント
│   ├── chat/               # Chat関連コンポーネント
│   └── merchant/           # Merchant関連コンポーネント
├── lib/                    # ユーティリティ関数
│   └── utils.ts            # cn()など
└── public/                 # 静的ファイル
```

## API プロキシ

Next.jsの`rewrites`機能で、Shopping AgentのAPIをプロキシしています：

- `/api/chat/*` → `http://localhost:8000/chat/*`
- `/api/a2a/*` → `http://localhost:8000/a2a/*`
- `/api/products/*` → `http://localhost:8000/products/*`
- `/api/transactions/*` → `http://localhost:8000/transactions/*`

## 技術スタック

- **Next.js 15** (App Router)
- **React 19**
- **TypeScript 5.6**
- **TailwindCSS 3.4**
- **shadcn/ui** (Radix UI + TailwindCSS)
- **Lucide Icons**
- **Embla Carousel** (商品カルーセル)

## 主要機能

- ✅ Chat UI（SSE/Streaming対応）
- ✅ SignaturePromptModal（WebAuthn/Passkey）
- ✅ ProductCarousel（商品カルーセル）
- ✅ Merchant管理画面（在庫管理・署名）

## 開発中の注意点

- Shopping Agentが起動していることを確認してください（port 8000）
- WebAuthn機能はHTTPS環境、またはlocalhostでのみ動作します
