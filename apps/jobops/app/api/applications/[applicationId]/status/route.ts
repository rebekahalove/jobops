import { NextResponse } from "next/server";
import { getJobOpsServerEnv } from "../../../../../lib/server-env";

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ applicationId: string }>;
};

export async function PATCH(request: Request, context: RouteContext) {
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

  const { applicationId } = await context.params;
  const env = await getJobOpsServerEnv(["JOBOPS_API_BASE_URL"]);
  const apiBaseUrl = env.JOBOPS_API_BASE_URL ?? "http://localhost:8000";

  try {
    const apiResponse = await fetch(`${apiBaseUrl.replace(/\/$/, "")}/v1/applications/${applicationId}/status`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(body)
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
