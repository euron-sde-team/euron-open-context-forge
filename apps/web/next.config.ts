import type { NextConfig } from "next";

/**
 * Same-origin deployment: the browser only ever talks to this origin. Next proxies the
 * admin API, the OpenAI-compatible gateway and the health probes to the API service, so
 * the httpOnly session cookie stays first-party and no CORS is needed. In production a
 * load balancer may route these paths straight to the API before they reach Next.
 */
const apiInternal = (process.env.API_INTERNAL_URL || "http://localhost:4330").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  // One self-contained server bundle (`node server.js`), the unit a container image ships.
  output: "standalone",
  outputFileTracingRoot: __dirname,
  poweredByHeader: false,
  devIndicators: false,
  reactStrictMode: true,
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${apiInternal}/api/:path*` },
      { source: "/v1/:path*", destination: `${apiInternal}/v1/:path*` },
      { source: "/healthz", destination: `${apiInternal}/healthz` },
      { source: "/readyz", destination: `${apiInternal}/readyz` },
      { source: "/docs", destination: `${apiInternal}/docs` },
      { source: "/openapi.json", destination: `${apiInternal}/openapi.json` },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
