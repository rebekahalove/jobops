import { parseJsonBody, proxyJobOpsApi } from "../../../../../../lib/jobops-api-proxy";

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ userId: string }>;
};

export async function PATCH(request: Request, context: RouteContext) {
  const { userId } = await context.params;
  const body = await parseJsonBody(request);
  return proxyJobOpsApi(request, `/v1/admin/users/${encodeURIComponent(userId)}/role`, {
    method: "PATCH",
    body: JSON.stringify(body ?? {})
  });
}
