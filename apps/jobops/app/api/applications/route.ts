import { NextResponse } from "next/server";
import { getJobOpsApiServerConfig, requireJobOpsServerEnvValue } from "../../../lib/server-env";

export const runtime = "nodejs";

export async function GET() {
  let config: Awaited<ReturnType<typeof getJobOpsApiServerConfig>>;
  try {
    config = await getJobOpsApiServerConfig(["JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG"]);
  } catch (error) {
    return serverConfigErrorResponse(error);
  }

  let slug: string;
  try {
    slug = requireJobOpsServerEnvValue(config, "JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG");
  } catch (error) {
    return serverConfigErrorResponse(error);
  }

  const url = new URL(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/applications`);
  url.searchParams.set("candidate_profile_slug", slug);

  try {
    const apiResponse = await fetch(url, {
      cache: "no-store",
      headers: {
        "X-JobOps-Internal-Key": config.internalApiKey
      }
    });
    const payload = await apiResponse.json();
    return NextResponse.json(payload, { status: apiResponse.status });
  } catch {
    return NextResponse.json(
      {
        ok: false,
        error: "Application tracker API is unavailable. Start the FastAPI service on JOBOPS_API_BASE_URL."
      },
      { status: 503 }
    );
  }
}

export async function POST(request: Request) {
  let body: Record<string, unknown>;

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

  let config: Awaited<ReturnType<typeof getJobOpsApiServerConfig>>;
  try {
    config = await getJobOpsApiServerConfig(["JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG"]);
  } catch (error) {
    return serverConfigErrorResponse(error);
  }

  let candidateProfileSlug: string | undefined;
  try {
    candidateProfileSlug =
      typeof body.candidate_profile_slug === "string" && body.candidate_profile_slug.trim().length > 0
        ? body.candidate_profile_slug
        : typeof body.candidateProfileSlug === "string" && body.candidateProfileSlug.trim().length > 0
          ? body.candidateProfileSlug
          : requireJobOpsServerEnvValue(config, "JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG");
  } catch (error) {
    return serverConfigErrorResponse(error);
  }

  const payload = {
    ...body,
    candidate_profile_slug: candidateProfileSlug
  };

  try {
    const apiResponse = await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/applications`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-JobOps-Internal-Key": config.internalApiKey
      },
      body: JSON.stringify(payload)
    });
    const responsePayload = await apiResponse.json();
    return NextResponse.json(responsePayload, { status: apiResponse.status });
  } catch {
    return NextResponse.json(
      {
        ok: false,
        error: "Application tracker API is unavailable. Start the FastAPI service on JOBOPS_API_BASE_URL."
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
