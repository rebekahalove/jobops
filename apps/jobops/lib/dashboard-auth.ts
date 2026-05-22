export const JOBOPS_SESSION_COOKIE_NAME = "jobops_session";

const PROTECTED_API_PROXY_PATHS = [
  "/api/command-center",
  "/api/profile",
  "/api/profile-intake",
  "/api/profile-draft",
  "/api/companies",
  "/api/applications"
] as const;
const STANDALONE_DASHBOARD_PATHS = [
  "/",
  "/profile",
  "/companies",
  "/jobs",
  "/applications",
  "/materials",
  "/follow-ups",
  "/fit-scoring"
] as const;

export type DashboardAuthEnvironment = {
  authDisabled: boolean;
  isProduction: boolean;
};

export type DashboardGateOptions = {
  dashboardBasePath: "" | "/jobops";
  env?: DashboardAuthEnvironment;
  loginPath: "/login" | "/jobops/login";
};

export function getDashboardAuthEnvironment(): DashboardAuthEnvironment {
  const isProduction = process.env.NODE_ENV === "production" || process.env.APP_ENV === "prod";

  return {
    authDisabled: !isProduction && process.env.JOBOPS_DASHBOARD_AUTH_DISABLED === "true",
    isProduction
  };
}

export async function gateDashboardRequest(request: Request, options: DashboardGateOptions) {
  const { dashboardBasePath, loginPath } = options;
  const requestUrl = new URL(request.url);
  const pathname = requestUrl.pathname;
  const isProtectedApiPath = isProtectedDashboardApiProxyPath(pathname, dashboardBasePath);
  const isProtectedUiPath = isProtectedDashboardUiPath(pathname, dashboardBasePath);

  if (
    isStaticOrFrameworkPath(pathname) ||
    isDashboardLoginPath(pathname, loginPath) ||
    isDashboardPublicInfoPath(pathname, dashboardBasePath) ||
    isDashboardPublicPortfolioPath(pathname, dashboardBasePath) ||
    isDashboardPublicApiPath(pathname, dashboardBasePath) ||
    isDashboardInvitePath(pathname, dashboardBasePath) ||
    isDashboardPrivacyPath(pathname, dashboardBasePath) ||
    isDashboardPasswordResetPath(pathname, dashboardBasePath) ||
    isDashboardAuthRoute(pathname, dashboardBasePath) ||
    (!isProtectedApiPath && !isProtectedUiPath)
  ) {
    return undefined;
  }

  const env = options.env ?? getDashboardAuthEnvironment();

  if (env.authDisabled) {
    return undefined;
  }

  const sessionCookieValue = readCookie(request.headers.get("cookie"), JOBOPS_SESSION_COOKIE_NAME);
  if (sessionCookieValue && isProtectedUiPath) {
    const backendSession = await validateBackendSession(request.headers.get("cookie"));
    if (backendSession.ok) {
      return undefined;
    }

    const loginUrl = buildLoginRedirectUrl(request.url, loginPath, requestUrl);
    return new Response(null, {
      headers: {
        Location: loginUrl.toString(),
        "Set-Cookie": clearSessionCookieHeader(env.isProduction)
      },
      status: 307
    });
  }

  if (sessionCookieValue) {
    return undefined;
  }

  if (isDashboardLandingPath(pathname, dashboardBasePath)) {
    return Response.redirect(buildPublicInfoUrl(request.url, dashboardBasePath), 307);
  }

  if (isProtectedApiPath) {
    return jsonResponse(
      {
        ok: false,
        error: "JobOps authentication is required."
      },
      401
    );
  }

  return Response.redirect(buildLoginRedirectUrl(request.url, loginPath, requestUrl), 307);
}

export function isProtectedDashboardUiPath(pathname: string, dashboardBasePath: "" | "/jobops") {
  if (dashboardBasePath) {
    return pathname === dashboardBasePath || pathname.startsWith(`${dashboardBasePath}/`);
  }

  return STANDALONE_DASHBOARD_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`));
}

export function isProtectedDashboardApiProxyPath(pathname: string, dashboardBasePath: "" | "/jobops") {
  const localPath = stripDashboardBasePath(pathname, dashboardBasePath);
  return PROTECTED_API_PROXY_PATHS.some((path) => localPath === path || localPath.startsWith(`${path}/`));
}

export function resolveSafeDashboardReturnTo(value: FormDataEntryValue | string | null | undefined, fallback: "/" | "/jobops") {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) {
    return fallback;
  }

  const basePath = fallback === "/jobops" ? "/jobops" : "";
  const loginPath = `${basePath}/login` as "/login" | "/jobops/login";

  let parsedValue: URL;
  try {
    parsedValue = new URL(value, "https://jobops.local");
  } catch {
    return fallback;
  }

  if (
    !isProtectedDashboardUiPath(parsedValue.pathname, basePath) ||
    isProtectedDashboardApiProxyPath(parsedValue.pathname, basePath) ||
    isDashboardLoginPath(parsedValue.pathname, loginPath) ||
    isDashboardAuthRoute(parsedValue.pathname, basePath)
  ) {
    return fallback;
  }

  return `${parsedValue.pathname}${parsedValue.search}`;
}

export function getDashboardBasePathFromRequestPath(pathname: string): "" | "/jobops" {
  return pathname.startsWith("/jobops/") ? "/jobops" : "";
}

function isDashboardLoginPath(pathname: string, loginPath: "/login" | "/jobops/login") {
  return pathname === loginPath;
}

function isDashboardLandingPath(pathname: string, dashboardBasePath: "" | "/jobops") {
  return stripDashboardBasePath(pathname, dashboardBasePath) === "/";
}

function isDashboardPublicInfoPath(pathname: string, dashboardBasePath: "" | "/jobops") {
  return stripDashboardBasePath(pathname, dashboardBasePath) === "/about";
}

function isDashboardPublicPortfolioPath(pathname: string, dashboardBasePath: "" | "/jobops") {
  const localPath = stripDashboardBasePath(pathname, dashboardBasePath);
  return localPath === "/portfolio" || localPath.startsWith("/portfolio/");
}

function isDashboardPublicApiPath(pathname: string, dashboardBasePath: "" | "/jobops") {
  return stripDashboardBasePath(pathname, dashboardBasePath).startsWith("/api/public/");
}

function isDashboardInvitePath(pathname: string, dashboardBasePath: "" | "/jobops") {
  const localPath = stripDashboardBasePath(pathname, dashboardBasePath);
  return localPath === "/invite" || localPath.startsWith("/invite/");
}

function isDashboardPrivacyPath(pathname: string, dashboardBasePath: "" | "/jobops") {
  return stripDashboardBasePath(pathname, dashboardBasePath) === "/privacy";
}

function isDashboardPasswordResetPath(pathname: string, dashboardBasePath: "" | "/jobops") {
  return stripDashboardBasePath(pathname, dashboardBasePath) === "/reset-password";
}

function isDashboardAuthRoute(pathname: string, dashboardBasePath: "" | "/jobops") {
  return stripDashboardBasePath(pathname, dashboardBasePath).startsWith("/api/dashboard-auth/");
}

function isStaticOrFrameworkPath(pathname: string) {
  return (
    pathname.startsWith("/_next/") ||
    pathname === "/favicon.ico" ||
    /\.(?:avif|css|gif|ico|jpg|jpeg|js|map|png|svg|txt|webp|xml)$/i.test(pathname)
  );
}

function stripDashboardBasePath(pathname: string, dashboardBasePath: "" | "/jobops") {
  if (!dashboardBasePath) {
    return pathname;
  }

  if (pathname === dashboardBasePath) {
    return "/";
  }

  return pathname.startsWith(`${dashboardBasePath}/`) ? pathname.slice(dashboardBasePath.length) : pathname;
}

function jsonResponse(body: unknown, status: number) {
  return new Response(JSON.stringify(body), {
    headers: {
      "Content-Type": "application/json"
    },
    status
  });
}

export function redirectResponse(location: string, status: 303 | 307) {
  return new Response(null, {
    headers: {
      Location: location
    },
    status
  });
}

function buildLoginRedirectUrl(requestUrl: string, loginPath: "/login" | "/jobops/login", currentUrl: URL) {
  const loginUrl = new URL(requestUrl);
  loginUrl.pathname = loginPath;
  loginUrl.search = "";
  loginUrl.searchParams.set("returnTo", `${currentUrl.pathname}${currentUrl.search}`);
  return loginUrl;
}

function buildPublicInfoUrl(requestUrl: string, dashboardBasePath: "" | "/jobops") {
  const publicInfoUrl = new URL(requestUrl);
  publicInfoUrl.pathname = `${dashboardBasePath}/about` || "/about";
  publicInfoUrl.search = "";
  return publicInfoUrl;
}

async function validateBackendSession(cookieHeader: string | null) {
  const apiBaseUrl = process.env.JOBOPS_API_BASE_URL?.replace(/\/$/, "") || "http://localhost:8000";
  const internalApiKey = process.env.JOBOPS_INTERNAL_API_KEY?.trim() || "";

  if (!internalApiKey) {
    return { ok: false };
  }

  try {
    const response = await fetch(`${apiBaseUrl}/v1/auth/me`, {
      cache: "no-store",
      headers: {
        Cookie: cookieHeader || "",
        "X-JobOps-Internal-Key": internalApiKey
      }
    });
    return { ok: response.ok };
  } catch {
    return { ok: false };
  }
}

function clearSessionCookieHeader(isProduction: boolean) {
  return `${JOBOPS_SESSION_COOKIE_NAME}=; Max-Age=0; Path=/; SameSite=Lax; HttpOnly${isProduction ? "; Secure" : ""}`;
}

function readCookie(cookieHeader: string | null, name: string) {
  if (!cookieHeader) {
    return undefined;
  }

  for (const item of cookieHeader.split(";")) {
    const [rawKey, ...rawValueParts] = item.trim().split("=");
    if (rawKey === name) {
      return rawValueParts.join("=");
    }
  }

  return undefined;
}
