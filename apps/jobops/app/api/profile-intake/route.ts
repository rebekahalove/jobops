import { NextResponse } from "next/server";
import { validateProfileIntakeApiRequest } from "../../../lib/profile-intake-contract";
import { getJobOpsServerEnv } from "../../../lib/server-env";

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

  const env = await getJobOpsServerEnv(["JOBOPS_API_BASE_URL"]);
  const apiBaseUrl = env.JOBOPS_API_BASE_URL ?? "http://localhost:8000";

  try {
    const apiResponse = await fetch(`${apiBaseUrl.replace(/\/$/, "")}/v1/profile-intake/extract`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        latest_user_message: validation.value.latestUserMessage,
        existing_draft: validation.value.existingDraft ?? null
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
