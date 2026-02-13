/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  swcMinify: true,
  compiler: {
    removeConsole: process.env.NODE_ENV === 'production',
    styledComponents: true,
  },
  env: {
    PORT: process.env.NEXT_PUBLIC_PORT
  },
  experimental: {
    optimizePackageImports: [
      '@mui/material',
      '@mui/icons-material',
      'lucide-react',
      'react-syntax-highlighter'
    ],
  },
  // 정적 자원 압축 및 캐싱 최적화
  compress: true,
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:8505/api/:path*',
      },
    ];
  },
};

module.exports = nextConfig;
