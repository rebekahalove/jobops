import { describe, expect, it } from "vitest";
import { CHEAP_MODEL, DEFAULT_MODEL, createDefaultRoutingConfig, resolveModelForTask } from "./routing";
import type { ModelTask } from "./types";

describe("model routing", () => {
  it.each([
    ["profile_extract", DEFAULT_MODEL],
    ["intake_followup", DEFAULT_MODEL],
    ["role_fit", DEFAULT_MODEL],
    ["bulk_triage", CHEAP_MODEL],
    ["eval_harness", CHEAP_MODEL],
    ["judge_or_second_pass", DEFAULT_MODEL]
  ] satisfies Array<[ModelTask, string]>)("routes %s to %s", (task, expectedModel) => {
    expect(resolveModelForTask(task, createDefaultRoutingConfig())).toBe(expectedModel);
  });

  it("allows task-specific overrides", () => {
    const model = resolveModelForTask(
      "judge_or_second_pass",
      createDefaultRoutingConfig({
        taskModelOverrides: {
          judge_or_second_pass: "gemini-2.5-pro"
        }
      })
    );

    expect(model).toBe("gemini-2.5-pro");
  });
});
