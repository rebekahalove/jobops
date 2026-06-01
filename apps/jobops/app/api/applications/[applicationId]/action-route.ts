import { NextResponse } from "next/server";
import { getJobOpsApiServerConfig } from "../../../../lib/server-env";

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ applicationId: string }>;
};

export async function POST(request: Request, context: RouteContext) {
  const { applicationId } = await context.params;
  const action = applicationActionFromUrl(request.url);
  let config: Awaited<ReturnType<typeof getJobOpsApiServerConfig>>;
  try {
    config = await getJobOpsApiServerConfig();
  } catch (error) {
    return serverConfigErrorResponse(error);
  }

  try {
    const apiResponse = await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/applications/${applicationId}/${action}`, {
      method: "POST",
      headers: {
        "X-JobOps-Internal-Key": config.internalApiKey,
        ...forwardCookieHeader(request)
      }
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

function applicationActionFromUrl(url: string) {
  const action = lastPathSegment(url);
  if (action === "restore") {
    return "restore";
  }
  if (action === "reject") {
    return "reject";
  }
  if (action === "withdraw") {
    return "withdraw";
  }
  if (action === "reopen") {
    return "reopen";
  }
  return "archive";
}

function lastPathSegment(url: string) {
  return new URL(url).pathname.split("/").filter(Boolean).pop();
}

function forwardCookieHeader(request: Request): Record<string, string> {
  const cookie = request.headers.get("cookie");
  return cookie ? { Cookie: cookie } : {};
}

function serverConfigErrorResponse(error: unknown) {
  return NextResponse.json(
    {
      ok: false,
      error: error instanceof Error ? error.message : "JobOps server configuration is invalid."
    },
    { status: 503 }
  );
}
