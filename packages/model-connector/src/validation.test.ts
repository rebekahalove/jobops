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

  it("normalizes fenced JSON before validation", async () => {
    const connector = new MockModelConnector({
      ...createDefaultRoutingConfig(),
      defaultResponse: "```json\n{\"answer\":\"fenced\"}\n```"
    });

    const response = await generateStructuredOutput(
      connector,
      {
        task: "profile_extract",
        messages: [{ role: "user", content: "resume text" }]
      },
      requireObject
    );

    expect(response.value).toEqual({ answer: "fenced" });
  });

  it("normalizes a single JSON object surrounded by prose before validation", async () => {
    const connector = new MockModelConnector({
      ...createDefaultRoutingConfig(),
      defaultResponse: "Here is the JSON:\n{\"answer\":\"wrapped\"}\nDone."
    });

    const response = await generateStructuredOutput(
      connector,
      {
        task: "profile_extract",
        messages: [{ role: "user", content: "resume text" }]
      },
      requireObject
    );

    expect(response.value).toEqual({ answer: "wrapped" });
  });

  it("adds a truncation issue when the provider reports a token limit finish", async () => {
    const connector = new MockModelConnector({
      ...createDefaultRoutingConfig(),
      defaultResponse: "{\"answer\":\"unfinished\""
    });
    const originalGenerate = connector.generate.bind(connector);
    connector.generate = async (request) => ({
      ...(await originalGenerate(request)),
      finishReason: "MAX_TOKENS"
    });

    await expect(
      generateStructuredOutput(
        connector,
        {
          task: "profile_extract",
          messages: [{ role: "user", content: "long resume text" }]
        },
        requireObject
      )
    ).rejects.toMatchObject({
      issues: expect.arrayContaining(["Model response appears to have been truncated before valid JSON completed."])
    });
  });
});
