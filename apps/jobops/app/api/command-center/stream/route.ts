import { NextResponse } from "next/server";
import { validateCommandCenterApiRequest } from "../../../../lib/command-center-contract";
import { getJobOpsApiServerConfig } from "../../../../lib/server-env";

export const runtime = "nodejs";

export async function POST(request: Request) {
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
    const apiResponse = await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/command-center/commands/stream`, {
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

    if (!apiResponse.body) {
      return NextResponse.json(
        {
          ok: false,
          error: "Command-center stream did not return a response body."
        },
        { status: 502 }
      );
    }

    return new Response(apiResponse.body, {
      headers: {
        "Cache-Control": "no-cache",
        "Content-Type": apiResponse.headers.get("content-type") ?? "application/x-ndjson"
      },
      status: apiResponse.status
    });
  } catch {
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
