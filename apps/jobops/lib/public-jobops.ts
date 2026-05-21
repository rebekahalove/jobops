import "server-only";

import { getJobOpsApiServerConfig } from "./server-env";

export type PublicJobOpsMetric = {
  id: string;
  label: string;
  value: number | null;
};

const DEFAULT_METRICS: PublicJobOpsMetric[] = [
  { id: "usersOnboarded", label: "Alpha users onboarded", value: null },
  { id: "companiesTracked", label: "Companies tracked", value: null },
  { id: "jobsTracked", label: "Jobs saved", value: null },
  { id: "applicationsTracked", label: "Applications tracked", value: null },
  { id: "profileDraftsCreated", label: "Profile drafts created", value: null },
  { id: "aiAssistedActionsCompleted", label: "AI-assisted workflow actions", value: null }
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

  return DEFAULT_METRICS.map((fallback) => {
    const metric = valuesById.get(fallback.id);
    return metric ? { ...metric, label: fallback.label } : fallback;
  });
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
