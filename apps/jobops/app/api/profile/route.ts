import { NextResponse } from "next/server";
import { getJobOpsApiServerConfig } from "../../../lib/server-env";

export const runtime = "nodejs";

export async function GET(request: Request) {
  return proxyProfileRequest(request, "/v1/profile/current");
}

export async function PATCH(request: Request) {
  return proxyProfileRequest(request, "/v1/profile/current", {
    body: await request.text(),
    method: "PATCH"
  });
}

export async function POST(request: Request) {
  let body: { action?: string };
  try {
    body = (await request.json()) as { action?: string };
  } catch {
    return NextResponse.json({ ok: false, error: "Request body must be valid JSON." }, { status: 400 });
  }

  if (body.action !== "publish") {
    return NextResponse.json({ ok: false, error: "Unsupported profile action." }, { status: 400 });
  }

  return proxyProfileRequest(request, "/v1/profile/publish", {
    body: "{}",
    method: "POST"
  });
}

async function proxyProfileRequest(
  request: Request,
  backendPath: string,
  init: { body?: string; method?: string } = {}
) {
  let config: Awaited<ReturnType<typeof getJobOpsApiServerConfig>>;
  try {
    config = await getJobOpsApiServerConfig();
  } catch (error) {
    return NextResponse.json(
      { ok: false, error: error instanceof Error ? error.message : "JobOps server configuration is invalid." },
      { status: 503 }
    );
  }

  try {
    const apiResponse = await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}${backendPath}`, {
      body: init.body,
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-JobOps-Internal-Key": config.internalApiKey,
        ...forwardCookieHeader(request)
      },
      method: init.method ?? "GET"
    });
    const payload = await apiResponse.json();
    return NextResponse.json(payload, { status: apiResponse.status });
  } catch {
    return NextResponse.json(
      { ok: false, error: "Profile API is unavailable. Start the FastAPI service on JOBOPS_API_BASE_URL." },
      { status: 503 }
    );
  }
}

function forwardCookieHeader(request: Request): Record<string, string> {
  const cookie = request.headers.get("cookie");
  return cookie ? { Cookie: cookie } : {};
}
