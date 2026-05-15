import { NextResponse } from "next/server";
import {
  clearDashboardAuthCookie,
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
  const response = NextResponse.redirect(new URL(`${basePath}/login` || "/login", requestUrl), { status: 303 });
  clearDashboardAuthCookie(response, getDashboardAuthEnvironment());

  return response;
}
