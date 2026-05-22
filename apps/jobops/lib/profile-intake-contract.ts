export const profileIntakeSources = ["chat", "resume", "model"] as const;
export const profileIntakeItemStatuses = ["draft", "needs_review", "candidate_approved", "reviewed", "rejected", "published"] as const;
export const profileIntakeWorkModes = ["remote", "hybrid", "onsite", "flexible"] as const;

export type ProfileIntakeSource = (typeof profileIntakeSources)[number];
export type ProfileIntakeItemStatus = (typeof profileIntakeItemStatuses)[number];
export type ProfileIntakeWorkMode = (typeof profileIntakeWorkModes)[number];
export type ProfileExperienceItemType = "experience" | "project" | "education" | "certification";

export type ProfileIntakeMetadata = {
  source: ProfileIntakeSource;
  status: ProfileIntakeItemStatus;
  visibility: "private" | "public";
  published: boolean;
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
      yearsMin?: number;
      yearsMax?: number;
    }
  >;
  experienceAndProjects: Array<
    ProfileIntakeMetadata & {
      id?: string;
      itemType?: ProfileExperienceItemType;
      title: string;
      organization?: string;
      startDate?: string;
      endDate?: string;
      location?: string;
      summary: string;
      bullets?: string[];
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
  candidateProfileSlug?: string;
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
      existingDraft: request.existingDraft,
      candidateProfileSlug:
        typeof request.candidateProfileSlug === "string" && request.candidateProfileSlug.trim().length > 0
          ? request.candidateProfileSlug
          : undefined
    }
  };
}
