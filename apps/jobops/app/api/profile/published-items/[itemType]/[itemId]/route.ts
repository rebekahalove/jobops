import { NextResponse } from "next/server";
import { getJobOpsApiServerConfig } from "../../../../../../lib/server-env";

export const runtime = "nodejs";

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ itemType: string; itemId: string }> }
) {
  const { itemType, itemId } = await params;
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
    const apiResponse = await fetch(
      `${config.apiBaseUrl.replace(/\/$/, "")}/v1/profile/published-items/${encodeURIComponent(itemType)}/${encodeURIComponent(itemId)}`,
      {
        body: await request.text(),
        cache: "no-store",
        headers: {
          "Content-Type": "application/json",
          "X-JobOps-Internal-Key": config.internalApiKey,
          ...forwardCookieHeader(request)
        },
        method: "PATCH"
      }
    );
    const payload = await apiResponse.json();
    if (!apiResponse.ok && payload && typeof payload === "object" && "detail" in payload) {
      return NextResponse.json({ ok: false, error: String(payload.detail) }, { status: apiResponse.status });
    }
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
