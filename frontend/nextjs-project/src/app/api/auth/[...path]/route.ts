export const dynamic = "force-dynamic";

async function getHandler() {
  const { authApiHandler } = await import("@neondatabase/auth/next/server");
  return authApiHandler();
}

export async function GET(req: Request, ctx: { params: { path: string[] } }) {
  const h = await getHandler();
  return h.GET(req, ctx);
}

export async function POST(req: Request, ctx: { params: { path: string[] } }) {
  const h = await getHandler();
  return h.POST(req, ctx);
}

export async function PUT(req: Request, ctx: { params: { path: string[] } }) {
  const h = await getHandler();
  return h.PUT(req, ctx);
}

export async function DELETE(req: Request, ctx: { params: { path: string[] } }) {
  const h = await getHandler();
  return h.DELETE(req, ctx);
}

export async function PATCH(req: Request, ctx: { params: { path: string[] } }) {
  const h = await getHandler();
  return h.PATCH(req, ctx);
}
