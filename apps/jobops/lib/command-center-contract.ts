import type { PlannedCommandAction, WorkspaceTab } from "./command-center-actions";
import type { ProfileIntakeOutput } from "./profile-intake-contract";

export type CommandCenterApiRequest = {
  command: string;
  candidateProfileSlug?: string;
  activeWorkspace?: WorkspaceTab;
  clientContext?: Record<string, unknown>;
};

export type CommandCenterApiResponse = {
  assistant_message: string;
  actions: Array<Omit<PlannedCommandAction, "id"> & { id?: string }>;
  target_workspace?: WorkspaceTab;
  statusUpdates?: CommandCenterStatusUpdate[];
  result_payload?: {
    profileDraft?: ProfileIntakeOutput;
    [key: string]: unknown;
  };
};

export type CommandCenterStatusUpdate = {
  stage: string;
  message: string;
  actionType?: PlannedCommandAction["type"];
  confidence?: "high" | "medium" | "low" | string | null;
  targetWorkspace?: WorkspaceTab | null;
};

export type JobSearchRunStatus = {
  id: string;
  status: "queued" | "started" | "running" | "completed" | "failed" | "needs_confirmation" | "cancelled" | string;
  searchMode?: string | null;
  createdAt?: string | null;
  startedAt?: string | null;
  completedAt?: string | null;
  providerResultCount: number;
  candidatePoolCount: number;
  candidateCountAfterDedupe: number;
  modelSelectedCount: number;
  savedCount: number;
  updatedExistingCount: number;
  duplicateCount: number;
  skippedCount: number;
  providerErrorCount: number;
  error?: string | null;
  message: string;
  userVisibleSummary?: string | null;
  userSummary?: string | null;
  plannerRationale?: string | null;
  plannerFallbackUsed?: boolean | null;
  recentSearchesUsed?: number;
  selectionAssistantMessage?: string | null;
  selectionSkippedCandidateNotes?: Array<{ candidateId: string; reason: string }>;
  selectionClarifyingQuestions?: string[];
  replansAttempted?: number;
  replanLimit?: number | null;
  replanningStatus?: string | null;
  replanningDecision?: string | null;
  replanReason?: string | null;
  replanReasons?: string[];
  replanQueries?: string[];
  diagnostics?: JobSearchRunDiagnostics;
};

export type JobSearchRunDiagnostics = {
  searchCriteria?: {
    searchMode?: string | null;
    roleQueries?: string[];
    companyNames?: string[];
    locations?: string[];
    remoteWorkModes?: string[];
    salaryMin?: number | null;
    excludeTerms?: string[];
    maxProviderPages?: number | null;
  };
  providerDiagnostics?: JobSearchProviderDiagnostic[];
  modelReview?: {
    candidateCountAfterDedupe?: number;
    candidatePoolCount?: number;
    modelSelectedCount?: number;
    savedCount?: number;
    updatedExistingCount?: number;
    duplicateCount?: number;
    skippedCount?: number;
    providerErrorCount?: number;
  };
  modelExplanation?: {
    userVisibleSummary?: string | null;
    userSummary?: string | null;
    plannerRationale?: string | null;
    selectionAssistantMessage?: string | null;
    skippedCandidateNotes?: Array<{ candidateId: string; reason: string }>;
  };
  replanning?: {
    replansAttempted?: number | null;
    replanLimit?: number | null;
    replanReasons?: string[];
    replanningDecision?: string | null;
    replanQueries?: string[];
    displayLabel?: string | null;
    displayMessage?: string | null;
    triggerProviderName?: string | null;
    triggerProviderType?: string | null;
    companyBoardsReturnedCandidates?: boolean;
    providerResultsExisted?: boolean;
    candidatePoolExisted?: boolean;
  };
};

export type JobSearchProviderDiagnostic = {
  providerName?: string | null;
  providerType?: string | null;
  companyName?: string | null;
  boardToken?: string | null;
  attempted?: boolean;
  configured?: boolean;
  queryPreview?: string | null;
  requestCriteria?: Record<string, unknown> | null;
  rawResultCount?: number | null;
  resultCount?: number | null;
  normalizedResultCount?: number | null;
  dedupedResultCount?: number | null;
  candidateCountAfterFilters?: number | null;
  totalMatches?: number | null;
  page?: number | null;
  pagesAttempted?: number | null;
  errorSummary?: string | null;
  searchMode?: string | null;
  reason?: string | null;
};

export type CommandCenterProxyResponse =
  | {
      ok: true;
      result: CommandCenterApiResponse;
    }
  | {
      ok: false;
      error: string;
      diagnostic?: {
        code: string;
        contentType: string | null;
        likelyCause: string;
        message?: string;
        responseHost?: string | null;
        status: number;
      };
    };

export type CommandCenterStreamEvent =
  | {
      type: "status";
      statusUpdate: CommandCenterStatusUpdate;
    }
  | {
      type: "result";
      result: CommandCenterApiResponse;
    };

export function validateCommandCenterApiRequest(value: unknown):
  | {
      ok: true;
      value: CommandCenterApiRequest;
    }
  | {
      ok: false;
      issues: string[];
    } {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return { ok: false, issues: ["Request must be a JSON object."] };
  }

  const request = value as Record<string, unknown>;
  if (typeof request.command !== "string" || request.command.trim().length === 0) {
    return { ok: false, issues: ["command must be a non-empty string."] };
  }

  return {
    ok: true,
    value: {
      command: request.command,
      candidateProfileSlug:
        typeof request.candidateProfileSlug === "string" && request.candidateProfileSlug.trim().length > 0
          ? request.candidateProfileSlug
          : undefined,
      activeWorkspace: isWorkspaceTab(request.activeWorkspace) ? request.activeWorkspace : undefined,
      clientContext:
        request.clientContext !== null && typeof request.clientContext === "object" && !Array.isArray(request.clientContext)
          ? (request.clientContext as Record<string, unknown>)
          : undefined
    }
  };
}

export function isWorkspaceTab(value: unknown): value is WorkspaceTab {
  return (
    value === "profile" ||
    value === "companies" ||
    value === "jobs" ||
    value === "applications" ||
    value === "materials" ||
    value === "follow-ups"
  );
}
