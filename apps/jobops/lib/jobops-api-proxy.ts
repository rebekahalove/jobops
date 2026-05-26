import { NextResponse } from "next/server";
import { getJobOpsApiServerConfig } from "./server-env";

export const runtime = "nodejs";

export async function proxyJobOpsApi(request: Request, apiPath: string, init: RequestInit = {}) {
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
    const apiResponse = await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}${apiPath}`, {
      ...init,
      cache: "no-store",
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        "X-JobOps-Internal-Key": config.internalApiKey,
        ...forwardCookieHeader(request),
        ...(init.headers || {})
      }
    });
    const payload = await apiResponse.json();
    return NextResponse.json(payload, { status: apiResponse.status });
  } catch {
    return NextResponse.json({ ok: false, error: "JobOps API is unavailable." }, { status: 503 });
  }
}

export async function parseJsonBody(request: Request) {
  try {
    return await request.json();
  } catch {
    return undefined;
  }
}

function forwardCookieHeader(request: Request): Record<string, string> {
  const cookie = request.headers.get("cookie");
  return cookie ? { Cookie: cookie } : {};
}
