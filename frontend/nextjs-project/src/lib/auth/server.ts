import { createAuthServer, neonAuth } from "@neondatabase/auth/next/server";

export const auth = createAuthServer();
export { neonAuth };
