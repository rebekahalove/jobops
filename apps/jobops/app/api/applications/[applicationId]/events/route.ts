import { NextResponse } from "next/server";
import { getJobOpsApiServerConfig } from "../../../../../lib/server-env";

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ applicationId: string }>;
};

export async function POST(request: Request, context: RouteContext) {
  let body: unknown;

  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      {
        ok: false,
        error: "Request body must be valid JSON."
      },
      { status: 400 }
    );
  }

  const { applicationId } = await context.params;
  let config: Awaited<ReturnType<typeof getJobOpsApiServerConfig>>;
  try {
    config = await getJobOpsApiServerConfig();
  } catch {
    return missingInternalApiKeyResponse();
  }

  try {
    const apiResponse = await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/applications/${applicationId}/events`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-JobOps-Internal-Key": config.internalApiKey,
        ...forwardCookieHeader(request)
      },
      body: JSON.stringify(body)
    });
    const payload = await apiResponse.json();
    return NextResponse.json(payload, { status: apiResponse.status });
  } catch {
    return NextResponse.json(
      {
        ok: false,
        error: "Application tracker API is unavailable. Start the FastAPI service on JOBOPS_API_BASE_URL."
      },
      { status: 503 }
    );
  }
}

function forwardCookieHeader(request: Request): Record<string, string> {
  const cookie = request.headers.get("cookie");
  return cookie ? { Cookie: cookie } : {};
}

function missingInternalApiKeyResponse() {
  return NextResponse.json(
    {
      ok: false,
      error: "JobOps internal API key is not configured on the server."
    },
    { status: 503 }
  );
}
