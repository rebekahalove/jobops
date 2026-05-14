import { NextResponse } from "next/server";
import { getJobOpsServerEnv } from "../../../lib/server-env";

export const runtime = "nodejs";

export async function GET() {
  const env = await getJobOpsServerEnv(["JOBOPS_API_BASE_URL", "JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG"]);
  const apiBaseUrl = env.JOBOPS_API_BASE_URL ?? "http://localhost:8000";
  const slug = env.JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG ?? "rebekah-love";
  const url = new URL(`${apiBaseUrl.replace(/\/$/, "")}/v1/applications`);
  url.searchParams.set("candidate_profile_slug", slug);

  try {
    const apiResponse = await fetch(url, { cache: "no-store" });
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

  const env = await getJobOpsServerEnv(["JOBOPS_API_BASE_URL", "JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG"]);
  const apiBaseUrl = env.JOBOPS_API_BASE_URL ?? "http://localhost:8000";
  const payload = {
    candidate_profile_slug: env.JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG ?? "rebekah-love",
    ...body
  };

  try {
    const apiResponse = await fetch(`${apiBaseUrl.replace(/\/$/, "")}/v1/applications`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
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
