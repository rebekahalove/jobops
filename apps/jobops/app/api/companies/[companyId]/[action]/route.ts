import { NextResponse } from "next/server";
import { getJobOpsApiServerConfig } from "../../../../../lib/server-env";

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ companyId: string; action: string }>;
};

const ALLOWED_ACTIONS = new Set(["archive", "restore", "avoid", "watch"]);

export async function POST(request: Request, context: RouteContext) {
  const { companyId, action } = await context.params;
  if (!ALLOWED_ACTIONS.has(action)) {
    return NextResponse.json({ ok: false, error: "Unsupported company action." }, { status: 400 });
  }

  let config: Awaited<ReturnType<typeof getJobOpsApiServerConfig>>;
  try {
    config = await getJobOpsApiServerConfig();
  } catch (error) {
    return serverConfigErrorResponse(error);
  }

  const url = new URL(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/companies/${encodeURIComponent(companyId)}/${action}`);

  try {
    const apiResponse = await fetch(url, {
      method: "POST",
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
        error: "Company action API is unavailable. Start the FastAPI service on JOBOPS_API_BASE_URL."
      },
      { status: 503 }
    );
  }
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
