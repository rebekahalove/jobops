import { NextResponse } from "next/server";
import { getJobOpsServerEnv } from "../../../lib/server-env";

export const runtime = "nodejs";

export async function GET(request: Request) {
  const env = await getJobOpsServerEnv(["JOBOPS_API_BASE_URL", "JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG"]);
  const apiBaseUrl = env.JOBOPS_API_BASE_URL ?? "http://localhost:8000";
  const requestUrl = new URL(request.url);
  const slug = requestUrl.searchParams.get("candidateProfileSlug") ?? env.JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG ?? "rebekah-love";

  try {
    const apiResponse = await fetch(`${apiBaseUrl.replace(/\/$/, "")}/v1/command-center/profile-draft/${slug}`);
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
