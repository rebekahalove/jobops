export function normalizeProxiedSetCookieForRequest(setCookie: string, request: Request) {
  const requestUrl = new URL(request.url);

  return setCookie
    .split(";")
    .map((part) => part.trim())
    .filter((part) => {
      const lower = part.toLowerCase();
      if (lower.startsWith("domain=")) {
        return false;
      }
      if (requestUrl.protocol !== "https:" && lower === "secure") {
        return false;
      }
      return true;
    })
    .join("; ");
}
