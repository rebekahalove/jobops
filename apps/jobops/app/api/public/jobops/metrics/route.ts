import { NextResponse } from "next/server";
import { getJobOpsApiServerConfig } from "../../../../../lib/server-env";

export const runtime = "nodejs";

export async function GET() {
  let config: Awaited<ReturnType<typeof getJobOpsApiServerConfig>>;
  try {
    config = await getJobOpsApiServerConfig();
  } catch (error) {
    return serverConfigErrorResponse(error);
  }

  try {
    const apiResponse = await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/public/jobops/metrics`, {
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
        error: "JobOps public metrics are unavailable. Start the FastAPI service on JOBOPS_API_BASE_URL."
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
