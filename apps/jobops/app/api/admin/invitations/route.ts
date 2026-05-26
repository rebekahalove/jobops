import { parseJsonBody, proxyJobOpsApi } from "../../../../lib/jobops-api-proxy";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = await parseJsonBody(request);
  return proxyJobOpsApi(request, "/v1/admin/invitations", {
    method: "POST",
    body: JSON.stringify(body ?? {})
  });
}
