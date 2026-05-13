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

export type StructuredValidationResult<T> =
  | {
      ok: true;
      value: T;
    }
  | {
      ok: false;
      issues: string[];
    };

export function validateProfileIntakeApiRequest(value: unknown): StructuredValidationResult<ProfileIntakeApiRequest> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return { ok: false, issues: ["Request must be a JSON object."] };
  }

  const request = value as Record<string, unknown>;
  const latestUserMessage = request.latestUserMessage;

  if (typeof latestUserMessage !== "string" || latestUserMessage.trim().length === 0) {
    return { ok: false, issues: ["latestUserMessage must be a non-empty string."] };
  }

  return {
    ok: true,
    value: {
      latestUserMessage,
      existingDraft: request.existingDraft
    }
  };
}
