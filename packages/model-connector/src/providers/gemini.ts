import { GoogleGenAI } from "@google/genai";
import { ModelConfigurationError } from "../errors";
import { resolveModelForTask } from "../routing";
import type { ModelConnector, ModelConnectorConfig, ModelMessage, ModelRequest, ModelResponse } from "../types";

type GeminiContent = {
  role: "user" | "model";
  parts: Array<{ text: string }>;
};

export class GeminiModelConnector implements ModelConnector {
  private readonly config: ModelConnectorConfig;
  private client?: GoogleGenAI;

  constructor(config: ModelConnectorConfig) {
    this.config = config;
  }

  async generate(request: ModelRequest): Promise<ModelResponse> {
    const model = resolveModelForTask(request.task, this.config);
    const client = this.getClient();
    const { contents, systemInstruction } = toGeminiMessages(request.messages);

    const response = await client.models.generateContent({
      model,
      contents,
      config: {
        ...(systemInstruction ? { systemInstruction } : {}),
        ...(request.temperature === undefined ? {} : { temperature: request.temperature }),
        ...(request.maxOutputTokens === undefined ? {} : { maxOutputTokens: request.maxOutputTokens }),
        ...(request.responseFormat?.type === "json" ? { responseMimeType: "application/json" } : {}),
        ...(request.responseFormat?.type === "json" && request.responseFormat.schema
          ? { responseSchema: request.responseFormat.schema }
          : {})
      }
    });

    return {
      provider: "gemini",
      model,
      task: request.task,
      text: response.text ?? "",
      finishReason: response.candidates?.[0]?.finishReason,
      usage: {
        inputTokens: response.usageMetadata?.promptTokenCount,
        outputTokens: response.usageMetadata?.candidatesTokenCount,
        totalTokens: response.usageMetadata?.totalTokenCount
      }
    };
  }

  private getClient(): GoogleGenAI {
    if (!this.config.geminiApiKey) {
      throw new ModelConfigurationError(
        "GEMINI_API_KEY is required for live Gemini model calls. Set it in a server-side environment file or use JOBOPS_LLM_PROVIDER=mock for deterministic tests.",
        "MODEL_CONFIG_MISSING_GEMINI_API_KEY"
      );
    }

    this.client ??= new GoogleGenAI({ apiKey: this.config.geminiApiKey });
    return this.client;
  }
}

function toGeminiMessages(messages: ModelMessage[]): {
  contents: GeminiContent[];
  systemInstruction?: string;
} {
  const systemInstruction = messages
    .filter((message) => message.role === "system")
    .map((message) => message.content)
    .join("\n\n");

  const contents = messages
    .filter((message) => message.role !== "system")
    .map((message) => ({
      role: message.role === "assistant" ? ("model" as const) : ("user" as const),
      parts: [{ text: message.content }]
    }));

  return {
    contents: contents.length > 0 ? contents : [{ role: "user", parts: [{ text: "" }] }],
    ...(systemInstruction ? { systemInstruction } : {})
  };
}
