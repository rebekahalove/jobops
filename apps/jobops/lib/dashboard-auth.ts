export const DASHBOARD_AUTH_COOKIE_NAME = "jobops_dashboard_auth";
export const DASHBOARD_AUTH_COOKIE_MAX_AGE_SECONDS = 12 * 60 * 60;

const TOKEN_VERSION = "v1";
const TOKEN_PURPOSE = "jobops-dashboard-auth";
const PROTECTED_API_PROXY_PATHS = [
  "/api/command-center",
  "/api/profile-intake",
  "/api/profile-draft",
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
  cookieSecret?: string;
  isProduction: boolean;
  password?: string;
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
    cookieSecret: process.env.JOBOPS_DASHBOARD_COOKIE_SECRET,
    isProduction,
    password: process.env.JOBOPS_DASHBOARD_PASSWORD
  };
}

export function isDashboardAuthConfigured(env = getDashboardAuthEnvironment()) {
  return Boolean(env.password && env.cookieSecret);
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
    isDashboardAuthRoute(pathname, dashboardBasePath) ||
    (!isProtectedApiPath && !isProtectedUiPath)
  ) {
    return undefined;
  }

  const env = options.env ?? getDashboardAuthEnvironment();

  if (env.authDisabled) {
    return undefined;
  }

  if (!isDashboardAuthConfigured(env)) {
    return failClosedResponse(isProtectedApiPath);
  }

  const cookieValue = readCookie(request.headers.get("cookie"), DASHBOARD_AUTH_COOKIE_NAME);
  if (cookieValue && (await verifyDashboardAuthToken(cookieValue, env.cookieSecret ?? ""))) {
    return undefined;
  }

  if (isProtectedApiPath) {
    return jsonResponse(
      {
        ok: false,
        error: "JobOps dashboard authentication is required."
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

export async function createDashboardAuthToken(secret: string, now = Date.now()) {
  const expiresAt = now + DASHBOARD_AUTH_COOKIE_MAX_AGE_SECONDS * 1000;
  const nonce = randomBase64Url(16);
  const payload = `${TOKEN_VERSION}.${expiresAt}.${nonce}`;
  const signature = await signTokenPayload(payload, secret);

  return `${payload}.${signature}`;
}

export async function verifyDashboardAuthToken(token: string, secret: string, now = Date.now()) {
  const parts = token.split(".");
  if (parts.length !== 4 || parts[0] !== TOKEN_VERSION) {
    return false;
  }

  const [, expiresAtText] = parts;
  const expiresAt = Number(expiresAtText);
  if (!Number.isSafeInteger(expiresAt) || expiresAt <= now) {
    return false;
  }

  const payload = parts.slice(0, 3).join(".");
  const expectedSignature = await signTokenPayload(payload, secret);
  return timingSafeEqualBytes(base64UrlToBytes(parts[3]), base64UrlToBytes(expectedSignature));
}

export async function constantTimeEqualText(left: string, right: string) {
  const crypto = getWebCrypto();
  const [leftDigest, rightDigest] = await Promise.all([
    crypto.subtle.digest("SHA-256", encodeText(left)),
    crypto.subtle.digest("SHA-256", encodeText(right))
  ]);

  return timingSafeEqualBytes(new Uint8Array(leftDigest), new Uint8Array(rightDigest));
}

export function createDashboardAuthSetCookieHeader(token: string, env = getDashboardAuthEnvironment()) {
  return serializeCookie(DASHBOARD_AUTH_COOKIE_NAME, token, {
    httpOnly: true,
    maxAge: DASHBOARD_AUTH_COOKIE_MAX_AGE_SECONDS,
    path: "/",
    sameSite: "Lax",
    secure: env.isProduction
  });
}

export function createDashboardAuthClearCookieHeader(env = getDashboardAuthEnvironment()) {
  return serializeCookie(DASHBOARD_AUTH_COOKIE_NAME, "", {
    httpOnly: true,
    maxAge: 0,
    path: "/",
    sameSite: "Lax",
    secure: env.isProduction
  });
}

export function getDashboardBasePathFromRequestPath(pathname: string): "" | "/jobops" {
  return pathname.startsWith("/jobops/") ? "/jobops" : "";
}

function failClosedResponse(isApiPath: boolean) {
  const error = "JobOps private preview access is not configured.";

  if (isApiPath) {
    return jsonResponse({ ok: false, error }, 503);
  }

  return new Response(error, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8"
    },
    status: 503
  });
}

function isDashboardLoginPath(pathname: string, loginPath: "/login" | "/jobops/login") {
  return pathname === loginPath;
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

async function signTokenPayload(payload: string, secret: string) {
  const crypto = getWebCrypto();
  const key = await crypto.subtle.importKey(
    "raw",
    encodeText(secret),
    {
      hash: "SHA-256",
      name: "HMAC"
    },
    false,
    ["sign"]
  );
  const signature = await crypto.subtle.sign("HMAC", key, encodeText(`${TOKEN_PURPOSE}.${payload}`));

  return bytesToBase64Url(new Uint8Array(signature));
}

function randomBase64Url(byteLength: number) {
  const bytes = new Uint8Array(byteLength);
  getWebCrypto().getRandomValues(bytes);
  return bytesToBase64Url(bytes);
}

function timingSafeEqualBytes(left: Uint8Array, right: Uint8Array) {
  if (left.length !== right.length) {
    return false;
  }

  let diff = 0;
  for (let index = 0; index < left.length; index += 1) {
    diff |= left[index] ^ right[index];
  }

  return diff === 0;
}

function bytesToBase64Url(bytes: Uint8Array) {
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }

  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/u, "");
}

function base64UrlToBytes(value: string) {
  try {
    const padded = value.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(value.length / 4) * 4, "=");
    const binary = atob(padded);
    const bytes = new Uint8Array(binary.length);

    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }

    return bytes;
  } catch {
    return new Uint8Array();
  }
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

function serializeCookie(
  name: string,
  value: string,
  options: {
    httpOnly: boolean;
    maxAge: number;
    path: string;
    sameSite: "Lax";
    secure: boolean;
  }
) {
  const parts = [`${name}=${value}`, `Max-Age=${options.maxAge}`, `Path=${options.path}`, `SameSite=${options.sameSite}`];

  if (options.httpOnly) {
    parts.push("HttpOnly");
  }

  if (options.secure) {
    parts.push("Secure");
  }

  return parts.join("; ");
}

function encodeText(value: string) {
  return new TextEncoder().encode(value);
}

function getWebCrypto() {
  if (!globalThis.crypto?.subtle) {
    throw new Error("Web Crypto is required for JobOps dashboard authentication.");
  }

  return globalThis.crypto;
}
