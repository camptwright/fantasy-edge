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
    return [{ source: "/api/:path*", destination: `${API_INTERNAL_URL}/:path*` }];
  },
  // A plain HTTP redirect with a real Location header for a browser or curl
  // hitting `/` directly. next/navigation's redirect() (the App Router
  // runtime helper, previously used in app/page.tsx) is built for RSC
  // client-side transitions instead: it returns 307 with `Vary: RSC,
  // Next-Router-State-Tree, ...` and NO Location header, which only the
  // Next.js client router (not a real HTTP client) knows how to follow.
  // Verified against this app's own build: curl -I on `/` came back 307
  // with a body but no Location header at all. Config-level redirects()
  // resolve before the App Router even matches a page, so this doesn't
  // need an app/page.tsx at `/` - there isn't one.
  async redirects() {
    return [{ source: "/", destination: "/signals", permanent: false }];
  },
};

module.exports = nextConfig;
