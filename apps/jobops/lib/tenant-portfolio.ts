import "server-only";
import type { CandidateProfile } from "@jobops/contracts";
import { getJobOpsApiServerConfig } from "./server-env";

export type TenantPortfolioLoadResult = {
  profile: CandidateProfile;
  source: "api";
};

export async function loadTenantPortfolioProfile(tenantSlug: string): Promise<TenantPortfolioLoadResult> {
  try {
    const config = await getJobOpsApiServerConfig();
    const response = await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/public/portfolio/${encodeURIComponent(tenantSlug)}`, {
      cache: "no-store"
    });
    if (!response.ok) {
      return { profile: emptyTenantProfile(tenantSlug), source: "api" };
    }
    return {
      profile: (await response.json()) as CandidateProfile,
      source: "api"
    };
  } catch {
    return { profile: emptyTenantProfile(tenantSlug), source: "api" };
  }
}

function emptyTenantProfile(tenantSlug: string): CandidateProfile {
  return {
    id: tenantSlug,
    slug: tenantSlug,
    displayName: "Profile not published yet",
    headline: "This JobOps portfolio is not public yet.",
    summary: "",
    profileStatus: "draft",
    facts: [],
    skillClaims: [],
    experienceAndProjects: [],
    evidenceLinks: [],
    hasPublishedPublicContent: false,
    updatedAt: new Date(0).toISOString()
  };
}
