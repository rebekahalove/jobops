import { NextResponse } from "next/server";
import { validateCommandCenterApiRequest } from "../../../lib/command-center-contract";
import { getJobOpsApiServerConfig, requireJobOpsServerEnvValue } from "../../../lib/server-env";

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
    config = await getJobOpsApiServerConfig(["JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG"]);
  } catch (error) {
    return serverConfigErrorResponse(error);
  }

  let candidateProfileSlug: string;
  try {
    candidateProfileSlug =
      validation.value.candidateProfileSlug?.trim() ||
      requireJobOpsServerEnvValue(config, "JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG");
  } catch (error) {
    return serverConfigErrorResponse(error);
  }

  try {
    const apiResponse = await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/command-center/commands`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-JobOps-Internal-Key": config.internalApiKey
      },
      body: JSON.stringify({
        command: validation.value.command,
        candidate_profile_slug: candidateProfileSlug,
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

function serverConfigErrorResponse(error: unknown) {
  return NextResponse.json(
    {
      ok: false,
      error: error instanceof Error ? error.message : "JobOps server configuration is invalid."
    },
    { status: 503 }
  );
}
