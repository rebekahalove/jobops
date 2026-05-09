import { StructuredOutputValidationError } from "./errors";
import type { ModelConnector, ModelRequest, ModelResponse } from "./types";

export type StructuredValidationResult<T> =
  | {
      ok: true;
      value: T;
    }
  | {
      ok: false;
      issues: string[];
    };

export type StructuredOutputValidator<T> = (value: unknown) => StructuredValidationResult<T>;

export type StructuredModelResponse<T> = ModelResponse & {
  value: T;
};

export async function generateStructuredOutput<T>(
  connector: ModelConnector,
  request: ModelRequest,
  validator: StructuredOutputValidator<T>
): Promise<StructuredModelResponse<T>> {
  const response = await connector.generate({
    ...request,
    responseFormat: request.responseFormat ?? {
      type: "json",
      schemaName: "structured_output"
    }
  });

  return {
    ...response,
    value: validateStructuredText(response.text, validator)
  };
}

export function validateStructuredText<T>(
  text: string,
  validator: StructuredOutputValidator<T>
): T {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new StructuredOutputValidationError(["Output is not valid JSON."]);
  }

  const result = validator(parsed);
  if (!result.ok) {
    throw new StructuredOutputValidationError(result.issues);
  }

  return result.value;
}

export function requireObject(value: unknown): StructuredValidationResult<Record<string, unknown>> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return {
      ok: false,
      issues: ["Output must be a JSON object."]
    };
  }

  return {
    ok: true,
    value: value as Record<string, unknown>
  };
}
