import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getJobOpsApiServerConfigMock = vi.hoisted(() => vi.fn());

vi.mock("../../../lib/server-env", () => ({
  getJobOpsApiServerConfig: getJobOpsApiServerConfigMock
}));

describe("jobs API proxy", () => {
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

  it("forwards unfavorite requests to the exact FastAPI unfavorite action", async () => {
    const { POST } = await import("./[savedJobId]/unfavorite/route");
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      Response.json({ ok: true, job: { id: "saved-job-1", status: "new" } }, { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await POST(
      new Request("http://next.test/api/jobs/saved-job-1/unfavorite", {
        method: "POST",
        headers: { cookie: "jobops_session=test-token" }
      }),
      { params: Promise.resolve({ savedJobId: "saved-job-1" }) }
    );

    const firstCall = fetchMock.mock.calls[0];
    expect(String(firstCall?.[0])).toBe("http://fastapi.test/v1/jobs/saved-job-1/unfavorite");
    expect(firstCall?.[1]).toEqual(
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "X-JobOps-Internal-Key": "test-secret",
          Cookie: "jobops_session=test-token"
        })
      })
    );
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ ok: true, job: { id: "saved-job-1", status: "new" } });
  });
});
