export class ModelConfigurationError extends Error {
  readonly code: string;

  constructor(message: string, code = "MODEL_CONFIGURATION_ERROR") {
    super(message);
    this.name = "ModelConfigurationError";
    this.code = code;
  }
}

export class StructuredOutputValidationError extends Error {
  readonly issues: string[];

  constructor(issues: string[]) {
    super(`Model output failed structured validation: ${issues.join("; ")}`);
    this.name = "StructuredOutputValidationError";
    this.issues = issues;
  }
}
