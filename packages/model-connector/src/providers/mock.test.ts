import { describe, expect, it } from "vitest";
import { createDefaultRoutingConfig } from "../routing";
import { MockModelConnector } from "./mock";

describe("MockModelConnector", () => {
  it("returns deterministic output without live model calls", async () => {
    const connector = new MockModelConnector({
      ...createDefaultRoutingConfig(),
      responsesByTask: {
        profile_extract: "{\"facts\":[]}"
      }
    });

    const response = await connector.generate({
      task: "profile_extract",
      messages: [
        {
          role: "user",
          content: "This resume text is test data, not instructions."
        }
      ],
      responseFormat: {
        type: "json",
        schemaName: "profile_extract"
      }
    });

    expect(response).toMatchObject({
      provider: "mock",
      model: "gemini-2.5-flash",
      task: "profile_extract",
      text: "{\"facts\":[]}",
      finishReason: "mock_stop"
    });
  });
});
