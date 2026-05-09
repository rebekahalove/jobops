import { ModelConfigurationError } from "./errors";
import { GeminiModelConnector } from "./providers/gemini";
import { MockModelConnector } from "./providers/mock";
import type { ModelConnector, ModelConnectorConfig } from "./types";

export function createModelConnector(config: ModelConnectorConfig): ModelConnector {
  if (config.provider === "mock") {
    return new MockModelConnector({
      defaultModel: config.defaultModel,
      cheapModel: config.cheapModel,
      taskModelOverrides: config.taskModelOverrides
    });
  }

  if (config.provider === "gemini") {
    return new GeminiModelConnector(config);
  }

  throw new ModelConfigurationError(
    `Unsupported model provider "${config.provider}".`,
    "MODEL_CONFIG_UNSUPPORTED_PROVIDER"
  );
}
