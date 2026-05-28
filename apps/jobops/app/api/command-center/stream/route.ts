import { NextResponse } from "next/server";
import { validateCommandCenterApiRequest } from "../../../../lib/command-center-contract";
import { getJobOpsApiServerConfig } from "../../../../lib/server-env";

export const runtime = "nodejs";

const UNEXPECTED_STREAM_BODY_PREVIEW_CHARS = 200;

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
    return NextResponse.json(
      {
        ok: false,
        error: error instanceof Error ? error.message : "JobOps server configuration is invalid."
      },
      { status: 503 }
    );
  }

  try {
    const apiUrl = `${config.apiBaseUrl.replace(/\/$/, "")}/v1/command-center/commands/stream`;
    console.info("Command-center stream proxy request.", {
      activeWorkspace: validation.value.activeWorkspace ?? null,
      commandLength: validation.value.command.length,
      requestId,
      requestPath: new URL(request.url).pathname,
      upstreamPath: "/v1/command-center/commands/stream"
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
    console.info("Command-center stream proxy response.", {
      contentType: apiResponse.headers.get("content-type") || null,
      ok: apiResponse.ok,
      requestId,
      status: apiResponse.status,
      upstreamPath: "/v1/command-center/commands/stream"
    });

    if (!apiResponse.body) {
      console.error("Command-center stream API returned no response body.", {
        contentType: apiResponse.headers.get("content-type") || null,
        requestId,
        requestPath: new URL(request.url).pathname,
        requestUrl: apiUrl,
        responseUrl: apiResponse.url || null,
        status: apiResponse.status
      });
      return NextResponse.json(
        {
          ok: false,
          error: "Command-center stream did not return a response body."
        },
        { status: 502 }
      );
    }

    const responseContentType = apiResponse.headers.get("content-type") ?? "";
    if (!responseContentType.toLowerCase().includes("application/x-ndjson")) {
      const body = await apiResponse.text();
      const diagnostic = diagnoseUnexpectedUpstreamResponse({
        apiUrl,
        bodyPreview: previewBody(body),
        contentType: responseContentType || null,
        requestUrl: request.url,
        responseUrl: apiResponse.url || null,
        status: apiResponse.status
      });
      console.error("Command-center stream API returned an unexpected response.", {
        bodyPreview: diagnostic.bodyPreview,
        contentType: responseContentType || null,
        diagnosticCode: diagnostic.code,
        likelyCause: diagnostic.likelyCause,
        requestId,
        requestPath: new URL(request.url).pathname,
        requestUrl: apiUrl,
        responseUrl: apiResponse.url || null,
        status: apiResponse.status,
        upstreamPath: "/v1/command-center/commands/stream"
      });
      return NextResponse.json(
        {
          ok: false,
          error: diagnostic.message,
          diagnostic: omitBodyPreview(diagnostic)
        },
        { status: 502 }
      );
    }

    return new Response(apiResponse.body, {
      headers: {
        "Cache-Control": "no-cache",
        "Content-Type": responseContentType
      },
      status: apiResponse.status
    });
  } catch (error) {
    console.error("Command-center stream API proxy request failed.", {
      error: error instanceof Error ? error.message : String(error),
      requestId,
      requestPath: new URL(request.url).pathname,
      upstreamPath: "/v1/command-center/commands/stream"
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

function previewBody(text: string) {
  return text.replace(/\s+/g, " ").trim().slice(0, UNEXPECTED_STREAM_BODY_PREVIEW_CHARS);
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
  let likelyCause = "FastAPI returned a response that was not NDJSON.";
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
    bodyPreview,
    code,
    contentType: contentType || null,
    likelyCause,
    message: `Command-center stream expected NDJSON but upstream returned ${contentTypeDescription(contentType)}. ${likelyCause}`,
    responseHost,
    status
  };
}

function omitBodyPreview<T extends { bodyPreview: string }>(diagnostic: T) {
  const { bodyPreview: _bodyPreview, ...safeDiagnostic } = diagnostic;
  return safeDiagnostic;
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
