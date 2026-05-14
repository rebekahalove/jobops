import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../lib/server-env", () => ({
  getJobOpsServerEnv: vi.fn(async () => ({
    JOBOPS_API_BASE_URL: "http://fastapi.test/",
    JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG: "rebekah-love"
  }))
}));

describe("profile-draft API proxy", () => {
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
    const fetchMock = vi.fn(async (_input: RequestInfo | URL) => Response.json(fastApiPayload, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(new Request("http://next.test/api/profile-draft"));

    expect(fetchMock.mock.calls[0]?.[0]).toBe("http://fastapi.test/v1/command-center/profile-draft/rebekah-love");
    await expect(response.json()).resolves.toEqual(fastApiPayload);
  });
});
