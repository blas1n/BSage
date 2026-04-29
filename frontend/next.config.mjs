/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: ['bsserver'],
  devIndicators: false,
  // Preserve the previous Vercel rewrite: proxy /api/* to the BSage backend.
  // In production on Vercel this matches the rewrites previously declared in
  // vercel.json (now deleted, since Next.js auto-detects on Vercel).
  // In dev this replaces the Vite proxy in vite.config.ts.
  async rewrites() {
    const backend =
      process.env.BSAGE_API_TARGET || 'https://api-sage.bsvibe.dev';
    return [
      {
        source: '/api/:path*',
        destination: `${backend}/api/:path*`,
      },
      {
        source: '/ws',
        destination: `${backend}/ws`,
      },
    ];
  },
};

export default nextConfig;
