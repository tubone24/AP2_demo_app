/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',

  // プロキシは使わず、ブラウザから直接バックエンドAPIにアクセス
  // NEXT_PUBLIC_SHOPPING_AGENT_URL と NEXT_PUBLIC_CREDENTIAL_PROVIDER_URL を使用

  // 画像設定（AP2完全準拠）
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'placehold.co',
      },
    ],
    // ローカルパス（/assets/...）の画像は最適化なしで表示
    unoptimized: process.env.NODE_ENV === 'development',
  },
};

export default nextConfig;
