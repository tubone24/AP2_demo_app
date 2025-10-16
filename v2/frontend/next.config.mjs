/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',

  // プロキシは使わず、ブラウザから直接バックエンドAPIにアクセス
  // NEXT_PUBLIC_SHOPPING_AGENT_URL と NEXT_PUBLIC_CREDENTIAL_PROVIDER_URL を使用
};

export default nextConfig;
