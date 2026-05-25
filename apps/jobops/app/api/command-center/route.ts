import { NextResponse } from "next/server";
import { validateCommandCenterApiRequest } from "../../../lib/command-center-contract";
import { getJobOpsApiServerConfig } from "../../../lib/server-env";

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
    return serverConfigErrorResponse(error);
  }

  try {
    const apiResponse = await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/command-center/commands`, {
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
    if (!payload.ok) {
      console.error("Command-center API returned a non-JSON response.", {
        contentType: payload.contentType || "unknown",
        status: apiResponse.status
      });
      return NextResponse.json(
        {
          ok: false,
          error: "Command-center API returned an unexpected response. Please try again."
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

async function readJsonPayload(response: Response):
  Promise<
    | {
        ok: true;
        value: Record<string, unknown>;
      }
    | {
        ok: false;
        contentType: string | null;
      }
  > {
  const contentType = response.headers.get("content-type");
  const text = await response.text();
  if (!contentType?.toLowerCase().includes("application/json")) {
    return { ok: false, contentType };
  }

  try {
    const value = text ? (JSON.parse(text) as Record<string, unknown>) : {};
    return { ok: true, value };
  } catch {
    return { ok: false, contentType };
  }
}

function readErrorMessage(payload: Record<string, unknown>) {
  return typeof payload.assistant_message === "string"
    ? payload.assistant_message
    : typeof payload.error === "string"
      ? payload.error
      : undefined;
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
