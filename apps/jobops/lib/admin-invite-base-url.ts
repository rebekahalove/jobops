import { getDashboardBasePathFromRequestPath } from "./dashboard-auth";

export function withInviteBaseUrl(request: Request, body: unknown) {
  const requestUrl = new URL(request.url);
  const basePath = getDashboardBasePathFromRequestPath(requestUrl.pathname);
  const payload = isRecord(body) ? { ...body } : {};

  if (!payload.invite_base_url) {
    payload.invite_base_url = resolveInviteBaseUrl(request, requestUrl, basePath);
  }

  return payload;
}

function resolveInviteBaseUrl(request: Request, requestUrl: URL, basePath: string) {
  const configuredBaseUrl = process.env.JOBOPS_APP_BASE_URL?.trim().replace(/\/$/, "");
  if (configuredBaseUrl) {
    return configuredBaseUrl;
  }

  return `${resolvePublicOrigin(request, requestUrl)}${basePath}`;
}

function resolvePublicOrigin(request: Request, requestUrl: URL) {
  const forwardedProto = firstForwardedValue(request.headers.get("x-forwarded-proto"));
  const forwardedHost = firstForwardedValue(request.headers.get("x-forwarded-host"));
  const host = forwardedHost || request.headers.get("host") || requestUrl.host;
  const protocol = resolvePublicProtocol(forwardedProto, requestUrl, host);

  return `${protocol}://${stripDefaultPort(host, protocol)}`;
}

function resolvePublicProtocol(forwardedProto: string | null, requestUrl: URL, host: string) {
  if (forwardedProto === "https" || forwardedProto === "http") {
    return forwardedProto;
  }
  if (requestUrl.protocol === "https:") {
    return "https";
  }
  return isLocalHost(host) ? "http" : "https";
}

function stripDefaultPort(host: string, protocol: "http" | "https") {
  if (protocol === "https" && (host.endsWith(":443") || host.endsWith(":80"))) {
    return host.replace(/:(443|80)$/, "");
  }
  if (protocol === "http" && host.endsWith(":80")) {
    return host.replace(/:80$/, "");
  }
  return host;
}

function firstForwardedValue(value: string | null) {
  return value?.split(",")[0]?.trim().toLowerCase() || null;
}

function isLocalHost(host: string) {
  const hostname = host.replace(/:\d+$/, "").toLowerCase();
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
