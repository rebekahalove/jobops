export type DashboardWorkflowId =
  | "profile"
  | "jobs"
  | "fit-scoring"
  | "materials"
  | "applications";

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
    id: "jobs",
    label: "Jobs",
    href: "/jobs",
    purpose: "Ingest and track job postings worth evaluating.",
    emptyState: "Job posting intake comes after the first structured profile is ready."
  },
  {
    id: "fit-scoring",
    label: "Fit Scoring",
    href: "/fit-scoring",
    purpose: "Compare jobs against the structured user profile.",
    emptyState: "Fit scoring depends on both an approved profile and saved job records."
  },
  {
    id: "materials",
    label: "Materials",
    href: "/materials",
    purpose: "Draft tailored resumes, cover letters, outreach notes, and follow-up messages.",
    emptyState: "Application materials depend on the profile and a selected job."
  },
  {
    id: "applications",
    label: "Applications",
    href: "/applications",
    purpose: "Track application status, follow-ups, interviews, and outcomes.",
    emptyState: "Application tracking comes after job intake."
  }
];

export function getWorkflow(id: DashboardWorkflowId): DashboardWorkflow {
  const workflow = dashboardWorkflows.find((item) => item.id === id);
  if (!workflow) {
    throw new Error(`Unknown dashboard workflow: ${id}`);
  }

  return workflow;
}
