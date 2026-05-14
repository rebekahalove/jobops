export type DashboardWorkflowId =
  | "profile"
  | "companies"
  | "jobs"
  | "applications"
  | "materials"
  | "follow-ups";

export type DashboardWorkflow = {
  id: DashboardWorkflowId;
  label: string;
  href: string;
  purpose: string;
  emptyState: string;
  recommendedStep?: boolean;
};

export const dashboardWorkflows: DashboardWorkflow[] = [
  {
    id: "profile",
    label: "Profile",
    href: "/profile",
    purpose: "Build and maintain the structured career profile that powers JobOps.",
    emptyState:
      "Next up: upload or paste a resume, extract draft profile data with an LLM, then answer clarifying questions to fill gaps.",
    recommendedStep: true
  },
  {
    id: "companies",
    label: "Companies",
    href: "/companies",
    purpose: "Follow target companies and keep AI-ready notes, career links, and outreach context together.",
    emptyState:
      "Watched companies, AI suggestions, careers links, and company notes will live here after command execution exists."
  },
  {
    id: "jobs",
    label: "Jobs",
    href: "/jobs",
    purpose: "Collect job leads and route saved roles into prioritization, applications, and materials.",
    emptyState:
      "The job inbox, saved jobs, AI-discovered jobs, and selected job workbench will live here after job intake exists."
  },
  {
    id: "applications",
    label: "Applications",
    href: "/applications",
    purpose: "Track application status, follow-ups, interviews, and outcomes.",
    emptyState: "Manual application tracking is available now; job intake can attach richer records later."
  },
  {
    id: "materials",
    label: "Materials",
    href: "/materials",
    purpose: "Draft tailored resumes, cover letters, outreach notes, and follow-up messages.",
    emptyState:
      "Generated cover letters, resume variants, short-answer snippets, and downloads will live here after materials generation exists."
  },
  {
    id: "follow-ups",
    label: "Follow-ups",
    href: "/follow-ups",
    purpose: "Review reminders, application events, recruiter touchpoints, and next actions.",
    emptyState:
      "Reminders, application events, and recruiter follow-ups will live here after follow-up planning exists."
  }
];

export function getWorkflow(id: DashboardWorkflowId): DashboardWorkflow {
  const workflow = dashboardWorkflows.find((item) => item.id === id);
  if (!workflow) {
    throw new Error(`Unknown dashboard workflow: ${id}`);
  }

  return workflow;
}
