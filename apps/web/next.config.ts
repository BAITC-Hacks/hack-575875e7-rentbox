import type { NextConfig } from "next"

const nextConfig: NextConfig = {
  devIndicators: false,
  transpilePackages: ["@workspace/ui"],
}

export default nextConfig
