import { proxyJobOpsApi } from "../../../../../../lib/jobops-api-proxy";

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ applicationId: string }>;
};

export async function POST(request: Request, context: RouteContext) {
  const { applicationId } = await context.params;
  return proxyJobOpsApi(request, `/v1/applications/${applicationId}/requirements/extract`, { method: "POST" });
}
