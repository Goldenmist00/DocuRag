import { NextRequest, NextResponse } from "next/server";

export function middleware(req: NextRequest) {
  // Guard: if env vars aren't set, skip auth and let the request through
  if (!process.env.NEON_AUTH_BASE_URL) {
    return NextResponse.next();
  }

  // Dynamically require so it doesn't execute at build/import time
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { neonAuthMiddleware } = require("@neondatabase/auth/next/server");
  return neonAuthMiddleware({ loginUrl: "/login" })(req);
}

export const config = {
  matcher: ["/books/:path*", "/dashboard/:path*"],
};
