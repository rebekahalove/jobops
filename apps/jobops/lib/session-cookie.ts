export function normalizeProxiedSetCookieForRequest(setCookie: string, request: Request) {
  const requestUrl = new URL(request.url);
  if (requestUrl.protocol === "https:") {
    return setCookie;
  }

  return setCookie
    .split(";")
    .map((part) => part.trim())
    .filter((part) => part.toLowerCase() !== "secure")
    .join("; ");
}
