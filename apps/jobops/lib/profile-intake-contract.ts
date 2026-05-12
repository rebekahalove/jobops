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

const MAX_ASSISTANT_MESSAGE_LENGTH = 400;
const MAX_TARGET_FIELD_LENGTH = 200;
const MAX_SHORT_FIELD_LENGTH = 120;
const MAX_MEDIUM_FIELD_LENGTH = 240;
const MAX_LONG_FIELD_LENGTH = 320;
const MAX_URL_LENGTH = 1000;

const MAX_DRAFT_FACTS = 4;
const MAX_SKILL_CLAIMS = 6;
const MAX_EXPERIENCE_AND_PROJECTS = 3;
const MAX_EVIDENCE_LINKS = 4;
const MAX_CLARIFYING_QUESTIONS = 3;
const MAX_CHANGE_SUMMARY_ITEMS = 3;

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
    assistantMessage: { type: "string", maxLength: MAX_ASSISTANT_MESSAGE_LENGTH },
    targetRoleIntent: {
      type: "object",
      additionalProperties: false,
      properties: {
        targetTitles: { type: "string", maxLength: MAX_TARGET_FIELD_LENGTH },
        targetRoleFamilies: { type: "string", maxLength: MAX_TARGET_FIELD_LENGTH },
        preferredWorkMode: { type: "string", enum: [...profileIntakeWorkModes] },
        preferredLocations: { type: "string", maxLength: MAX_TARGET_FIELD_LENGTH },
        domainsOrIndustries: { type: "string", maxLength: MAX_TARGET_FIELD_LENGTH },
        constraints: { type: "string", maxLength: MAX_TARGET_FIELD_LENGTH }
      }
    },
    draftFacts: {
      type: "array",
      maxItems: MAX_DRAFT_FACTS,
      items: {
        type: "object",
        additionalProperties: false,
        required: ["claim", "source", "status", "visibility", "published"],
        properties: {
          id: { type: "string", maxLength: MAX_SHORT_FIELD_LENGTH },
          claim: { type: "string", maxLength: MAX_MEDIUM_FIELD_LENGTH },
          category: { type: "string", maxLength: MAX_SHORT_FIELD_LENGTH },
          ...metadataProperties
        }
      }
    },
    skillClaims: {
      type: "array",
      maxItems: MAX_SKILL_CLAIMS,
      items: {
        type: "object",
        additionalProperties: false,
        required: ["skill", "source", "status", "visibility", "published"],
        properties: {
          id: { type: "string", maxLength: MAX_SHORT_FIELD_LENGTH },
          skill: { type: "string", maxLength: MAX_SHORT_FIELD_LENGTH },
          category: { type: "string", maxLength: MAX_SHORT_FIELD_LENGTH },
          evidence: { type: "string", maxLength: MAX_MEDIUM_FIELD_LENGTH },
          ...metadataProperties
        }
      }
    },
    experienceAndProjects: {
      type: "array",
      maxItems: MAX_EXPERIENCE_AND_PROJECTS,
      items: {
        type: "object",
        additionalProperties: false,
        required: ["title", "summary", "source", "status", "visibility", "published"],
        properties: {
          id: { type: "string", maxLength: MAX_SHORT_FIELD_LENGTH },
          title: { type: "string", maxLength: MAX_TARGET_FIELD_LENGTH },
          organization: { type: "string", maxLength: MAX_TARGET_FIELD_LENGTH },
          summary: { type: "string", maxLength: MAX_LONG_FIELD_LENGTH },
          ...metadataProperties
        }
      }
    },
    evidenceLinks: {
      type: "array",
      maxItems: MAX_EVIDENCE_LINKS,
      items: {
        type: "object",
        additionalProperties: false,
        required: ["url", "source", "status", "visibility", "published"],
        properties: {
          id: { type: "string", maxLength: MAX_SHORT_FIELD_LENGTH },
          url: { type: "string", maxLength: MAX_URL_LENGTH },
          label: { type: "string", maxLength: MAX_TARGET_FIELD_LENGTH },
          ...metadataProperties
        }
      }
    },
    clarifyingQuestions: {
      type: "array",
      maxItems: MAX_CLARIFYING_QUESTIONS,
      items: { type: "string", maxLength: MAX_MEDIUM_FIELD_LENGTH }
    },
    changeSummary: {
      type: "array",
      maxItems: MAX_CHANGE_SUMMARY_ITEMS,
      items: { type: "string", maxLength: MAX_MEDIUM_FIELD_LENGTH }
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

  const assistantMessage = requireBoundedString(
    output.assistantMessage,
    "assistantMessage",
    MAX_ASSISTANT_MESSAGE_LENGTH,
    issues
  );
  const targetRoleIntent = validateTargetRoleIntent(output.targetRoleIntent, issues);
  const draftFacts = validateArray(output.draftFacts, "draftFacts", issues, validateDraftFact, MAX_DRAFT_FACTS);
  const skillClaims = validateArray(output.skillClaims, "skillClaims", issues, validateSkillClaim, MAX_SKILL_CLAIMS);
  const experienceAndProjects = validateArray(
    output.experienceAndProjects,
    "experienceAndProjects",
    issues,
    validateExperienceAndProject,
    MAX_EXPERIENCE_AND_PROJECTS
  );
  const evidenceLinks = validateArray(output.evidenceLinks, "evidenceLinks", issues, validateEvidenceLink, MAX_EVIDENCE_LINKS);
  const clarifyingQuestions = validateArray(
    output.clarifyingQuestions,
    "clarifyingQuestions",
    issues,
    validateMediumStringItem,
    MAX_CLARIFYING_QUESTIONS
  );
  const changeSummary = validateArray(
    output.changeSummary,
    "changeSummary",
    issues,
    validateMediumStringItem,
    MAX_CHANGE_SUMMARY_ITEMS
  );

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
    targetTitles: optionalBoundedString(
      objectResult.value.targetTitles,
      "targetRoleIntent.targetTitles",
      MAX_TARGET_FIELD_LENGTH,
      issues
    ),
    targetRoleFamilies: optionalBoundedString(
      objectResult.value.targetRoleFamilies,
      "targetRoleIntent.targetRoleFamilies",
      MAX_TARGET_FIELD_LENGTH,
      issues
    ),
    preferredWorkMode: optionalEnum(
      objectResult.value.preferredWorkMode,
      "targetRoleIntent.preferredWorkMode",
      profileIntakeWorkModes,
      issues
    ),
    preferredLocations: optionalBoundedString(
      objectResult.value.preferredLocations,
      "targetRoleIntent.preferredLocations",
      MAX_TARGET_FIELD_LENGTH,
      issues
    ),
    domainsOrIndustries: optionalBoundedString(
      objectResult.value.domainsOrIndustries,
      "targetRoleIntent.domainsOrIndustries",
      MAX_TARGET_FIELD_LENGTH,
      issues
    ),
    constraints: optionalBoundedString(
      objectResult.value.constraints,
      "targetRoleIntent.constraints",
      MAX_TARGET_FIELD_LENGTH,
      issues
    )
  };
}

function validateDraftFact(value: unknown, path: string, issues: string[]) {
  const object = requireGeneratedItem(value, path, issues);
  return {
    id: optionalBoundedString(object.id, `${path}.id`, MAX_SHORT_FIELD_LENGTH, issues),
    claim: requireBoundedString(object.claim, `${path}.claim`, MAX_MEDIUM_FIELD_LENGTH, issues),
    category: optionalBoundedString(object.category, `${path}.category`, MAX_SHORT_FIELD_LENGTH, issues),
    ...readMetadata(object, path, issues)
  };
}

function validateSkillClaim(value: unknown, path: string, issues: string[]) {
  const object = requireGeneratedItem(value, path, issues);
  return {
    id: optionalBoundedString(object.id, `${path}.id`, MAX_SHORT_FIELD_LENGTH, issues),
    skill: requireBoundedString(object.skill, `${path}.skill`, MAX_SHORT_FIELD_LENGTH, issues),
    category: optionalBoundedString(object.category, `${path}.category`, MAX_SHORT_FIELD_LENGTH, issues),
    evidence: optionalBoundedString(object.evidence, `${path}.evidence`, MAX_MEDIUM_FIELD_LENGTH, issues),
    ...readMetadata(object, path, issues)
  };
}

function validateExperienceAndProject(value: unknown, path: string, issues: string[]) {
  const object = requireGeneratedItem(value, path, issues);
  return {
    id: optionalBoundedString(object.id, `${path}.id`, MAX_SHORT_FIELD_LENGTH, issues),
    title: requireBoundedString(object.title, `${path}.title`, MAX_TARGET_FIELD_LENGTH, issues),
    organization: optionalBoundedString(object.organization, `${path}.organization`, MAX_TARGET_FIELD_LENGTH, issues),
    summary: requireBoundedString(object.summary, `${path}.summary`, MAX_LONG_FIELD_LENGTH, issues),
    ...readMetadata(object, path, issues)
  };
}

function validateEvidenceLink(value: unknown, path: string, issues: string[]) {
  const object = requireGeneratedItem(value, path, issues);
  return {
    id: optionalBoundedString(object.id, `${path}.id`, MAX_SHORT_FIELD_LENGTH, issues),
    url: requireBoundedString(object.url, `${path}.url`, MAX_URL_LENGTH, issues),
    label: optionalBoundedString(object.label, `${path}.label`, MAX_TARGET_FIELD_LENGTH, issues),
    ...readMetadata(object, path, issues)
  };
}

function validateMediumStringItem(value: unknown, path: string, issues: string[]) {
  return requireBoundedString(value, path, MAX_MEDIUM_FIELD_LENGTH, issues);
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
  validator: (item: unknown, path: string, issues: string[]) => T,
  maxItems: number
): T[] {
  if (!Array.isArray(value)) {
    issues.push(`${path} must be an array.`);
    return [];
  }

  if (value.length > maxItems) {
    issues.push(`${path} must contain at most ${maxItems} item(s).`);
  }

  return value.slice(0, maxItems).map((item, index) => validator(item, `${path}[${index}]`, issues));
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

function requireBoundedString(value: unknown, path: string, maxLength: number, issues: string[]): string {
  const stringValue = requireString(value, path, issues);

  if (stringValue.length > maxLength) {
    issues.push(`${path} must be ${maxLength} characters or fewer.`);
  }

  return stringValue;
}

function optionalBoundedString(
  value: unknown,
  path: string,
  maxLength: number,
  issues: string[]
): string | undefined {
  if (value === undefined) {
    return undefined;
  }

  return requireBoundedString(value, path, maxLength, issues);
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
