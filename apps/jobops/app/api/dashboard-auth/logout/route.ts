import {
  createDashboardAuthClearCookieHeader,
  getDashboardAuthEnvironment,
  getDashboardBasePathFromRequestPath,
  redirectResponse
} from "../../../../lib/dashboard-auth";

export const runtime = "nodejs";

export function GET(request: Request) {
  return clearCookieAndRedirect(request);
}

export function POST(request: Request) {
  return clearCookieAndRedirect(request);
}

function clearCookieAndRedirect(request: Request) {
  const requestUrl = new URL(request.url);
  const basePath = getDashboardBasePathFromRequestPath(requestUrl.pathname);
  const loginPath = basePath ? `${basePath}/login` : "/login";
  const response = redirectResponse(loginPath, 303);
  response.headers.set("Set-Cookie", createDashboardAuthClearCookieHeader(getDashboardAuthEnvironment()));
  return response;
}
