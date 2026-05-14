export const workspaceTabs = ["profile", "companies", "jobs", "applications", "materials", "follow-ups"] as const;

export type WorkspaceTab = (typeof workspaceTabs)[number];

export const commandCenterActionTypes = [
  "add_job_from_url",
  "follow_company",
  "prioritize_jobs",
  "generate_materials",
  "mark_applied",
  "update_profile",
  "follow_up_review",
  "unknown"
] as const;

export type CommandCenterActionType = (typeof commandCenterActionTypes)[number];

export type PlannedActionStatus = "planned" | "needs_confirmation" | "completed" | "failed";

export type PlannedCommandAction = {
  id: string;
  type: CommandCenterActionType;
  title: string;
  summary: string;
  status: PlannedActionStatus;
  targetWorkspace?: WorkspaceTab;
  ctaLabel?: string;
};

export type ClassifiedCommand = {
  type: CommandCenterActionType;
  targetWorkspace?: WorkspaceTab;
  title: string;
  ctaLabel?: string;
};

const actionDetails: Record<CommandCenterActionType, ClassifiedCommand> = {
  add_job_from_url: {
    type: "add_job_from_url",
    targetWorkspace: "jobs",
    title: "Add job from URL",
    ctaLabel: "Open Jobs"
  },
  follow_company: {
    type: "follow_company",
    targetWorkspace: "companies",
    title: "Follow company",
    ctaLabel: "Open Companies"
  },
  prioritize_jobs: {
    type: "prioritize_jobs",
    targetWorkspace: "jobs",
    title: "Prioritize saved jobs",
    ctaLabel: "Open Jobs"
  },
  generate_materials: {
    type: "generate_materials",
    targetWorkspace: "materials",
    title: "Generate application materials",
    ctaLabel: "Open Materials"
  },
  mark_applied: {
    type: "mark_applied",
    targetWorkspace: "applications",
    title: "Mark job as applied",
    ctaLabel: "Open Applications"
  },
  update_profile: {
    type: "update_profile",
    targetWorkspace: "profile",
    title: "Update profile",
    ctaLabel: "Open Profile"
  },
  follow_up_review: {
    type: "follow_up_review",
    targetWorkspace: "follow-ups",
    title: "Review follow-ups",
    ctaLabel: "Open Follow-ups"
  },
  unknown: {
    type: "unknown",
    title: "Review command",
    ctaLabel: "Review"
  }
};

export function classifyCommand(command: string): ClassifiedCommand {
  const normalized = command.toLowerCase();

  if (/\bfollow[-\s]?up\b/.test(normalized) || normalized.includes("follow up on") || normalized.includes("follow up this week")) {
    return actionDetails.follow_up_review;
  }

  if (normalized.includes("material") || normalized.includes("cover letter") || normalized.includes("resume variant")) {
    return actionDetails.generate_materials;
  }

  if (normalized.includes("mark") && normalized.includes("applied")) {
    return actionDetails.mark_applied;
  }

  if (normalized.includes("update my profile") || normalized.includes("add this project") || normalized.includes("with this project")) {
    return actionDetails.update_profile;
  }

  if (normalized.includes("prioritize") || normalized.includes("which jobs") || normalized.includes("apply to today")) {
    return actionDetails.prioritize_jobs;
  }

  if (normalized.includes("follow this company") || normalized.includes("follow company") || normalized.includes("watch this company")) {
    return actionDetails.follow_company;
  }

  if (/https?:\/\/\S+/.test(command) || normalized.includes("job url") || normalized.includes("add it to my jobs")) {
    return actionDetails.add_job_from_url;
  }

  return actionDetails.unknown;
}

export function createPlannedAction(command: string, id: string): PlannedCommandAction {
  const classified = classifyCommand(command);
  const workspace = classified.targetWorkspace ? formatWorkspaceLabel(classified.targetWorkspace) : "the command center";

  return {
    id,
    type: classified.type,
    title: classified.title,
    summary:
      classified.type === "unknown"
        ? `JobOps captured "${command}" and needs a clearer workspace or action before it can route this.`
        : `JobOps understood "${command}" as a planned ${classified.title.toLowerCase()} action for ${workspace}.`,
    status: "planned",
    targetWorkspace: classified.targetWorkspace,
    ctaLabel: classified.ctaLabel
  };
}

export function formatWorkspaceLabel(workspace: WorkspaceTab): string {
  if (workspace === "follow-ups") {
    return "Follow-ups";
  }

  return workspace.replace(/^\w/, (letter) => letter.toUpperCase());
}
