import { NextResponse } from "next/server";
import { getJobOpsApiServerConfig } from "../../../../../lib/server-env";

export const runtime = "nodejs";

export async function POST(request: Request) {
  let config: Awaited<ReturnType<typeof getJobOpsApiServerConfig>>;
  try {
    config = await getJobOpsApiServerConfig();
  } catch (error) {
    return serverConfigErrorResponse(error);
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ ok: false, error: "Request body must be valid JSON." }, { status: 400 });
  }

  try {
    const apiResponse = await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/public/jobops/access-requests`, {
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
        error: "JobOps alpha access requests are unavailable. Start the FastAPI service on JOBOPS_API_BASE_URL."
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
