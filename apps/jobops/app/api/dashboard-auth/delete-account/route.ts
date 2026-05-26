import { NextResponse } from "next/server";
import { getJobOpsApiServerConfig } from "../../../../lib/server-env";

export const runtime = "nodejs";

export async function DELETE(request: Request) {
  let body: { confirmation?: string; currentPassword?: string; candidateProfileId?: string };
  try {
    body = (await request.json()) as { confirmation?: string; currentPassword?: string; candidateProfileId?: string };
  } catch {
    return NextResponse.json({ ok: false, error: "Request body must be valid JSON." }, { status: 400 });
  }

  try {
    const config = await getJobOpsApiServerConfig();
    const apiResponse = await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/auth/account`, {
      method: "DELETE",
      headers: {
        "Content-Type": "application/json",
        "X-JobOps-Internal-Key": config.internalApiKey,
        ...forwardCookieHeader(request)
      },
      body: JSON.stringify({
        confirmation: body.confirmation,
        current_password: body.currentPassword,
        candidate_profile_id: body.candidateProfileId
      })
    });
    const payload = await apiResponse.json();
    const response = NextResponse.json(payload, { status: apiResponse.status });
    const setCookie = apiResponse.headers.get("set-cookie");
    if (setCookie) {
      response.headers.append("Set-Cookie", setCookie);
    }
    return response;
  } catch {
    return NextResponse.json({ ok: false, error: "Account deletion service is unavailable." }, { status: 503 });
  }
}

function forwardCookieHeader(request: Request): Record<string, string> {
  const cookie = request.headers.get("cookie");
  return cookie ? { Cookie: cookie } : {};
}
