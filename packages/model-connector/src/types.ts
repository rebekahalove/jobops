export const modelTasks = [
  "profile_extract",
  "intake_followup",
  "role_fit",
  "bulk_triage",
  "eval_harness",
  "judge_or_second_pass"
] as const;

export type ModelTask = (typeof modelTasks)[number];

export type ModelProviderName = "mock" | "gemini";

export type ModelMessageRole = "system" | "user" | "assistant";

export type ModelMessage = {
  role: ModelMessageRole;
  content: string;
};

export type JsonSchema = {
  type: string;
  properties?: Record<string, JsonSchema>;
  items?: JsonSchema;
  required?: string[];
  enum?: string[];
  description?: string;
  additionalProperties?: boolean | JsonSchema;
  maxItems?: number;
  maxLength?: number;
};

export type ModelResponseFormat =
  | {
      type: "text";
    }
  | {
      type: "json";
      schemaName: string;
      schema?: JsonSchema;
    };

export type ModelRequest = {
  task: ModelTask;
  messages: ModelMessage[];
  responseFormat?: ModelResponseFormat;
  temperature?: number;
  maxOutputTokens?: number;
  metadata?: Record<string, string>;
};

export type ModelUsage = {
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
};

export type ModelResponse = {
  provider: ModelProviderName;
  model: string;
  task: ModelTask;
  text: string;
  usage?: ModelUsage;
  finishReason?: string;
};

export type ModelConnector = {
  generate(request: ModelRequest): Promise<ModelResponse>;
};

export type ModelRoutingConfig = {
  defaultModel: string;
  cheapModel: string;
  taskModelOverrides?: Partial<Record<ModelTask, string>>;
};

export type ModelConnectorConfig = ModelRoutingConfig & {
  provider: ModelProviderName;
  geminiApiKey?: string;
};
