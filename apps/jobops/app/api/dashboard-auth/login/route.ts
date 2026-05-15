import {
  constantTimeEqualText,
  createDashboardAuthSetCookieHeader,
  createDashboardAuthToken,
  getDashboardAuthEnvironment,
  getDashboardBasePathFromRequestPath,
  isDashboardAuthConfigured,
  resolveSafeDashboardReturnTo
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
    return Response.redirect(new URL(returnTo, requestUrl), 303);
  }

  if (!isDashboardAuthConfigured(env)) {
    return Response.json(
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

    return Response.redirect(loginUrl, 303);
  }

  return new Response(null, {
    headers: {
      Location: new URL(returnTo, requestUrl).toString(),
      "Set-Cookie": createDashboardAuthSetCookieHeader(await createDashboardAuthToken(env.cookieSecret ?? ""), env)
    },
    status: 303
  });
}
