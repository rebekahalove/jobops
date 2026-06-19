import {
  getDashboardBasePathFromRequestPath,
  redirectResponse,
  resolveSafeDashboardReturnTo
} from "../../../../lib/dashboard-auth";
import { normalizeProxiedSetCookieForRequest } from "../../../../lib/session-cookie";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const requestUrl = new URL(request.url);
  const basePath = getDashboardBasePathFromRequestPath(requestUrl.pathname);
  const loginPath = `${basePath}/login` || "/login";
  const fallbackPath = basePath || "/";
  const formData = await request.formData();
  const returnTo = resolveSafeDashboardReturnTo(formData.get("returnTo"), fallbackPath);
  const submittedUsername = formData.get("username");
  const username = typeof submittedUsername === "string" ? submittedUsername.trim().toLowerCase() : "";
  const submittedPassword = formData.get("password");
  const password = typeof submittedPassword === "string" ? submittedPassword : "";

  if (!username || !password) {
    const loginUrl = new URL(loginPath, "https://jobops.local");
    loginUrl.searchParams.set("error", "1");
    loginUrl.searchParams.set("returnTo", returnTo);

    return redirectResponse(`${loginUrl.pathname}${loginUrl.search}`, 303);
  }

  const backendSession = await createBackendSessionCookie(username, password);
  if (backendSession.passwordResetRequired) {
    const resetUrl = new URL(basePath ? `${basePath}/reset-password` : "/reset-password", "https://jobops.local");
    resetUrl.searchParams.set("username", username);
    resetUrl.searchParams.set("returnTo", returnTo);
    return redirectResponse(`${resetUrl.pathname}${resetUrl.search}`, 303);
  }
  if (backendSession.unknownUsername || backendSession.invalidCredentials) {
    const loginUrl = new URL(loginPath, "https://jobops.local");
    loginUrl.searchParams.set("error", "1");
    loginUrl.searchParams.set("returnTo", returnTo);

    return redirectResponse(`${loginUrl.pathname}${loginUrl.search}`, 303);
  }
  if (!backendSession.setCookie) {
    return Response.json(
      {
        ok: false,
        error: backendSession.error
      },
      { status: 503 }
    );
  }

  const response = new Response(null, {
    headers: {
      Location: returnTo
    },
    status: 303
  });
  response.headers.append("Set-Cookie", normalizeProxiedSetCookieForRequest(backendSession.setCookie, request));
  return response;
}

async function createBackendSessionCookie(username: string, password: string) {
  try {
    const { getJobOpsApiServerConfig } = await import("../../../../lib/server-env");
    const config = await getJobOpsApiServerConfig();
    const apiResponse = await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/auth/session`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-JobOps-Internal-Key": config.internalApiKey
      },
      body: JSON.stringify({
        username,
        password
      })
    });
    if (apiResponse.status === 403 && (await isPasswordResetRequired(apiResponse))) {
      return {
        passwordResetRequired: true
      };
    }
    if (apiResponse.status === 404) {
      return {
        unknownUsername: true
      };
    }
    if (apiResponse.status === 401 && (await isInvalidCredentials(apiResponse))) {
      return {
        invalidCredentials: true
      };
    }
    if (!apiResponse.ok) {
      return {
        error: `JobOps backend session could not be created: ${await readBackendError(apiResponse)}`
      };
    }

    const setCookie = apiResponse.headers.get("set-cookie");
    return setCookie
      ? { setCookie }
      : { error: "JobOps backend session could not be created: backend did not return a session cookie." };
  } catch (error) {
    return {
      error: error instanceof Error ? `JobOps backend session could not be created: ${error.message}` : "JobOps backend session could not be created."
    };
  }
}

async function isPasswordResetRequired(response: Response) {
  try {
    const payload = await response.clone().json();
    return payload?.detail?.code === "password_reset_required";
  } catch {
    return false;
  }
}

async function isInvalidCredentials(response: Response) {
  try {
    const payload = await response.clone().json();
    return payload?.detail === "Username or password is incorrect.";
  } catch {
    return false;
  }
}

async function readBackendError(response: Response) {
  try {
    const payload = await response.json();
    if (typeof payload?.detail === "string") {
      return payload.detail;
    }
    if (typeof payload?.error === "string") {
      return payload.error;
    }
  } catch {
  }

  return `${response.status} ${response.statusText || "Backend request failed"}`;
}
