/** @type {import('next').NextConfig} */
// CONSTRAINT #10: output 'standalone' is what makes the Dockerfile's
// node server.js CMD work without shipping node_modules in the final layer.
//
// The rewrite below is a fallback, not the primary path: CONSTRAINT #11's
// system nginx already proxies /api/ -> the FastAPI container for the
// whole LXC (it also fronts /flower/, which this app doesn't touch). This
// rewrite exists so the dashboard is independently functional if hit
// directly on :3000 - `API_INTERNAL_URL` defaults to the Docker Compose
// service DNS name, which resolves on the shared `fantasy` network with no
// extra config.
const API_INTERNAL_URL = process.env.API_INTERNAL_URL || "http://api:8000";

const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  async rewrites() {
    return [
      // Sports v1 intentionally includes the /api prefix in FastAPI so its
      // versioned contract remains distinct from the legacy routes below.
      { source: "/api/v1/:path*", destination: `${API_INTERNAL_URL}/api/v1/:path*` },
      { source: "/api/:path*", destination: `${API_INTERNAL_URL}/:path*` },
    ];
  },
};

module.exports = nextConfig;
