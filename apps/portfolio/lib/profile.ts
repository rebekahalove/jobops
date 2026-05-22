import { headers } from "next/headers";
import type { CandidateProfile } from "@jobops/contracts";
import { publicProfile } from "@jobops/profile";
import { getServerEnvValue } from "./server-env";

const DEFAULT_LOCAL_HOSTNAME = "rebekahalove.dev";

export type ProfileLoadResult = {
  profile: CandidateProfile;
  source: "api" | "seed";
  notFound?: boolean;
};

export async function loadCandidateProfile(): Promise<ProfileLoadResult> {
  const apiBaseUrl = await getServerEnvValue("JOBOPS_API_BASE_URL");
  const hostname = await getRequestHostname();

  if (!apiBaseUrl) {
    return { profile: publicProfile, source: "seed" };
  }

  try {
    const response = await fetch(
      `${apiBaseUrl}/v1/profile-by-hostname/${encodeURIComponent(hostname)}`,
      {
        cache: "no-store"
      }
    );

    if (!response.ok) {
      return { profile: publicProfile, source: "seed" };
    }

    return {
      profile: (await response.json()) as CandidateProfile,
      source: "api"
    };
  } catch {
    return { profile: publicProfile, source: "seed" };
  }
}

export async function loadTenantPortfolioProfile(tenantSlug: string): Promise<ProfileLoadResult> {
  const apiBaseUrl = await getServerEnvValue("JOBOPS_API_BASE_URL");
  if (!apiBaseUrl) {
    return { profile: emptyTenantProfile(tenantSlug), source: "api", notFound: true };
  }

  try {
    const response = await fetch(`${apiBaseUrl}/v1/public/portfolio/${encodeURIComponent(tenantSlug)}`, {
      cache: "no-store"
    });

    if (!response.ok) {
      return { profile: emptyTenantProfile(tenantSlug), source: "api", notFound: true };
    }

    return {
      profile: (await response.json()) as CandidateProfile,
      source: "api"
    };
  } catch {
    return { profile: emptyTenantProfile(tenantSlug), source: "api", notFound: true };
  }
}

async function getRequestHostname() {
  const headerStore = await headers();
  const host = headerStore.get("x-forwarded-host") ?? headerStore.get("host");

  if (!host || host.startsWith("localhost") || host.startsWith("127.0.0.1")) {
    return DEFAULT_LOCAL_HOSTNAME;
  }

  return host.split(":")[0].toLowerCase();
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
