import type { ModelRoutingConfig, ModelTask } from "./types";

export const DEFAULT_MODEL = "gemini-2.5-flash";
export const CHEAP_MODEL = "gemini-2.5-flash-lite";

const cheapModelTasks = new Set<ModelTask>(["bulk_triage", "eval_harness"]);

export function resolveModelForTask(task: ModelTask, config: ModelRoutingConfig): string {
  const override = config.taskModelOverrides?.[task];
  if (override) {
    return override;
  }

  return cheapModelTasks.has(task) ? config.cheapModel : config.defaultModel;
}

export function createDefaultRoutingConfig(
  overrides: Partial<ModelRoutingConfig> = {}
): ModelRoutingConfig {
  return {
    defaultModel: overrides.defaultModel ?? DEFAULT_MODEL,
    cheapModel: overrides.cheapModel ?? CHEAP_MODEL,
    taskModelOverrides: overrides.taskModelOverrides
  };
}
