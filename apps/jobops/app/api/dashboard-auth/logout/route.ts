import { getDashboardAuthEnvironment, getDashboardBasePathFromRequestPath, JOBOPS_SESSION_COOKIE_NAME, redirectResponse } from "../../../../lib/dashboard-auth";

export const runtime = "nodejs";

export async function GET(request: Request) {
  return clearCookieAndRedirect(request);
}

export async function POST(request: Request) {
  return clearCookieAndRedirect(request);
}

async function clearCookieAndRedirect(request: Request) {
  const requestUrl = new URL(request.url);
  const basePath = getDashboardBasePathFromRequestPath(requestUrl.pathname);
  const loginPath = basePath ? `${basePath}/login` : "/login";
  await revokeBackendSession(request);
  const response = redirectResponse(loginPath, 303);
  const env = getDashboardAuthEnvironment();
  response.headers.set(
    "Set-Cookie",
    `${JOBOPS_SESSION_COOKIE_NAME}=; Max-Age=0; Path=/; SameSite=Lax; HttpOnly${env.isProduction ? "; Secure" : ""}`
  );
  return response;
}

async function revokeBackendSession(request: Request) {
  const sessionCookie = getSessionCookie(request.headers.get("cookie"));
  if (!sessionCookie) {
    return;
  }

  try {
    const { getJobOpsApiServerConfig } = await import("../../../../lib/server-env");
    const config = await getJobOpsApiServerConfig();
    await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/auth/logout`, {
      method: "POST",
      headers: {
        Cookie: `${JOBOPS_SESSION_COOKIE_NAME}=${sessionCookie}`,
        "X-JobOps-Internal-Key": config.internalApiKey
      }
    });
  } catch {
  }
}

function getSessionCookie(cookieHeader: string | null) {
  if (!cookieHeader) {
    return null;
  }

  for (const part of cookieHeader.split(";")) {
    const [rawName, ...rawValue] = part.trim().split("=");
    if (rawName === JOBOPS_SESSION_COOKIE_NAME) {
      return rawValue.join("=");
    }
  }

  return null;
}
