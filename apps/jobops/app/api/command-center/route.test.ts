import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getJobOpsApiServerConfigMock = vi.hoisted(() => vi.fn());
const requireJobOpsServerEnvValueMock = vi.hoisted(() =>
  vi.fn((env: Record<string, string | undefined>, key: string) => {
    const value = env[key]?.trim();
    if (!value) {
      throw new Error(`${key} is required for this JobOps server route.`);
    }
    return value;
  })
);

vi.mock("../../../lib/server-env", () => ({
  getJobOpsApiServerConfig: getJobOpsApiServerConfigMock,
  requireJobOpsServerEnvValue: requireJobOpsServerEnvValueMock
}));

describe("command-center API proxy", () => {
  beforeEach(() => {
    getJobOpsApiServerConfigMock.mockResolvedValue({
      apiBaseUrl: "http://fastapi.test/",
      internalApiKey: "test-secret",
      JOBOPS_API_BASE_URL: "http://fastapi.test/",
      JOBOPS_INTERNAL_API_KEY: "test-secret",
      JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG: "configured-profile"
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it("forwards valid UI commands to the FastAPI command-center endpoint", async () => {
    const { POST } = await import("./route");
    const fastApiPayload = {
      assistant_message: "I updated your profile draft.",
      actions: [
        {
          type: "profile_intake",
          status: "completed",
          targetWorkspace: "profile",
          title: "Update profile",
          summary: "Updated the saved profile draft."
        }
      ],
      target_workspace: "profile",
      result_payload: {
        profileDraft: {
          assistantMessage: "I updated your profile draft.",
          targetRoleIntent: {
            targetTitles: "Applied AI Engineer"
          },
          draftFacts: [],
          skillClaims: [],
          experienceAndProjects: [],
          evidenceLinks: [],
          clarifyingQuestions: [],
          changeSummary: []
        }
      }
    };
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      Response.json(fastApiPayload, { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await POST(
      new Request("http://next.test/api/command-center", {
        body: JSON.stringify({
          command: "I want to be an Applied AI Engineer.",
          activeWorkspace: "profile"
        }),
        headers: {
          "Content-Type": "application/json"
        },
        method: "POST"
      })
    );

    const firstCall = fetchMock.mock.calls[0];
    expect(firstCall?.[0]).toBe("http://fastapi.test/v1/command-center/commands");
    const init = firstCall?.[1] as RequestInit | undefined;
    expect(init?.headers).toEqual(
      expect.objectContaining({
        "Content-Type": "application/json",
        "X-JobOps-Internal-Key": "test-secret"
      })
    );
    expect(JSON.parse(String(init?.body))).toEqual({
      command: "I want to be an Applied AI Engineer.",
      candidate_profile_slug: "configured-profile",
      active_workspace: "profile",
      client_context: {}
    });
    await expect(response.json()).resolves.toEqual({
      ok: true,
      result: fastApiPayload
    });
  });

  it("uses an explicit request candidate slug even when no default slug is configured", async () => {
    getJobOpsApiServerConfigMock.mockResolvedValueOnce({
      apiBaseUrl: "http://fastapi.test/",
      internalApiKey: "test-secret",
      JOBOPS_API_BASE_URL: "http://fastapi.test/",
      JOBOPS_INTERNAL_API_KEY: "test-secret"
    });
    const { POST } = await import("./route");
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      Response.json({ assistant_message: "ok", actions: [] }, { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);

    await POST(
      new Request("http://next.test/api/command-center", {
        body: JSON.stringify({
          command: "Find companies",
          candidateProfileSlug: "request-profile"
        }),
        headers: { "Content-Type": "application/json" },
        method: "POST"
      })
    );

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
    expect(JSON.parse(String(init?.body)).candidate_profile_slug).toBe("request-profile");
  });

  it("returns a clear config error when no request or configured candidate slug is available", async () => {
    getJobOpsApiServerConfigMock.mockResolvedValueOnce({
      apiBaseUrl: "http://fastapi.test/",
      internalApiKey: "test-secret",
      JOBOPS_API_BASE_URL: "http://fastapi.test/",
      JOBOPS_INTERNAL_API_KEY: "test-secret"
    });
    const { POST } = await import("./route");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await POST(
      new Request("http://next.test/api/command-center", {
        body: JSON.stringify({ command: "update switchboard's careers url to https://welcome.oneswitchboard.com/careers" }),
        headers: { "Content-Type": "application/json" },
        method: "POST"
      })
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      ok: false,
      error: "JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG is required for this JobOps server route."
    });
  });
});
