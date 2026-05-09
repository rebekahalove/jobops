import { ModelConfigurationError } from "./errors";
import { CHEAP_MODEL, DEFAULT_MODEL } from "./routing";
import type { ModelConnectorConfig, ModelProviderName } from "./types";

type EnvLike = Partial<Record<string, string | undefined>>;

export function readModelConnectorConfigFromEnv(
  env: EnvLike = process.env
): ModelConnectorConfig {
  assertServerRuntime();

  return {
    provider: normalizeProvider(env.JOBOPS_LLM_PROVIDER ?? "gemini"),
    defaultModel: env.JOBOPS_DEFAULT_MODEL ?? DEFAULT_MODEL,
    cheapModel: env.JOBOPS_CHEAP_MODEL ?? CHEAP_MODEL,
    geminiApiKey: env.GEMINI_API_KEY
  };
}

export function assertServerRuntime(): void {
  if (typeof window !== "undefined") {
    throw new ModelConfigurationError(
      "Model connector environment configuration must only be read in a server runtime.",
      "MODEL_CONFIG_BROWSER_RUNTIME"
    );
  }
}

function normalizeProvider(provider: string): ModelProviderName {
  if (provider === "mock" || provider === "gemini") {
    return provider;
  }

  throw new ModelConfigurationError(
    `Unsupported JOBOPS_LLM_PROVIDER "${provider}". Expected "mock" or "gemini".`,
    "MODEL_CONFIG_UNSUPPORTED_PROVIDER"
  );
}
