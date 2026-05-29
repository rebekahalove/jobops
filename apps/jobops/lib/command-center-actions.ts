export const workspaceTabs = ["profile", "companies", "jobs", "applications", "materials", "follow-ups"] as const;

export type WorkspaceTab = (typeof workspaceTabs)[number];

export const commandCenterActionTypes = [
  "add_job_from_url",
  "company_discovery",
  "company_update",
  "job_discovery",
  "follow_company",
  "prioritize_jobs",
  "generate_materials",
  "mark_applied",
  "profile_intake",
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
  resultPayload?: unknown;
};

export const workspaceRoutes: Record<WorkspaceTab, string> = {
  profile: "/profile",
  companies: "/companies",
  jobs: "/jobs",
  applications: "/applications",
  materials: "/materials",
  "follow-ups": "/follow-ups"
};

export function getWorkspaceRoute(workspace: WorkspaceTab, basePath = "") {
  return `${basePath}${workspaceRoutes[workspace]}`;
}

const COMMAND_PREVIEW_MAX_CHARS = 180;

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
  company_discovery: {
    type: "company_discovery",
    targetWorkspace: "companies",
    title: "Discover companies",
    ctaLabel: "Open Companies"
  },
  company_update: {
    type: "company_update",
    targetWorkspace: "companies",
    title: "Update company",
    ctaLabel: "Open Companies"
  },
  job_discovery: {
    type: "job_discovery",
    targetWorkspace: "jobs",
    title: "Discover jobs",
    ctaLabel: "Open Jobs"
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
  profile_intake: {
    type: "profile_intake",
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

  if (
    normalized.includes("i want to be") ||
    normalized.includes("update my profile") ||
    normalized.includes("add this project") ||
    normalized.includes("with this project") ||
    normalized.includes("my experience") ||
    normalized.includes("my skills") ||
    normalized.includes("resume") ||
    looksLikeResumeText(command)
  ) {
    return actionDetails.profile_intake;
  }

  if (
    (normalized.includes("company") || normalized.includes("careers url") || normalized.includes("job listings url") || normalized.includes("source url")) &&
    (normalized.includes("update") || normalized.includes("set") || normalized.includes("add this"))
  ) {
    return actionDetails.company_update;
  }

  if (normalized.includes("prioritize") || normalized.includes("which jobs") || normalized.includes("apply to today")) {
    return actionDetails.prioritize_jobs;
  }

  if (
    normalized.includes("follow this company") ||
    normalized.includes("follow company") ||
    normalized.includes("follow companies") ||
    normalized.includes("companies to follow") ||
    normalized.includes("companies i should follow") ||
    normalized.includes("companies that i should follow") ||
    normalized.includes("companies that i should be following") ||
    normalized.includes("companies should i follow") ||
    normalized.includes("companies should i be following") ||
    normalized.includes("companies to watch") ||
    normalized.includes("companies to track") ||
    normalized.includes("watch this company") ||
    normalized.includes("watch companies") ||
    normalized.includes("find companies") ||
    normalized.includes("find me companies") ||
    (normalized.includes("find") && normalized.includes("companies")) ||
    (normalized.includes("companies") && normalized.includes("who hire")) ||
    (normalized.includes("companies") && normalized.includes("that hire")) ||
    (normalized.includes("companies") &&
      (normalized.includes("following") || normalized.includes("watch") || normalized.includes("track") || normalized.includes("research"))) ||
    normalized.includes("discover companies") ||
    normalized.includes("company discovery")
  ) {
    return actionDetails.company_discovery;
  }

  if (/https?:\/\/\S+/.test(command) || normalized.includes("job url") || normalized.includes("add it to my jobs")) {
    return actionDetails.add_job_from_url;
  }

  if (looksLikeJobDiscovery(normalized)) {
    return actionDetails.job_discovery;
  }

  return actionDetails.unknown;
}

export function createPlannedAction(command: string, id: string): PlannedCommandAction {
  const classified = classifyCommand(command);
  const workspace = classified.targetWorkspace ? formatWorkspaceLabel(classified.targetWorkspace) : "the command center";
  const commandPreview = summarizeCommandForDisplay(command);

  return {
    id,
    type: classified.type,
    title: classified.title,
    summary:
      classified.type === "unknown"
        ? `JobOps captured ${commandPreview} and needs a clearer workspace or action before it can route this.`
        : `JobOps understood ${commandPreview} as a planned ${classified.title.toLowerCase()} action for ${workspace}.`,
    status: "planned",
    targetWorkspace: classified.targetWorkspace,
    ctaLabel: classified.ctaLabel
  };
}

export function summarizeCommandForDisplay(command: string, maxLength = COMMAND_PREVIEW_MAX_CHARS): string {
  const compact = command.replace(/\s+/g, " ").trim();
  if (!compact) {
    return "this command";
  }
  if (compact.length <= maxLength) {
    return `"${compact}"`;
  }

  const preview = compact.slice(0, Math.max(0, maxLength - 3)).trimEnd();
  return `"${preview}..." (${compact.length.toLocaleString()} chars)`;
}

function looksLikeResumeText(command: string) {
  const normalized = command.toLowerCase();
  const signals = [
    "professional summary",
    "core skills",
    "technical skills",
    "professional experience",
    "work experience",
    "selected technical strengths",
    "selected platform highlights",
    "education",
    "certification",
    "linkedin.com/in/"
  ];
  const signalCount = signals.filter((signal) => normalized.includes(signal)).length;

  return signalCount >= 2 || (command.length >= 1500 && signalCount >= 1);
}

function looksLikeJobDiscovery(normalized: string) {
  return (
    normalized.includes("find me some jobs") ||
    normalized.includes("find me jobs") ||
    normalized.includes("find some jobs") ||
    normalized.includes("find jobs") ||
    normalized.includes("discover jobs") ||
    normalized.includes("job discovery") ||
    normalized.includes("jobs to apply to") ||
    normalized.includes("jobs that fit my profile") ||
    normalized.includes("roles i should consider") ||
    normalized.includes("show me roles") ||
    normalized.includes("show me jobs") ||
    normalized.includes("find me applied ai") ||
    normalized.includes("find applied ai") ||
    normalized.includes("find remote") ||
    normalized.includes("find ai platform") ||
    normalized.includes("find jobs like this")
  );
}

export function formatWorkspaceLabel(workspace: WorkspaceTab): string {
  if (workspace === "follow-ups") {
    return "Follow-ups";
  }

  return workspace.replace(/^\w/, (letter) => letter.toUpperCase());
}
