import type { CandidateProfile } from "@jobops/contracts";

export const PUBLIC_PORTFOLIO_UNAVAILABLE_MESSAGE =
  "This portfolio is temporarily unavailable. Please try again later.";

export function unavailableProfile(hostname: string): CandidateProfile {
  return {
    id: hostname,
    slug: hostname,
    displayName: "Portfolio temporarily unavailable",
    headline: "Public profile data could not be loaded.",
    summary: PUBLIC_PORTFOLIO_UNAVAILABLE_MESSAGE,
    profileStatus: "draft",
    facts: [],
    skillClaims: [],
    experienceAndProjects: [],
    evidenceLinks: [],
    hasPublishedPublicContent: false,
    updatedAt: new Date(0).toISOString()
  };
}
