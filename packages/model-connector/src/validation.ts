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

  try {
    return {
      ...response,
      value: validateStructuredText(response.text, validator)
    };
  } catch (error) {
    if (error instanceof StructuredOutputValidationError && looksTruncated(response.finishReason)) {
      throw new StructuredOutputValidationError([
        ...error.issues,
        "Model response appears to have been truncated before valid JSON completed."
      ]);
    }

    throw error;
  }
}

export function validateStructuredText<T>(
  text: string,
  validator: StructuredOutputValidator<T>
): T {
  const parsed = parseStructuredJson(text);

  const result = validator(parsed);
  if (!result.ok) {
    throw new StructuredOutputValidationError(result.issues);
  }

  return result.value;
}

function parseStructuredJson(text: string): unknown {
  const trimmed = text.trim().replace(/^\uFEFF/, "");

  for (const candidate of jsonParseCandidates(trimmed)) {
    try {
      return JSON.parse(candidate);
    } catch {
      // Keep trying narrower candidates before reporting a malformed model response.
    }
  }

  throw new StructuredOutputValidationError(["Output is not valid JSON."]);
}

function looksTruncated(finishReason: string | undefined): boolean {
  return typeof finishReason === "string" && /max|length|token/i.test(finishReason);
}

function jsonParseCandidates(text: string): string[] {
  const candidates = [text];
  const fenced = text.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);

  if (fenced?.[1]) {
    candidates.push(fenced[1].trim());
  }

  const jsonObject = extractBalancedJson(text, "{", "}");
  if (jsonObject) {
    candidates.push(jsonObject);
  }

  const jsonArray = extractBalancedJson(text, "[", "]");
  if (jsonArray) {
    candidates.push(jsonArray);
  }

  return Array.from(new Set(candidates));
}

function extractBalancedJson(text: string, openToken: "{" | "[", closeToken: "}" | "]"): string | undefined {
  const start = text.indexOf(openToken);
  if (start === -1) {
    return undefined;
  }

  let depth = 0;
  let inString = false;
  let escaped = false;

  for (let index = start; index < text.length; index += 1) {
    const char = text[index];

    if (escaped) {
      escaped = false;
      continue;
    }

    if (char === "\\") {
      escaped = inString;
      continue;
    }

    if (char === "\"") {
      inString = !inString;
      continue;
    }

    if (inString) {
      continue;
    }

    if (char === openToken) {
      depth += 1;
    } else if (char === closeToken) {
      depth -= 1;

      if (depth === 0) {
        return text.slice(start, index + 1);
      }
    }
  }

  return undefined;
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
