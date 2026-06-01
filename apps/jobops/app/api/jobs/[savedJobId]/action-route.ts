import { NextResponse } from "next/server";
import { getJobOpsApiServerConfig } from "../../../../lib/server-env";

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ savedJobId: string }>;
};

export async function POST(request: Request, context: RouteContext) {
  const { savedJobId } = await context.params;
  const action = jobActionFromUrl(request.url);
  let config: Awaited<ReturnType<typeof getJobOpsApiServerConfig>>;
  try {
    config = await getJobOpsApiServerConfig();
  } catch (error) {
    return serverConfigErrorResponse(error);
  }

  try {
    const apiResponse = await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/jobs/${savedJobId}/${action}`, {
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
        error: "Saved jobs API is unavailable. Start the FastAPI service on JOBOPS_API_BASE_URL."
      },
      { status: 503 }
    );
  }
}

function jobActionFromUrl(url: string) {
  const action = lastPathSegment(url);
  if (action === "restore") {
    return "restore";
  }
  if (action === "unfavorite") {
    return "unfavorite";
  }
  if (action === "favorite") {
    return "favorite";
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
