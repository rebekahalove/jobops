import { StructuredOutputValidationError } from "@jobops/model-connector";
import { describe, expect, it } from "vitest";
import { buildProfileIntakeValidationErrorBody } from "./profile-intake-api-errors";
import { ProfileIntakeValidationError } from "./profile-intake-errors";

describe("profile intake API errors", () => {
  it("returns a safe validation error without debugRunId by default", () => {
    const body = buildProfileIntakeValidationErrorBody(new StructuredOutputValidationError(["Output is not valid JSON."]));

    expect(body).toEqual({
      ok: false,
      error: "The model returned malformed profile intake data. No draft data was applied.",
      issues: ["Output is not valid JSON."]
    });
  });

  it("returns debugRunId only when the validation error carries one", () => {
    const body = buildProfileIntakeValidationErrorBody(
      new ProfileIntakeValidationError(["Output is not valid JSON."], { debugRunId: "run-123" })
    );

    expect(body).toMatchObject({
      debugRunId: "run-123",
      error: "The model returned malformed profile intake data. No draft data was applied."
    });
    expect(JSON.stringify(body)).not.toContain("raw-response");
  });
});
