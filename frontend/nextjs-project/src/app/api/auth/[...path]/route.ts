export const dynamic = "force-dynamic";

async function getHandler() {
  const { authApiHandler } = await import("@neondatabase/auth/next/server");
  return authApiHandler();
}

export async function GET(req: Request) {
  return (await getHandler()).GET(req);
}

export async function POST(req: Request) {
  return (await getHandler()).POST(req);
}

export async function PUT(req: Request) {
  return (await getHandler()).PUT(req);
}

export async function DELETE(req: Request) {
  return (await getHandler()).DELETE(req);
}

export async function PATCH(req: Request) {
  return (await getHandler()).PATCH(req);
}
