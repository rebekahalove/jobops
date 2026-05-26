import { proxyJobOpsApi } from "../../../../lib/jobops-api-proxy";

export const runtime = "nodejs";

export async function GET(request: Request) {
  return proxyJobOpsApi(request, "/v1/admin/alpha-requests");
}
