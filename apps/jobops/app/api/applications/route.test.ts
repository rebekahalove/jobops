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

describe("applications API proxy", () => {
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

  it("includes the internal key when loading applications from FastAPI", async () => {
    const { GET } = await import("./route");
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      Response.json([], { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(new Request("http://next.test/api/applications"));

    const firstCall = fetchMock.mock.calls[0];
    expect(String(firstCall?.[0])).toBe("http://fastapi.test/v1/applications");
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

  it("fails safely when the server-side internal key is missing", async () => {
    getJobOpsApiServerConfigMock.mockRejectedValueOnce(new Error("missing key"));
    const { GET } = await import("./route");
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(new Request("http://next.test/api/applications"));

    expect(response.status).toBe(503);
    expect(fetchMock).not.toHaveBeenCalled();
    await expect(response.json()).resolves.toEqual({
      ok: false,
      error: "missing key"
    });
  });

  it("forwards materials generation requests with cookies and the internal key", async () => {
    const { POST } = await import("./[applicationId]/materials/generate/route");
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      Response.json({ ok: true, bundle: { id: "bundle-1" } }, { status: 201 })
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await POST(
      new Request("http://next.test/api/applications/app-1/materials/generate", {
        method: "POST",
        headers: { cookie: "jobops_session=test-token" }
      }),
      { params: Promise.resolve({ applicationId: "app-1" }) }
    );

    const firstCall = fetchMock.mock.calls[0];
    expect(String(firstCall?.[0])).toBe("http://fastapi.test/v1/applications/app-1/materials/generate");
    expect(firstCall?.[1]).toEqual(
      expect.objectContaining({
        cache: "no-store",
        method: "POST",
        headers: expect.objectContaining({
          "X-JobOps-Internal-Key": "test-secret",
          Cookie: "jobops_session=test-token"
        })
      })
    );
    expect(response.status).toBe(201);
    await expect(response.json()).resolves.toEqual({ ok: true, bundle: { id: "bundle-1" } });
  });

  it("returns structured JSON when a materials upstream response is not JSON", async () => {
    const { GET } = await import("./[applicationId]/materials/route");
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response("<html>bad gateway</html>", { status: 502, headers: { "Content-Type": "text/html" } })
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(new Request("http://next.test/api/applications/app-1/materials"), {
      params: Promise.resolve({ applicationId: "app-1" })
    });

    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toEqual(
      expect.objectContaining({
        ok: false,
        error: "JobOps API request failed with HTTP 502.",
        upstreamBodyPreview: "<html>bad gateway</html>"
      })
    );
  });

  it("forwards requirements extraction requests with cookies and the internal key", async () => {
    const { POST } = await import("./[applicationId]/requirements/extract/route");
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      Response.json({ id: "extract-1", extraction_status: "succeeded" }, { status: 201 })
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await POST(
      new Request("http://next.test/api/applications/app-1/requirements/extract", {
        method: "POST",
        headers: { cookie: "jobops_session=test-token" }
      }),
      { params: Promise.resolve({ applicationId: "app-1" }) }
    );

    const firstCall = fetchMock.mock.calls[0];
    expect(String(firstCall?.[0])).toBe("http://fastapi.test/v1/applications/app-1/requirements/extract");
    expect(firstCall?.[1]).toEqual(
      expect.objectContaining({
        cache: "no-store",
        method: "POST",
        headers: expect.objectContaining({
          "X-JobOps-Internal-Key": "test-secret",
          Cookie: "jobops_session=test-token"
        })
      })
    );
    expect(response.status).toBe(201);
    await expect(response.json()).resolves.toEqual({ id: "extract-1", extraction_status: "succeeded" });
  });
});
