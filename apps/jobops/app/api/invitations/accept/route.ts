import { NextResponse } from "next/server";
import { getDashboardBasePathFromRequestPath, redirectResponse } from "../../../../lib/dashboard-auth";
import { getJobOpsApiServerConfig } from "../../../../lib/server-env";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const formData = await request.formData();
  const token = formData.get("token");
  const username = formData.get("username");
  const displayName = formData.get("displayName");
  const password = formData.get("password");
  if (typeof token !== "string" || !token.trim()) {
    return NextResponse.json({ ok: false, error: "Invite token is required." }, { status: 400 });
  }
  if (
    typeof username !== "string" ||
    !username.trim() ||
    typeof displayName !== "string" ||
    !displayName.trim() ||
    typeof password !== "string" ||
    !password
  ) {
    return NextResponse.json({ ok: false, error: "Username, display name, and password are required." }, { status: 400 });
  }

  let config: Awaited<ReturnType<typeof getJobOpsApiServerConfig>>;
  try {
    config = await getJobOpsApiServerConfig();
  } catch (error) {
    return NextResponse.json(
      { ok: false, error: error instanceof Error ? error.message : "JobOps server configuration is invalid." },
      { status: 503 }
    );
  }

  const apiResponse = await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/invitations/accept`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-JobOps-Internal-Key": config.internalApiKey
    },
    body: JSON.stringify({ token, username, display_name: displayName, password })
  });

  if (!apiResponse.ok) {
    const payload = await apiResponse.json();
    return NextResponse.json(payload, { status: apiResponse.status });
  }

  const requestUrl = new URL(request.url);
  const basePath = getDashboardBasePathFromRequestPath(requestUrl.pathname);
  const response = redirectResponse(basePath || "/", 303);
  const setCookie = apiResponse.headers.get("set-cookie");
  if (setCookie) {
    response.headers.set("Set-Cookie", setCookie);
  }
  return response;
}
