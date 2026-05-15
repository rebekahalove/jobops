import {
  createDashboardAuthClearCookieHeader,
  getDashboardAuthEnvironment,
  getDashboardBasePathFromRequestPath
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
  return new Response(null, {
    headers: {
      Location: new URL(`${basePath}/login` || "/login", requestUrl).toString(),
      "Set-Cookie": createDashboardAuthClearCookieHeader(getDashboardAuthEnvironment())
    },
    status: 303
  });
}
