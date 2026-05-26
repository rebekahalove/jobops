import { proxyJobOpsApi } from "../../../../../lib/jobops-api-proxy";

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ userId: string }>;
};

export async function DELETE(request: Request, context: RouteContext) {
  const { userId } = await context.params;
  return proxyJobOpsApi(request, `/v1/admin/users/${encodeURIComponent(userId)}`, { method: "DELETE" });
}
