import { resolveModelForTask } from "../routing";
import type {
  ModelConnector,
  ModelRequest,
  ModelResponse,
  ModelRoutingConfig,
  ModelTask
} from "../types";

type MockResponseResolver = string | ((request: ModelRequest) => string);

export type MockModelConnectorOptions = ModelRoutingConfig & {
  defaultResponse?: MockResponseResolver;
  responsesByTask?: Partial<Record<ModelTask, MockResponseResolver>>;
};

export class MockModelConnector implements ModelConnector {
  private readonly options: MockModelConnectorOptions;

  constructor(options: MockModelConnectorOptions) {
    this.options = options;
  }

  async generate(request: ModelRequest): Promise<ModelResponse> {
    const resolver =
      this.options.responsesByTask?.[request.task] ??
      this.options.defaultResponse ??
      "Mock model response.";

    const text = typeof resolver === "function" ? resolver(request) : resolver;

    return {
      provider: "mock",
      model: resolveModelForTask(request.task, this.options),
      task: request.task,
      text,
      finishReason: "mock_stop"
    };
  }
}
