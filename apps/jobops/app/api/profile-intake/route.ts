import { ModelConfigurationError, StructuredOutputValidationError } from "@jobops/model-connector/server";
import { NextResponse } from "next/server";
import { runProfileIntakeExtraction } from "../../../lib/profile-intake-model";
import { validateProfileIntakeApiRequest } from "../../../lib/profile-intake-contract";
import { buildProfileIntakeValidationErrorBody } from "../../../lib/profile-intake-api-errors";

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

  try {
    return NextResponse.json({
      ok: true,
      result: await runProfileIntakeExtraction(validation.value)
    });
  } catch (error) {
    if (error instanceof ModelConfigurationError) {
      return NextResponse.json(
        {
          ok: false,
          error:
            "Profile intake model is not configured. Set JOBOPS_LLM_PROVIDER=mock for deterministic local mode, or configure JOBOPS_LLM_PROVIDER=gemini with server-side GEMINI_API_KEY.",
          code: error.code
        },
        { status: 503 }
      );
    }

    if (isStructuredOutputValidationError(error)) {
      return NextResponse.json(
        buildProfileIntakeValidationErrorBody(error),
        { status: 502 }
      );
    }

    return NextResponse.json(
      {
        ok: false,
        error: "Profile intake failed. No draft data was applied."
      },
      { status: 500 }
    );
  }
}

function isStructuredOutputValidationError(error: unknown): error is StructuredOutputValidationError {
  return (
    error instanceof StructuredOutputValidationError ||
    (typeof error === "object" &&
      error !== null &&
      "issues" in error &&
      Array.isArray((error as { issues?: unknown }).issues))
  );
}
