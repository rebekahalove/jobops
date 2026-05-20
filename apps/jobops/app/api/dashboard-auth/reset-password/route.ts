import { getDashboardBasePathFromRequestPath, redirectResponse, resolveSafeDashboardReturnTo } from "../../../../lib/dashboard-auth";
import { getJobOpsApiServerConfig } from "../../../../lib/server-env";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const requestUrl = new URL(request.url);
  const basePath = getDashboardBasePathFromRequestPath(requestUrl.pathname);
  const resetPath = basePath ? `${basePath}/reset-password` : "/reset-password";
  const fallbackPath = basePath || "/";
  const formData = await request.formData();
  const returnTo = resolveSafeDashboardReturnTo(formData.get("returnTo"), fallbackPath);
  const username = textValue(formData.get("username")).toLowerCase();
  const currentPassword = textValue(formData.get("currentPassword"));
  const newPassword = textValue(formData.get("newPassword"));

  if (!username || !currentPassword || !newPassword) {
    return redirectToReset(resetPath, username, returnTo);
  }

  const backendSession = await resetBackendPassword(username, currentPassword, newPassword);
  if (!backendSession.setCookie) {
    return redirectToReset(resetPath, username, returnTo);
  }

  const response = new Response(null, {
    headers: {
      Location: returnTo
    },
    status: 303
  });
  response.headers.append("Set-Cookie", backendSession.setCookie);
  return response;
}

function redirectToReset(resetPath: string, username: string, returnTo: string) {
  const resetUrl = new URL(resetPath, "https://jobops.local");
  resetUrl.searchParams.set("error", "1");
  if (username) {
    resetUrl.searchParams.set("username", username);
  }
  resetUrl.searchParams.set("returnTo", returnTo);
  return redirectResponse(`${resetUrl.pathname}${resetUrl.search}`, 303);
}

async function resetBackendPassword(username: string, currentPassword: string, newPassword: string) {
  try {
    const config = await getJobOpsApiServerConfig();
    const apiResponse = await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/auth/password/reset`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-JobOps-Internal-Key": config.internalApiKey
      },
      body: JSON.stringify({
        username,
        current_password: currentPassword,
        new_password: newPassword
      })
    });

    const setCookie = apiResponse.headers.get("set-cookie");
    return apiResponse.ok && setCookie ? { setCookie } : {};
  } catch {
    return {};
  }
}

function textValue(value: FormDataEntryValue | null) {
  return typeof value === "string" ? value.trim() : "";
}
