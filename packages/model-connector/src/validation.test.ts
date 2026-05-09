import { describe, expect, it } from "vitest";
import { createDefaultRoutingConfig } from "./routing";
import { MockModelConnector } from "./providers/mock";
import { generateStructuredOutput, requireObject } from "./validation";

describe("structured output validation", () => {
  it("parses and validates model output before use", async () => {
    const connector = new MockModelConnector({
      ...createDefaultRoutingConfig(),
      defaultResponse: "{\"answer\":\"verified-only\"}"
    });

    const response = await generateStructuredOutput(
      connector,
      {
        task: "intake_followup",
        messages: [
          {
            role: "user",
            content: "Candidate-provided text is untrusted input."
          }
        ]
      },
      requireObject
    );

    expect(response.value).toEqual({ answer: "verified-only" });
  });

  it("rejects malformed structured output", async () => {
    const connector = new MockModelConnector({
      ...createDefaultRoutingConfig(),
      defaultResponse: "not json"
    });

    await expect(
      generateStructuredOutput(
        connector,
        {
          task: "profile_extract",
          messages: [{ role: "user", content: "resume text" }]
        },
        requireObject
      )
    ).rejects.toMatchObject({
      name: "StructuredOutputValidationError"
    });
  });
});
