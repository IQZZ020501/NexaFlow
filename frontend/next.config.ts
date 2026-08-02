import type { NextConfig } from "next"

// Dev proxy target; production deployments route /api through a reverse proxy.
const BACKEND_ORIGIN = process.env.NEXAFLOW_API_PROXY ?? "http://localhost:8000"

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${BACKEND_ORIGIN}/api/:path*` },
      { source: "/health", destination: `${BACKEND_ORIGIN}/health` },
    ]
  },
}

export default nextConfig
