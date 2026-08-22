import type { NextConfig } from "next";

const apiTarget = process.env.KOMI_API_URL ?? "http://127.0.0.1:8766";
const projectRoot = process.cwd();

const nextConfig: NextConfig = {
  outputFileTracingRoot: projectRoot,
  turbopack: { root: projectRoot },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiTarget}/api/:path*` }];
  },
};

export default nextConfig;
