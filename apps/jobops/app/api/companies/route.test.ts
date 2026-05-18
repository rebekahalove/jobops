import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getJobOpsApiServerConfigMock = vi.hoisted(() => vi.fn());

vi.mock("../../../lib/server-env", () => ({
  getJobOpsApiServerConfig: getJobOpsApiServerConfigMock
}));

describe("companies API proxy", () => {
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

  it("includes the internal key when loading companies from FastAPI", async () => {
    const { GET } = await import("./route");
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => Response.json([], { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET();

    const firstCall = fetchMock.mock.calls[0];
    expect(String(firstCall?.[0])).toBe("http://fastapi.test/v1/companies?candidate_profile_slug=rebekah-love");
    expect(firstCall?.[1]).toEqual(
      expect.objectContaining({
        cache: "no-store",
        headers: expect.objectContaining({
          "X-JobOps-Internal-Key": "test-secret"
        })
      })
    );
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual([]);
  });
});
