import { parseJsonBody, proxyJobOpsApi } from "../../../../lib/jobops-api-proxy";
import { withInviteBaseUrl } from "../../../../lib/admin-invite-base-url";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = await parseJsonBody(request);
  return proxyJobOpsApi(request, "/v1/admin/invitations", {
    method: "POST",
    body: JSON.stringify(withInviteBaseUrl(request, body))
  });
}
