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

describe("profile-draft API proxy", () => {
  beforeEach(() => {
    getJobOpsApiServerConfigMock.mockResolvedValue({
      apiBaseUrl: "http://fastapi.test/",
      internalApiKey: "test-secret",
      JOBOPS_API_BASE_URL: "http://fastapi.test/",
      JOBOPS_INTERNAL_API_KEY: "test-secret"
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it("loads the latest saved profile draft from FastAPI", async () => {
    const { GET } = await import("./route");
    const fastApiPayload = {
      ok: true,
      result: {
        assistantMessage: "",
        targetRoleIntent: {},
        draftFacts: [],
        skillClaims: [],
        experienceAndProjects: [],
        evidenceLinks: [],
        clarifyingQuestions: [],
        changeSummary: [],
        statusSummary: "No profile intake draft has been saved yet."
      }
    };
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      Response.json(fastApiPayload, { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(new Request("http://next.test/api/profile-draft"));

    expect(fetchMock.mock.calls[0]?.[0]).toBe("http://fastapi.test/v1/command-center/profile-draft/current");
    expect(fetchMock.mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({
        headers: expect.objectContaining({
          "X-JobOps-Internal-Key": "test-secret"
        })
      })
    );
    await expect(response.json()).resolves.toEqual(fastApiPayload);
  });

  it("ignores a candidateProfileSlug query and uses the authenticated session", async () => {
    const { GET } = await import("./route");
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      Response.json({ ok: true, result: {} }, { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(new Request("http://next.test/api/profile-draft?candidateProfileSlug="));

    expect(response.status).toBe(200);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("http://fastapi.test/v1/command-center/profile-draft/current");
  });

  it("does not require a configured candidate slug", async () => {
    getJobOpsApiServerConfigMock.mockResolvedValueOnce({
      apiBaseUrl: "http://fastapi.test/",
      internalApiKey: "test-secret",
      JOBOPS_API_BASE_URL: "http://fastapi.test/",
      JOBOPS_INTERNAL_API_KEY: "test-secret"
    });
    const { GET } = await import("./route");
    const fetchMock = vi.fn(async () => Response.json({ ok: true, result: {} }, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(new Request("http://next.test/api/profile-draft?candidateProfileSlug="));

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalled();
  });
});
