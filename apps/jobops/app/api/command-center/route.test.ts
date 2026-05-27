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
      JOBOPS_INTERNAL_API_KEY: "test-secret"
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
      active_workspace: "profile",
      client_context: {}
    });
    await expect(response.json()).resolves.toEqual({
      ok: true,
      result: fastApiPayload
    });
  });

  it("ignores explicit request candidate slugs because FastAPI owns workspace identity", async () => {
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
    expect(JSON.parse(String(init?.body)).candidate_profile_slug).toBeUndefined();
  });

  it("does not require a configured candidate slug", async () => {
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

    const response = await POST(
      new Request("http://next.test/api/command-center", {
        body: JSON.stringify({ command: "update switchboard's careers url to https://welcome.oneswitchboard.com/careers" }),
        headers: { "Content-Type": "application/json" },
        method: "POST"
      })
    );

    expect(fetchMock).toHaveBeenCalled();
    expect(response.status).toBe(200);
  });

  it("returns a safe JSON error when FastAPI responds with HTML", async () => {
    getJobOpsApiServerConfigMock.mockResolvedValueOnce({
      apiBaseUrl: "http://fastapi.test/",
      internalApiKey: "test-secret",
      JOBOPS_API_BASE_URL: "http://fastapi.test/",
      JOBOPS_INTERNAL_API_KEY: "test-secret"
    });
    const { POST } = await import("./route");
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response("<html><head><title>Service unavailable</title></head></html>", {
        headers: {
          "Content-Type": "text/html; charset=utf-8"
        },
        status: 502
      })
    );
    vi.stubGlobal("fetch", fetchMock);
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);

    const response = await POST(
      new Request("http://next.test/api/command-center", {
        body: JSON.stringify({
          command: "I pasted my resume.",
          activeWorkspace: "profile"
        }),
        headers: {
          "Content-Type": "application/json"
        },
        method: "POST"
      })
    );

    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toEqual({
      ok: false,
      error: "Command-center API returned an unexpected response. Please try again."
    });
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      "Command-center API returned a non-JSON response.",
      expect.objectContaining({
        bodyPreview: "<html><head><title>Service unavailable</title></head></html>",
        contentType: "text/html; charset=utf-8",
        requestPath: "/api/command-center",
        requestUrl: "http://fastapi.test/v1/command-center/commands",
        responseUrl: null,
        status: 502
      })
    );
  });

  it("proxies command-center stream responses from FastAPI", async () => {
    const { POST } = await import("./stream/route");
    const stream = new ReadableStream({
      start(controller) {
        const encoder = new TextEncoder();
        controller.enqueue(encoder.encode('{"type":"status","statusUpdate":{"stage":"router","message":"Routed."}}\n'));
        controller.enqueue(encoder.encode('{"type":"result","result":{"assistant_message":"Done.","actions":[]}}\n'));
        controller.close();
      }
    });
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response(stream, { headers: { "Content-Type": "application/x-ndjson" }, status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await POST(
      new Request("http://next.test/api/command-center/stream", {
        body: JSON.stringify({
          command: "I pasted my resume.",
          activeWorkspace: "profile"
        }),
        headers: {
          "Content-Type": "application/json",
          cookie: "jobops_session=test"
        },
        method: "POST"
      })
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toContain("application/x-ndjson");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("http://fastapi.test/v1/command-center/commands/stream");
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
    expect(init?.headers).toEqual(
      expect.objectContaining({
        Cookie: "jobops_session=test",
        "X-JobOps-Internal-Key": "test-secret"
      })
    );
    expect(await response.text()).toContain('"type":"status"');
  });

  it("returns a safe JSON error when the command-center stream upstream responds with HTML", async () => {
    const { POST } = await import("./stream/route");
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response("<html><body>Sign in required</body></html>", {
        headers: { "Content-Type": "text/html; charset=utf-8" },
        status: 200
      })
    );
    vi.stubGlobal("fetch", fetchMock);
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);

    const response = await POST(
      new Request("http://next.test/jobops/api/command-center/stream", {
        body: JSON.stringify({
          command: "I pasted my resume.",
          activeWorkspace: "profile"
        }),
        headers: {
          "Content-Type": "application/json",
          cookie: "jobops_session=test"
        },
        method: "POST"
      })
    );

    expect(response.status).toBe(502);
    expect(response.headers.get("content-type")).toContain("application/json");
    await expect(response.json()).resolves.toEqual({
      ok: false,
      error: "Command-center stream returned an unexpected response. Please try again."
    });
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      "Command-center stream API returned an unexpected response.",
      expect.objectContaining({
        bodyPreview: "<html><body>Sign in required</body></html>",
        contentType: "text/html; charset=utf-8",
        requestPath: "/jobops/api/command-center/stream",
        requestUrl: "http://fastapi.test/v1/command-center/commands/stream",
        responseUrl: null,
        status: 200
      })
    );
  });
});
