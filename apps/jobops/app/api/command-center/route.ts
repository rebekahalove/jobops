import { NextResponse } from "next/server";
import { validateCommandCenterApiRequest } from "../../../lib/command-center-contract";
import { getJobOpsServerEnv } from "../../../lib/server-env";

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

  const env = await getJobOpsServerEnv(["JOBOPS_API_BASE_URL", "JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG"]);
  const apiBaseUrl = env.JOBOPS_API_BASE_URL ?? "http://localhost:8000";

  try {
    const apiResponse = await fetch(`${apiBaseUrl.replace(/\/$/, "")}/v1/command-center/commands`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        command: validation.value.command,
        candidate_profile_slug:
          validation.value.candidateProfileSlug ?? env.JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG ?? "rebekah-love",
        active_workspace: validation.value.activeWorkspace,
        client_context: validation.value.clientContext ?? {}
      })
    });
    const payload = await apiResponse.json();

    return NextResponse.json(
      {
        ok: apiResponse.ok,
        ...(apiResponse.ok
          ? { result: payload }
          : { error: payload?.assistant_message ?? payload?.error ?? "Command-center API request failed.", result: payload })
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
