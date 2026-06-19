import { NextResponse } from "next/server";
import { getJobOpsApiServerConfig } from "../../../../../lib/server-env";

export const runtime = "nodejs";

export async function GET(request: Request) {
  let config: Awaited<ReturnType<typeof getJobOpsApiServerConfig>>;
  try {
    config = await getJobOpsApiServerConfig();
  } catch (error) {
    return NextResponse.json(
      {
        ok: false,
        error: error instanceof Error ? error.message : "JobOps server configuration is invalid."
      },
      { status: 503 }
    );
  }

  try {
    const apiResponse = await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/companies/discovery-runs/latest`, {
      cache: "no-store",
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
        error: "Company discovery diagnostics API is unavailable. Start the FastAPI service on JOBOPS_API_BASE_URL."
      },
      { status: 503 }
    );
  }
}

function forwardCookieHeader(request: Request): Record<string, string> {
  const cookie = request.headers.get("cookie");
  return cookie ? { Cookie: cookie } : {};
}
