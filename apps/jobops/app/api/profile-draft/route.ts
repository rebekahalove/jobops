import { NextResponse } from "next/server";
import { getJobOpsApiServerConfig, requireJobOpsServerEnvValue } from "../../../lib/server-env";

export const runtime = "nodejs";

export async function GET(request: Request) {
  let config: Awaited<ReturnType<typeof getJobOpsApiServerConfig>>;
  try {
    config = await getJobOpsApiServerConfig(["JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG"]);
  } catch (error) {
    return serverConfigErrorResponse(error);
  }

  const requestUrl = new URL(request.url);
  const requestSlug = requestUrl.searchParams.get("candidateProfileSlug")?.trim();
  let slug: string;
  try {
    slug = requestSlug || requireJobOpsServerEnvValue(config, "JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG");
  } catch (error) {
    return serverConfigErrorResponse(error);
  }

  try {
    const apiResponse = await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/command-center/profile-draft/${slug}`, {
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
        error: "Profile draft API is unavailable. Start the FastAPI service on JOBOPS_API_BASE_URL."
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
