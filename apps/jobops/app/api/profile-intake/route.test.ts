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

describe("profile-intake API proxy", () => {
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

  it("forwards valid UI requests to the FastAPI profile-intake endpoint", async () => {
    const { POST } = await import("./route");
    const fastApiPayload = {
      ok: true,
      result: {
        assistantMessage: "I drafted updates.",
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
    };
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      Response.json(fastApiPayload, { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await POST(
      new Request("http://next.test/api/profile-intake", {
        body: JSON.stringify({
          latestUserMessage: "I want to be an Applied AI Engineer.",
          existingDraft: {
            facts: []
          }
        }),
        headers: {
          "Content-Type": "application/json"
        },
        method: "POST"
      })
    );

    const firstCall = fetchMock.mock.calls[0];
    expect(firstCall?.[0]).toBe("http://fastapi.test/v1/profile-intake/extract");
    expect(firstCall?.[1]).toEqual(
      expect.objectContaining({
        method: "POST"
      })
    );
    const init = firstCall?.[1] as RequestInit | undefined;
    expect(init?.headers).toEqual(
      expect.objectContaining({
        "Content-Type": "application/json",
        "X-JobOps-Internal-Key": "test-secret"
      })
    );
    expect(JSON.parse(String(init?.body))).toEqual({
      latest_user_message: "I want to be an Applied AI Engineer.",
      existing_draft: {
        facts: []
      },
      candidate_profile_slug: "configured-profile"
    });
    await expect(response.json()).resolves.toEqual(fastApiPayload);
  });

  it("fails safely when the server-side internal key is missing", async () => {
    getJobOpsApiServerConfigMock.mockRejectedValueOnce(new Error("missing key"));
    const { POST } = await import("./route");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await POST(
      new Request("http://next.test/api/profile-intake", {
        body: JSON.stringify({
          latestUserMessage: "I want to be an Applied AI Engineer."
        }),
        headers: {
          "Content-Type": "application/json"
        },
        method: "POST"
      })
    );

    expect(response.status).toBe(503);
    expect(fetchMock).not.toHaveBeenCalled();
    await expect(response.json()).resolves.toEqual({
      ok: false,
      error: "missing key"
    });
  });
});
