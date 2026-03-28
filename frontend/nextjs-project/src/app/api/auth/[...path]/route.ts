export const dynamic = "force-dynamic";

type RouteContext = { params: Promise<{ path: string[] }> };

async function getHandler() {
  const { authApiHandler } = await import("@neondatabase/auth/next/server");
  return authApiHandler();
}

export async function GET(req: Request, ctx: RouteContext) {
  return (await getHandler()).GET(req, ctx);
}

export async function POST(req: Request, ctx: RouteContext) {
  return (await getHandler()).POST(req, ctx);
}

export async function PUT(req: Request, ctx: RouteContext) {
  return (await getHandler()).PUT(req, ctx);
}

export async function DELETE(req: Request, ctx: RouteContext) {
  return (await getHandler()).DELETE(req, ctx);
}

export async function PATCH(req: Request, ctx: RouteContext) {
  return (await getHandler()).PATCH(req, ctx);
}
