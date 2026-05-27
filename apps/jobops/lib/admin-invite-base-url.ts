import { getDashboardBasePathFromRequestPath } from "./dashboard-auth";

export function withInviteBaseUrl(request: Request, body: unknown) {
  const requestUrl = new URL(request.url);
  const basePath = getDashboardBasePathFromRequestPath(requestUrl.pathname);
  const payload = isRecord(body) ? { ...body } : {};

  if (!payload.invite_base_url) {
    payload.invite_base_url = `${requestUrl.origin}${basePath}`;
  }

  return payload;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
