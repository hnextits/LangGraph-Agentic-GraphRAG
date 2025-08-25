/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  env: {
    PORT: process.env.NEXT_PUBLIC_PORT
  },
  // Next.js 서버 포트 설정
  experimental: {
    serverComponentsExternalPackages: []
  }
};

module.exports = nextConfig;
