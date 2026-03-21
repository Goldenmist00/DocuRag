import type { createAuthServer as CreateAuthServerType } from "@neondatabase/auth/next/server";

let _auth: Awaited<ReturnType<typeof CreateAuthServerType>> | null = null;

export async function getAuth() {
  if (!_auth) {
    const { createAuthServer } = await import("@neondatabase/auth/next/server");
    _auth = createAuthServer();
  }
  return _auth;
}

export async function getNeonAuth() {
  const { neonAuth } = await import("@neondatabase/auth/next/server");
  return neonAuth;
}
