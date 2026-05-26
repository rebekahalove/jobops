import { getDashboardBasePathFromRequestPath, redirectResponse } from "../../../../lib/dashboard-auth";
import { getJobOpsApiServerConfig } from "../../../../lib/server-env";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const requestUrl = new URL(request.url);
  const basePath = getDashboardBasePathFromRequestPath(requestUrl.pathname);
  const formData = await request.formData();
  const identifier = textValue(formData.get("identifier"));

  if (identifier) {
    try {
      const config = await getJobOpsApiServerConfig();
      await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/auth/password/reset/request`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-JobOps-Internal-Key": config.internalApiKey
        },
        body: JSON.stringify({
          identifier,
          reset_base_url: `${requestUrl.origin}${basePath}`
        })
      });
    } catch {
    }
  }

  return redirectResponse(`${basePath}/forgot-password?sent=1`, 303);
}

function textValue(value: FormDataEntryValue | null) {
  return typeof value === "string" ? value.trim() : "";
}
