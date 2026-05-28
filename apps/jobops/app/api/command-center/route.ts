import { NextResponse } from "next/server";
import { validateCommandCenterApiRequest } from "../../../lib/command-center-contract";
import { getJobOpsApiServerConfig } from "../../../lib/server-env";

export const runtime = "nodejs";

const NON_JSON_BODY_PREVIEW_CHARS = 200;

export async function POST(request: Request) {
  const requestId = crypto.randomUUID();
  let body: unknown;

  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      {
        ok: false,
        error: "Request body must be valid JSON."
      },
      { status: 400 }
    );
  }

  const validation = validateCommandCenterApiRequest(body);
  if (!validation.ok) {
    return NextResponse.json(
      {
        ok: false,
        error: "Command-center request is invalid.",
        issues: validation.issues
      },
      { status: 400 }
    );
  }

  let config: Awaited<ReturnType<typeof getJobOpsApiServerConfig>>;
  try {
    config = await getJobOpsApiServerConfig();
  } catch (error) {
    return serverConfigErrorResponse(error);
  }

  try {
    const apiUrl = `${config.apiBaseUrl.replace(/\/$/, "")}/v1/command-center/commands`;
    console.info("Command-center proxy request.", {
      activeWorkspace: validation.value.activeWorkspace ?? null,
      commandLength: validation.value.command.length,
      requestId,
      requestPath: new URL(request.url).pathname,
      upstreamPath: "/v1/command-center/commands"
    });
    const apiResponse = await fetch(apiUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-JobOps-Internal-Key": config.internalApiKey,
        ...forwardCookieHeader(request)
      },
      body: JSON.stringify({
        command: validation.value.command,
        active_workspace: validation.value.activeWorkspace,
        client_context: validation.value.clientContext ?? {}
      })
    });
    const payload = await readJsonPayload(apiResponse);
    const responseContentType = apiResponse.headers.get("content-type");
    console.info("Command-center proxy response.", {
      contentType: responseContentType || null,
      ok: apiResponse.ok,
      requestId,
      status: apiResponse.status,
      upstreamPath: "/v1/command-center/commands"
    });
    if (!payload.ok) {
      const diagnostic = diagnoseUnexpectedUpstreamResponse({
        apiUrl,
        bodyPreview: payload.bodyPreview,
        contentType: payload.contentType,
        requestUrl: request.url,
        responseUrl: payload.responseUrl,
        status: apiResponse.status
      });
      console.error("Command-center API returned a non-JSON response.", {
        bodyPreview: payload.bodyPreview,
        contentType: payload.contentType || "unknown",
        diagnosticCode: diagnostic.code,
        likelyCause: diagnostic.likelyCause,
        requestId,
        requestPath: new URL(request.url).pathname,
        requestUrl: apiUrl,
        responseUrl: payload.responseUrl,
        status: apiResponse.status
      });
      return NextResponse.json(
        {
          ok: false,
          error: diagnostic.message,
          diagnostic
        },
        { status: 502 }
      );
    }

    return NextResponse.json(
      {
        ok: apiResponse.ok,
        ...(apiResponse.ok
          ? { result: payload.value }
          : {
              error:
                readErrorMessage(payload.value) ??
                "Command-center API request failed.",
              result: payload.value
            })
      },
      { status: apiResponse.status }
    );
  } catch (error) {
    console.error("Command-center API proxy request failed.", {
      error: error instanceof Error ? error.message : String(error),
      requestId,
      requestPath: new URL(request.url).pathname,
      upstreamPath: "/v1/command-center/commands"
    });
    return NextResponse.json(
      {
        ok: false,
        error: "Command-center API is unavailable. Start the FastAPI service on JOBOPS_API_BASE_URL."
      },
      { status: 503 }
    );
  }
}

function forwardCookieHeader(request: Request): Record<string, string> {
  const cookie = request.headers.get("cookie");
  return cookie ? { Cookie: cookie } : {};
}

async function readJsonPayload(response: Response):
  Promise<
    | {
        ok: true;
        value: Record<string, unknown>;
      }
    | {
        ok: false;
        bodyPreview: string;
        contentType: string | null;
        responseUrl: string | null;
      }
  > {
  const contentType = response.headers.get("content-type");
  const text = await response.text();
  if (!contentType?.toLowerCase().includes("application/json")) {
    return {
      ok: false,
      bodyPreview: previewBody(text),
      contentType,
      responseUrl: response.url || null
    };
  }

  try {
    const value = text ? (JSON.parse(text) as Record<string, unknown>) : {};
    return { ok: true, value };
  } catch {
    return {
      ok: false,
      bodyPreview: previewBody(text),
      contentType,
      responseUrl: response.url || null
    };
  }
}

function previewBody(text: string) {
  return text.replace(/\s+/g, " ").trim().slice(0, NON_JSON_BODY_PREVIEW_CHARS);
}

function readErrorMessage(payload: Record<string, unknown>) {
  return typeof payload.assistant_message === "string"
    ? payload.assistant_message
    : typeof payload.error === "string"
      ? payload.error
      : undefined;
}

function diagnoseUnexpectedUpstreamResponse({
  apiUrl,
  bodyPreview,
  contentType,
  requestUrl,
  responseUrl,
  status
}: {
  apiUrl: string;
  bodyPreview: string;
  contentType: string | null;
  requestUrl: string;
  responseUrl: string | null;
  status: number;
}) {
  const lowerContentType = (contentType ?? "").toLowerCase();
  const lowerPreview = bodyPreview.toLowerCase();
  const apiHost = safeHost(apiUrl);
  const requestHost = safeHost(requestUrl);
  const responseHost = responseUrl ? safeHost(responseUrl) : null;

  let code = "upstream_unexpected_content";
  let likelyCause = "FastAPI returned a response that was not JSON.";
  if (apiHost && requestHost && apiHost === requestHost) {
    code = "jobops_api_base_url_points_to_next";
    likelyCause = "JOBOPS_API_BASE_URL appears to point at the Next.js app instead of the FastAPI backend.";
  } else if (lowerContentType.includes("text/html") && /sign in|login|log in|unauthorized/.test(lowerPreview)) {
    code = "upstream_auth_html";
    likelyCause = "The upstream returned an HTML sign-in or auth page, which usually means an expired session or auth middleware mismatch.";
  } else if (status === 401 || status === 403) {
    code = "upstream_auth_rejected";
    likelyCause = "FastAPI rejected the forwarded session or internal API key.";
  } else if (lowerContentType.includes("text/html")) {
    code = "upstream_html_error";
    likelyCause = "The upstream returned HTML, which can happen when JOBOPS_API_BASE_URL is wrong or a platform error page intercepted the request.";
  }

  return {
    code,
    contentType: contentType || null,
    likelyCause,
    message: `Command-center API returned ${contentTypeDescription(contentType)} instead of JSON. ${likelyCause}`,
    responseHost,
    status
  };
}

function safeHost(url: string) {
  try {
    return new URL(url).host;
  } catch {
    return null;
  }
}

function contentTypeDescription(contentType: string | null) {
  if (!contentType) {
    return "a response with no content type";
  }
  if (contentType.toLowerCase().includes("text/html")) {
    return "HTML";
  }
  return contentType;
}

function serverConfigErrorResponse(error: unknown) {
  return NextResponse.json(
    {
      ok: false,
      error: error instanceof Error ? error.message : "JobOps server configuration is invalid."
    },
    { status: 503 }
  );
}
