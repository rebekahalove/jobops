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

  const url = new URL(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/companies`);
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
        error: "Company watchlist API is unavailable. Start the FastAPI service on JOBOPS_API_BASE_URL."
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
