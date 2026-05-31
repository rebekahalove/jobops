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
    const payload = await parseUpstreamPayload(apiResponse);
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

async function parseUpstreamPayload(response: Response) {
  const text = await response.text();
  if (!text) {
    return response.ok ? { ok: true } : { ok: false, error: `JobOps API request failed with HTTP ${response.status}.` };
  }
  try {
    return JSON.parse(text);
  } catch {
    return {
      ok: false,
      error: response.ok ? "JobOps API returned a non-JSON response." : `JobOps API request failed with HTTP ${response.status}.`,
      upstreamBodyPreview: text.slice(0, 300)
    };
  }
}
