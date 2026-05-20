export const JOBOPS_SESSION_COOKIE_NAME = "jobops_session";

const PROTECTED_API_PROXY_PATHS = [
  "/api/command-center",
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
  if (sessionCookieValue) {
    return undefined;
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

  const loginUrl = new URL(request.url);
  loginUrl.pathname = loginPath;
  loginUrl.search = "";
  loginUrl.searchParams.set("returnTo", `${requestUrl.pathname}${requestUrl.search}`);

  return Response.redirect(loginUrl, 307);
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
