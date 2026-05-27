import { parseJsonBody, proxyJobOpsApi } from "../../../../../../lib/jobops-api-proxy";
import { withInviteBaseUrl } from "../../../../../../lib/admin-invite-base-url";

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ requestId: string }>;
};

export async function POST(request: Request, context: RouteContext) {
  const { requestId } = await context.params;
  const body = await parseJsonBody(request);
  return proxyJobOpsApi(request, `/v1/admin/alpha-requests/${encodeURIComponent(requestId)}/invite`, {
    method: "POST",
    body: JSON.stringify(withInviteBaseUrl(request, body))
  });
}
