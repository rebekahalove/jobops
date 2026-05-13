import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../lib/server-env", () => ({
  getJobOpsServerEnv: vi.fn(async () => ({
    JOBOPS_API_BASE_URL: "http://fastapi.test/",
    JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG: "rebekah-love"
  }))
}));

describe("profile-intake API proxy", () => {
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
    expect(JSON.parse(String(init?.body))).toEqual({
      latest_user_message: "I want to be an Applied AI Engineer.",
      existing_draft: {
        facts: []
      },
      candidate_profile_slug: "rebekah-love"
    });
    await expect(response.json()).resolves.toEqual(fastApiPayload);
  });
});
