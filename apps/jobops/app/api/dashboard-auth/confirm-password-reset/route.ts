import { getDashboardBasePathFromRequestPath, redirectResponse, resolveSafeDashboardReturnTo } from "../../../../lib/dashboard-auth";
import { getJobOpsApiServerConfig } from "../../../../lib/server-env";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const requestUrl = new URL(request.url);
  const basePath = getDashboardBasePathFromRequestPath(requestUrl.pathname);
  const resetPath = basePath ? `${basePath}/reset-password` : "/reset-password";
  const formData = await request.formData();
  const returnTo = resolveSafeDashboardReturnTo(formData.get("returnTo"), basePath || "/");
  const token = textValue(formData.get("token"));
  const newPassword = textValue(formData.get("newPassword"));

  if (!token || !newPassword) {
    return redirectToReset(resetPath, token, returnTo);
  }

  try {
    const config = await getJobOpsApiServerConfig();
    const apiResponse = await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/auth/password/reset/confirm`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-JobOps-Internal-Key": config.internalApiKey
      },
      body: JSON.stringify({
        token,
        new_password: newPassword
      })
    });
    if (apiResponse.ok) {
      return redirectResponse(`${basePath}/login?reset=1&returnTo=${encodeURIComponent(returnTo)}`, 303);
    }
  } catch {
  }

  return redirectToReset(resetPath, token, returnTo);
}

function redirectToReset(resetPath: string, token: string, returnTo: string) {
  const resetUrl = new URL(resetPath, "https://jobops.local");
  resetUrl.searchParams.set("error", "1");
  if (token) {
    resetUrl.searchParams.set("token", token);
  }
  resetUrl.searchParams.set("returnTo", returnTo);
  return redirectResponse(`${resetUrl.pathname}${resetUrl.search}`, 303);
}

function textValue(value: FormDataEntryValue | null) {
  return typeof value === "string" ? value.trim() : "";
}
