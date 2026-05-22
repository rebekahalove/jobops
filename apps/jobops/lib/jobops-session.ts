import "server-only";
import { cookies } from "next/headers";
import { JOBOPS_SESSION_COOKIE_NAME } from "./dashboard-auth";
import type { JobOpsServerSession } from "./jobops-session-contract";
import { getJobOpsApiServerConfig } from "./server-env";

export async function getCurrentJobOpsSession(): Promise<JobOpsServerSession> {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get(JOBOPS_SESSION_COOKIE_NAME)?.value;
  if (!sessionCookie) {
    return { isAuthenticated: false };
  }

  return resolveJobOpsSessionFromCookieHeader(`${JOBOPS_SESSION_COOKIE_NAME}=${sessionCookie}`);
}

export async function resolveJobOpsSessionFromCookieHeader(cookieHeader: string | null): Promise<JobOpsServerSession> {
  if (!cookieHeader || !cookieHeader.includes(`${JOBOPS_SESSION_COOKIE_NAME}=`)) {
    return { isAuthenticated: false };
  }

  let config: Awaited<ReturnType<typeof getJobOpsApiServerConfig>>;
  try {
    config = await getJobOpsApiServerConfig();
  } catch {
    return { isAuthenticated: false };
  }

  if (!config.internalApiKey) {
    return { isAuthenticated: false };
  }

  try {
    const response = await fetch(`${config.apiBaseUrl.replace(/\/$/, "")}/v1/auth/me`, {
      cache: "no-store",
      headers: {
        Cookie: cookieHeader,
        "X-JobOps-Internal-Key": config.internalApiKey
      }
    });
    if (!response.ok) {
      return { isAuthenticated: false };
    }

    const payload = (await response.json()) as {
      ok?: boolean;
      result?: {
        user?: unknown;
        workspace?: unknown;
        candidateProfile?: unknown;
      };
    };
    if (!payload.ok || !payload.result?.user || !payload.result.workspace || !payload.result.candidateProfile) {
      return { isAuthenticated: false };
    }

    return {
      isAuthenticated: true,
      user: payload.result.user,
      workspace: payload.result.workspace,
      candidateProfile: payload.result.candidateProfile
    };
  } catch {
    return { isAuthenticated: false };
  }
}
