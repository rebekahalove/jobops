import type { StructuredOutputValidationError } from "@jobops/model-connector";
import { getProfileIntakeDebugRunId } from "./profile-intake-errors";

export function buildProfileIntakeValidationErrorBody(error: StructuredOutputValidationError) {
  const debugRunId = getProfileIntakeDebugRunId(error);

  return {
    ok: false as const,
    error: "The model returned malformed profile intake data. No draft data was applied.",
    issues: error.issues,
    ...(debugRunId ? { debugRunId } : {})
  };
}
