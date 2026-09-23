import type { NextConfig } from "next"

const nextConfig: NextConfig = {
  devIndicators: false,
  // The helper allows up to 45 seconds for the OpenAI response.
  experimental: { proxyTimeout: 60_000 },
  transpilePackages: ["@workspace/ui"],
  async rewrites() {
    const backend = (
      process.env.RENTBOX_API_URL ??
      process.env.NEXT_PUBLIC_API_URL ??
      "http://127.0.0.1:8000/api"
    ).replace(/\/$/, "")
    return [{ source: "/api/:path*", destination: `${backend}/:path*` }]
  },
}

export default nextConfig
