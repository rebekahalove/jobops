import "server-only";

import { getJobOpsApiServerConfig } from "./server-env";

export type PublicJobOpsMetric = {
  id: string;
  label: string;
  value: number;
};

const DEFAULT_METRICS: PublicJobOpsMetric[] = [
  { id: "alphaAccessRequests", label: "Alpha access requests", value: 0 },
  { id: "usersOnboarded", label: "Users onboarded", value: 0 },
  { id: "companiesTracked", label: "Companies tracked", value: 0 },
  { id: "jobsTracked", label: "Jobs tracked", value: 0 },
  { id: "profileDraftsCreated", label: "Profile drafts created", value: 0 },
  { id: "profileDraftsPublished", label: "Profile drafts published", value: 0 },
  { id: "applicationsTracked", label: "Applications tracked", value: 0 },
  { id: "aiAssistedActionsCompleted", label: "AI-assisted actions completed", value: 0 }
];

export async function getPublicJobOpsMetrics(): Promise<PublicJobOpsMetric[]> {
  try {
    const config = await getJobOpsApiServerConfig();
    const response = await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/public/jobops/metrics`, {
      cache: "no-store",
      headers: {
        "X-JobOps-Internal-Key": config.internalApiKey
      }
    });

    if (!response.ok) {
      return DEFAULT_METRICS;
    }

    const payload = await response.json();
    return normalizeMetrics(payload?.result?.metrics);
  } catch {
    return DEFAULT_METRICS;
  }
}

function normalizeMetrics(value: unknown): PublicJobOpsMetric[] {
  if (!Array.isArray(value)) {
    return DEFAULT_METRICS;
  }

  const valuesById = new Map(
    value
      .filter(isMetricLike)
      .map((item) => [
        item.id,
        {
          id: item.id,
          label: item.label,
          value: item.value
        }
      ])
  );

  return DEFAULT_METRICS.map((fallback) => valuesById.get(fallback.id) ?? fallback);
}

function isMetricLike(value: unknown): value is PublicJobOpsMetric {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as PublicJobOpsMetric).id === "string" &&
    typeof (value as PublicJobOpsMetric).label === "string" &&
    typeof (value as PublicJobOpsMetric).value === "number"
  );
}
