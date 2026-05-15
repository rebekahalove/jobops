import { NextResponse } from "next/server";
import {
  constantTimeEqualText,
  createDashboardAuthToken,
  getDashboardAuthEnvironment,
  getDashboardBasePathFromRequestPath,
  isDashboardAuthConfigured,
  resolveSafeDashboardReturnTo,
  setDashboardAuthCookie
} from "../../../../lib/dashboard-auth";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const requestUrl = new URL(request.url);
  const basePath = getDashboardBasePathFromRequestPath(requestUrl.pathname);
  const loginPath = `${basePath}/login` || "/login";
  const fallbackPath = basePath || "/";
  const formData = await request.formData();
  const returnTo = resolveSafeDashboardReturnTo(formData.get("returnTo"), fallbackPath);
  const env = getDashboardAuthEnvironment();

  if (env.authDisabled) {
    return NextResponse.redirect(new URL(returnTo, requestUrl), { status: 303 });
  }

  if (!isDashboardAuthConfigured(env)) {
    return NextResponse.json(
      {
        ok: false,
        error: "JobOps private preview access is not configured."
      },
      { status: 503 }
    );
  }

  const submittedPassword = formData.get("password");
  const passwordMatches =
    typeof submittedPassword === "string" && (await constantTimeEqualText(submittedPassword, env.password ?? ""));

  if (!passwordMatches) {
    const loginUrl = new URL(loginPath, requestUrl);
    loginUrl.searchParams.set("error", "1");
    loginUrl.searchParams.set("returnTo", returnTo);

    return NextResponse.redirect(loginUrl, { status: 303 });
  }

  const response = NextResponse.redirect(new URL(returnTo, requestUrl), { status: 303 });
  setDashboardAuthCookie(response, await createDashboardAuthToken(env.cookieSecret ?? ""), env);

  return response;
}
