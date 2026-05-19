import { NextResponse } from "next/server";
import { validateProfileIntakeApiRequest } from "../../../lib/profile-intake-contract";
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

  const validation = validateProfileIntakeApiRequest(body);
  if (!validation.ok) {
    return NextResponse.json(
      {
        ok: false,
        error: "Profile intake request is invalid.",
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
      validation.value.candidateProfileSlug ??
      requireJobOpsServerEnvValue(config, "JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG");
  } catch (error) {
    return serverConfigErrorResponse(error);
  }

  try {
    const apiResponse = await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/profile-intake/extract`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-JobOps-Internal-Key": config.internalApiKey
      },
      body: JSON.stringify({
        latest_user_message: validation.value.latestUserMessage,
        existing_draft: validation.value.existingDraft ?? null,
        candidate_profile_slug: candidateProfileSlug
      })
    });
    const payload = await apiResponse.json();

    return NextResponse.json(payload, { status: apiResponse.status });
  } catch {
    return NextResponse.json(
      {
        ok: false,
        error:
          "Profile intake API is unavailable. Start the FastAPI service on JOBOPS_API_BASE_URL or switch to mock mode there."
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
