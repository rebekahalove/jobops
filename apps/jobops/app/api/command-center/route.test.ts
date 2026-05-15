import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getJobOpsApiServerConfigMock = vi.hoisted(() => vi.fn());

vi.mock("../../../lib/server-env", () => ({
  getJobOpsApiServerConfig: getJobOpsApiServerConfigMock
}));

describe("command-center API proxy", () => {
  beforeEach(() => {
    getJobOpsApiServerConfigMock.mockResolvedValue({
      apiBaseUrl: "http://fastapi.test/",
      internalApiKey: "test-secret",
      JOBOPS_API_BASE_URL: "http://fastapi.test/",
      JOBOPS_INTERNAL_API_KEY: "test-secret",
      JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG: "rebekah-love"
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
      candidate_profile_slug: "rebekah-love",
      active_workspace: "profile",
      client_context: {}
    });
    await expect(response.json()).resolves.toEqual({
      ok: true,
      result: fastApiPayload
    });
  });
});
