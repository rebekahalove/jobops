import { NextResponse } from "next/server";
import { getJobOpsApiServerConfig } from "../../../../lib/server-env";

export const runtime = "nodejs";

export async function POST(request: Request) {
  let body: { currentPassword?: string; newPassword?: string };
  try {
    body = (await request.json()) as { currentPassword?: string; newPassword?: string };
  } catch {
    return NextResponse.json({ ok: false, error: "Request body must be valid JSON." }, { status: 400 });
  }

  try {
    const config = await getJobOpsApiServerConfig();
    const apiResponse = await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/auth/password/change`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-JobOps-Internal-Key": config.internalApiKey,
        ...forwardCookieHeader(request)
      },
      body: JSON.stringify({
        current_password: body.currentPassword,
        new_password: body.newPassword
      })
    });
    const payload = await apiResponse.json();
    return NextResponse.json(payload, { status: apiResponse.status });
  } catch {
    return NextResponse.json({ ok: false, error: "Password change service is unavailable." }, { status: 503 });
  }
}

function forwardCookieHeader(request: Request): Record<string, string> {
  const cookie = request.headers.get("cookie");
  return cookie ? { Cookie: cookie } : {};
}
