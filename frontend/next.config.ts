import type { NextConfig } from "next";

// Same-origin proxy so session/CSRF cookies work without CORS.
const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${process.env.BACKEND_URL ?? "http://localhost:8000"}/api/:path*` }];
  },
};

export default nextConfig;
