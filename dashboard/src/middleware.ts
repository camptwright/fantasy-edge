import { createRemoteJWKSet, jwtVerify } from "jose";
import { NextResponse, type NextRequest } from "next/server";

export async function middleware(request: NextRequest) {
  // Enabled only on the separately deployed, loopback-published Mac preview.
  // Host checking is defense in depth, not a replacement for that network boundary.
  if (process.env.FANTASY_LOCAL_ONLY === "true") {
    const host = request.headers.get("host") || "";
    const local = /^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$/.test(host);
    const origin = request.headers.get("origin");
    if (!local || request.headers.has("cf-connecting-ip") || request.headers.has("cf-access-jwt-assertion") ||
        (origin && origin !== `http://${host}`)) {
      return new NextResponse("Local preview only", { status: 403 });
    }
    return NextResponse.next();
  }
  const team = process.env.CF_ACCESS_TEAM_DOMAIN;
  const audience = process.env.CF_ACCESS_AUD;
  // The dashboard has no host port publish (see docker-compose.yml) - the
  // only ingress path is reekserver-1's shared cloudflared container, so
  // Cloudflare Access is always mandatory. Both env vars are hard-required
  // at the compose level (`:?`); this check exists only as defense in depth
  // and fails closed, not open, if they're ever missing at runtime.
  if (!team || !audience) {
    return new NextResponse("Cloudflare Access is not configured", { status: 503 });
  }
  const token = request.headers.get("Cf-Access-Jwt-Assertion");
  if (!token) return new NextResponse("Cloudflare Access authentication required", { status: 401 });
  try {
    const jwks = createRemoteJWKSet(new URL(`https://${team}/cdn-cgi/access/certs`));
    await jwtVerify(token, jwks, { audience });
    return NextResponse.next();
  } catch {
    return new NextResponse("Invalid Cloudflare Access credential", { status: 401 });
  }
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
