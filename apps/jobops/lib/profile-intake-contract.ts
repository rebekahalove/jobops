import type { JsonSchema, StructuredValidationResult } from "@jobops/model-connector";

export const profileIntakeSources = ["chat", "resume", "model"] as const;
export const profileIntakeItemStatuses = ["draft", "needs_review"] as const;
export const profileIntakeWorkModes = ["remote", "hybrid", "onsite", "flexible"] as const;

export type ProfileIntakeSource = (typeof profileIntakeSources)[number];
export type ProfileIntakeItemStatus = (typeof profileIntakeItemStatuses)[number];
export type ProfileIntakeWorkMode = (typeof profileIntakeWorkModes)[number];

export type ProfileIntakeMetadata = {
  source: ProfileIntakeSource;
  status: ProfileIntakeItemStatus;
  visibility: "private";
  published: false;
};

export type ProfileIntakeOutput = {
  assistantMessage: string;
  targetRoleIntent: {
    targetTitles?: string;
    targetRoleFamilies?: string;
    preferredWorkMode?: ProfileIntakeWorkMode;
    preferredLocations?: string;
    domainsOrIndustries?: string;
    constraints?: string;
  };
  draftFacts: Array<
    ProfileIntakeMetadata & {
      id?: string;
      claim: string;
      category?: string;
    }
  >;
  skillClaims: Array<
    ProfileIntakeMetadata & {
      id?: string;
      skill: string;
      category?: string;
      evidence?: string;
    }
  >;
  experienceAndProjects: Array<
    ProfileIntakeMetadata & {
      id?: string;
      title: string;
      organization?: string;
      summary: string;
    }
  >;
  evidenceLinks: Array<
    ProfileIntakeMetadata & {
      id?: string;
      url: string;
      label?: string;
    }
  >;
  clarifyingQuestions: string[];
  changeSummary: string[];
};

export type ProfileIntakeApiRequest = {
  latestUserMessage: string;
  existingDraft?: unknown;
};

const metadataProperties: Record<string, JsonSchema> = {
  source: { type: "string", enum: [...profileIntakeSources] },
  status: { type: "string", enum: [...profileIntakeItemStatuses] },
  visibility: { type: "string", enum: ["private"] },
  published: { type: "boolean" }
};

export const profileIntakeJsonSchema: JsonSchema = {
  type: "object",
  additionalProperties: false,
  required: [
    "assistantMessage",
    "targetRoleIntent",
    "draftFacts",
    "skillClaims",
    "experienceAndProjects",
    "evidenceLinks",
    "clarifyingQuestions",
    "changeSummary"
  ],
  properties: {
    assistantMessage: { type: "string" },
    targetRoleIntent: {
      type: "object",
      additionalProperties: false,
      properties: {
        targetTitles: { type: "string" },
        targetRoleFamilies: { type: "string" },
        preferredWorkMode: { type: "string", enum: [...profileIntakeWorkModes] },
        preferredLocations: { type: "string" },
        domainsOrIndustries: { type: "string" },
        constraints: { type: "string" }
      }
    },
    draftFacts: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["claim", "source", "status", "visibility", "published"],
        properties: {
          id: { type: "string" },
          claim: { type: "string" },
          category: { type: "string" },
          ...metadataProperties
        }
      }
    },
    skillClaims: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["skill", "source", "status", "visibility", "published"],
        properties: {
          id: { type: "string" },
          skill: { type: "string" },
          category: { type: "string" },
          evidence: { type: "string" },
          ...metadataProperties
        }
      }
    },
    experienceAndProjects: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["title", "summary", "source", "status", "visibility", "published"],
        properties: {
          id: { type: "string" },
          title: { type: "string" },
          organization: { type: "string" },
          summary: { type: "string" },
          ...metadataProperties
        }
      }
    },
    evidenceLinks: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["url", "source", "status", "visibility", "published"],
        properties: {
          id: { type: "string" },
          url: { type: "string" },
          label: { type: "string" },
          ...metadataProperties
        }
      }
    },
    clarifyingQuestions: {
      type: "array",
      items: { type: "string" }
    },
    changeSummary: {
      type: "array",
      items: { type: "string" }
    }
  }
};

export function validateProfileIntakeApiRequest(value: unknown): StructuredValidationResult<ProfileIntakeApiRequest> {
  const objectResult = requirePlainObject(value, "Request");
  if (!objectResult.ok) {
    return objectResult;
  }

  const latestUserMessage = objectResult.value.latestUserMessage;
  if (typeof latestUserMessage !== "string" || latestUserMessage.trim().length === 0) {
    return { ok: false, issues: ["latestUserMessage must be a non-empty string."] };
  }

  return {
    ok: true,
    value: {
      latestUserMessage,
      existingDraft: objectResult.value.existingDraft
    }
  };
}

export function validateProfileIntakeOutput(value: unknown): StructuredValidationResult<ProfileIntakeOutput> {
  const objectResult = requirePlainObject(value, "Output");
  if (!objectResult.ok) {
    return objectResult;
  }

  const issues: string[] = [];
  const output = objectResult.value;

  const assistantMessage = requireString(output.assistantMessage, "assistantMessage", issues);
  const targetRoleIntent = validateTargetRoleIntent(output.targetRoleIntent, issues);
  const draftFacts = validateArray(output.draftFacts, "draftFacts", issues, validateDraftFact);
  const skillClaims = validateArray(output.skillClaims, "skillClaims", issues, validateSkillClaim);
  const experienceAndProjects = validateArray(
    output.experienceAndProjects,
    "experienceAndProjects",
    issues,
    validateExperienceAndProject
  );
  const evidenceLinks = validateArray(output.evidenceLinks, "evidenceLinks", issues, validateEvidenceLink);
  const clarifyingQuestions = validateArray(output.clarifyingQuestions, "clarifyingQuestions", issues, validateStringItem);
  const changeSummary = validateArray(output.changeSummary, "changeSummary", issues, validateStringItem);

  if (issues.length > 0) {
    return { ok: false, issues };
  }

  return {
    ok: true,
    value: {
      assistantMessage,
      targetRoleIntent,
      draftFacts,
      skillClaims,
      experienceAndProjects,
      evidenceLinks,
      clarifyingQuestions,
      changeSummary
    }
  };
}

function validateTargetRoleIntent(value: unknown, issues: string[]): ProfileIntakeOutput["targetRoleIntent"] {
  if (value === undefined) {
    return {};
  }

  const objectResult = requirePlainObject(value, "targetRoleIntent");
  if (!objectResult.ok) {
    issues.push(...objectResult.issues);
    return {};
  }

  return {
    targetTitles: optionalString(objectResult.value.targetTitles, "targetRoleIntent.targetTitles", issues),
    targetRoleFamilies: optionalString(
      objectResult.value.targetRoleFamilies,
      "targetRoleIntent.targetRoleFamilies",
      issues
    ),
    preferredWorkMode: optionalEnum(
      objectResult.value.preferredWorkMode,
      "targetRoleIntent.preferredWorkMode",
      profileIntakeWorkModes,
      issues
    ),
    preferredLocations: optionalString(
      objectResult.value.preferredLocations,
      "targetRoleIntent.preferredLocations",
      issues
    ),
    domainsOrIndustries: optionalString(
      objectResult.value.domainsOrIndustries,
      "targetRoleIntent.domainsOrIndustries",
      issues
    ),
    constraints: optionalString(objectResult.value.constraints, "targetRoleIntent.constraints", issues)
  };
}

function validateDraftFact(value: unknown, path: string, issues: string[]) {
  const object = requireGeneratedItem(value, path, issues);
  return {
    id: optionalString(object.id, `${path}.id`, issues),
    claim: requireString(object.claim, `${path}.claim`, issues),
    category: optionalString(object.category, `${path}.category`, issues),
    ...readMetadata(object, path, issues)
  };
}

function validateSkillClaim(value: unknown, path: string, issues: string[]) {
  const object = requireGeneratedItem(value, path, issues);
  return {
    id: optionalString(object.id, `${path}.id`, issues),
    skill: requireString(object.skill, `${path}.skill`, issues),
    category: optionalString(object.category, `${path}.category`, issues),
    evidence: optionalString(object.evidence, `${path}.evidence`, issues),
    ...readMetadata(object, path, issues)
  };
}

function validateExperienceAndProject(value: unknown, path: string, issues: string[]) {
  const object = requireGeneratedItem(value, path, issues);
  return {
    id: optionalString(object.id, `${path}.id`, issues),
    title: requireString(object.title, `${path}.title`, issues),
    organization: optionalString(object.organization, `${path}.organization`, issues),
    summary: requireString(object.summary, `${path}.summary`, issues),
    ...readMetadata(object, path, issues)
  };
}

function validateEvidenceLink(value: unknown, path: string, issues: string[]) {
  const object = requireGeneratedItem(value, path, issues);
  return {
    id: optionalString(object.id, `${path}.id`, issues),
    url: requireString(object.url, `${path}.url`, issues),
    label: optionalString(object.label, `${path}.label`, issues),
    ...readMetadata(object, path, issues)
  };
}

function validateStringItem(value: unknown, path: string, issues: string[]) {
  return requireString(value, path, issues);
}

function requireGeneratedItem(value: unknown, path: string, issues: string[]) {
  const objectResult = requirePlainObject(value, path);
  if (!objectResult.ok) {
    issues.push(...objectResult.issues);
    return {};
  }

  return objectResult.value;
}

function readMetadata(object: Record<string, unknown>, path: string, issues: string[]): ProfileIntakeMetadata {
  const source = requireEnum(object.source, `${path}.source`, profileIntakeSources, issues);
  const status = requireEnum(object.status, `${path}.status`, profileIntakeItemStatuses, issues);
  const visibility = requireEnum(object.visibility, `${path}.visibility`, ["private"] as const, issues);
  const published = object.published;

  if (published !== false) {
    issues.push(`${path}.published must be false.`);
  }

  return {
    source,
    status,
    visibility,
    published: false
  };
}

function validateArray<T>(
  value: unknown,
  path: string,
  issues: string[],
  validator: (item: unknown, path: string, issues: string[]) => T
): T[] {
  if (!Array.isArray(value)) {
    issues.push(`${path} must be an array.`);
    return [];
  }

  return value.map((item, index) => validator(item, `${path}[${index}]`, issues));
}

function requirePlainObject(
  value: unknown,
  label: string
): StructuredValidationResult<Record<string, unknown>> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return { ok: false, issues: [`${label} must be a JSON object.`] };
  }

  return { ok: true, value: value as Record<string, unknown> };
}

function requireString(value: unknown, path: string, issues: string[]): string {
  if (typeof value !== "string") {
    issues.push(`${path} must be a string.`);
    return "";
  }

  return value;
}

function optionalString(value: unknown, path: string, issues: string[]): string | undefined {
  if (value === undefined) {
    return undefined;
  }

  return requireString(value, path, issues);
}

function requireEnum<T extends readonly string[]>(
  value: unknown,
  path: string,
  allowed: T,
  issues: string[]
): T[number] {
  if (typeof value === "string" && allowed.includes(value)) {
    return value as T[number];
  }

  issues.push(`${path} must be one of: ${allowed.join(", ")}.`);
  return allowed[0];
}

function optionalEnum<T extends readonly string[]>(
  value: unknown,
  path: string,
  allowed: T,
  issues: string[]
): T[number] | undefined {
  if (value === undefined) {
    return undefined;
  }

  return requireEnum(value, path, allowed, issues);
}
