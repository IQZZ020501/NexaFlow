import type { NextConfig } from "next"

// Dev proxy target; production deployments route /api through a reverse proxy.
// Use 127.0.0.1, not localhost: the dev backend binds IPv4 only, and Node's
// happy-eyeballs may pick ::1 for `localhost`, making proxied requests fail
// with ECONNRESET/500.
const BACKEND_ORIGIN = process.env.NEXAFLOW_API_PROXY ?? "http://127.0.0.1:8000"
const isDevelopment = process.env.NODE_ENV === "development"

const HOST_CSP = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDevelopment ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https:",
  "font-src 'self' data:",
  "connect-src 'self'",
  "worker-src 'self' blob:",
  "frame-src 'self'",
  "frame-ancestors 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ")

const nextConfig: NextConfig = {
  reactStrictMode: true,
  logging: { incomingRequests: false },
  allowedDevOrigins: ["127.0.0.1"],
  output: "standalone",
  // Repository agent guidance is maintained in the root AGENTS.md.
  agentRules: false,
  // Keep the proxy request-body ceiling aligned with the backend upload limit.
  experimental: {
    optimizePackageImports: ["lucide-react", "recharts", "@ant-design/icons"],
    proxyClientMaxBodySize: "100mb",
    proxyTimeout: 120_000,
  },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${BACKEND_ORIGIN}/api/:path*` },
      ...(isDevelopment
        ? [
            { source: "/docs", destination: `${BACKEND_ORIGIN}/docs` },
            {
              source: "/openapi.json",
              destination: `${BACKEND_ORIGIN}/openapi.json`,
            },
          ]
        : []),
      { source: "/health", destination: `${BACKEND_ORIGIN}/health` },
    ]
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
          {
            key: "Referrer-Policy",
            value: "strict-origin-when-cross-origin",
          },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
          { key: "Content-Security-Policy", value: HOST_CSP },
        ],
      },
      {
        // Only public viewer assets are readable by the opaque preview iframe.
        source: "/file-preview/:path*",
        headers: [
          { key: "Access-Control-Allow-Origin", value: "*" },
          { key: "Cache-Control", value: "public, max-age=3600" },
        ],
      },
      {
        // HTML and RSC payloads reference build-specific chunks. Do not let a
        // deployment leave an old shell in a shared cache.
        source: "/((?!_next/static/|_next/image/|file-preview/).*)",
        headers: [{ key: "Cache-Control", value: "no-store" }],
      },
    ]
  },
}

export default nextConfig
