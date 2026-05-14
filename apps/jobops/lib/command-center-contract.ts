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
  result_payload?: {
    profileDraft?: ProfileIntakeOutput;
    [key: string]: unknown;
  };
};

export type CommandCenterProxyResponse =
  | {
      ok: true;
      result: CommandCenterApiResponse;
    }
  | {
      ok: false;
      error: string;
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
