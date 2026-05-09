import { headers } from "next/headers";
import type { CandidateProfile } from "@jobops/contracts";
import { publicProfile } from "@jobops/profile";
import { getServerEnvValue } from "./server-env";

const DEFAULT_LOCAL_HOSTNAME = "rebekahalove.dev";

export type ProfileLoadResult = {
  profile: CandidateProfile;
  source: "api" | "seed";
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

async function getRequestHostname() {
  const headerStore = await headers();
  const host = headerStore.get("x-forwarded-host") ?? headerStore.get("host");

  if (!host || host.startsWith("localhost") || host.startsWith("127.0.0.1")) {
    return DEFAULT_LOCAL_HOSTNAME;
  }

  return host.split(":")[0].toLowerCase();
}
