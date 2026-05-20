import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../../lib/server-env", () => ({
  getJobOpsApiServerConfig: vi.fn(async () => ({
    apiBaseUrl: "http://api.test",
    internalApiKey: "test-internal-key"
  }))
}));

describe("dashboard auth login route", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("sets the backend session cookie after a known username login", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("{}", {
        headers: {
          "Set-Cookie": "jobops_session=test-session; Max-Age=43200; Path=/; SameSite=Lax; HttpOnly; Secure"
        },
        status: 200
      })
    );
    const { POST } = await import("./route");

    const response = await POST(
      new Request("http://next.test/jobops/api/dashboard-auth/login", {
        body: new URLSearchParams({
          username: "rebekah-love",
          password: "test-password",
          returnTo: "/jobops/applications"
        }),
        headers: {
          "Content-Type": "application/x-www-form-urlencoded"
        },
        method: "POST"
      })
    );

    const setCookie = response.headers.get("set-cookie") ?? "";
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("/jobops/applications");
    expect(setCookie).toContain("jobops_session=test-session");
    expect(setCookie).toContain("HttpOnly");
    expect(setCookie).toContain("SameSite=Lax");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://api.test/v1/auth/session",
      expect.objectContaining({
        body: JSON.stringify({ username: "rebekah-love", password: "test-password" })
      })
    );
  });

  it("does not create a backend session without a username", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));
    const { POST } = await import("./route");

    const response = await POST(
      new Request("http://next.test/jobops/api/dashboard-auth/login", {
        body: new URLSearchParams({
          returnTo: "/jobops/applications"
        }),
        headers: {
          "Content-Type": "application/x-www-form-urlencoded"
        },
        method: "POST"
      })
    );

    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("/jobops/login?error=1&returnTo=%2Fjobops%2Fapplications");
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("does not create a backend session without a password", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));
    const { POST } = await import("./route");

    const response = await POST(
      new Request("http://next.test/jobops/api/dashboard-auth/login", {
        body: new URLSearchParams({
          username: "rebekah-love",
          returnTo: "/jobops/applications"
        }),
        headers: {
          "Content-Type": "application/x-www-form-urlencoded"
        },
        method: "POST"
      })
    );

    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("/jobops/login?error=1&returnTo=%2Fjobops%2Fapplications");
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("fails loudly when the backend session cannot be created", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Internal API key is required." }), {
        headers: {
          "Content-Type": "application/json"
        },
        status: 401
      })
    );
    const { POST } = await import("./route");

    const response = await POST(
      new Request("http://next.test/jobops/api/dashboard-auth/login", {
        body: new URLSearchParams({
          username: "rebekah-love",
          password: "test-password",
          returnTo: "/jobops/applications"
        }),
        headers: {
          "Content-Type": "application/x-www-form-urlencoded"
        },
        method: "POST"
      })
    );

    expect(response.status).toBe(503);
    expect(response.headers.get("set-cookie")).toBeNull();
    await expect(response.json()).resolves.toEqual({
      ok: false,
      error: "JobOps backend session could not be created: Internal API key is required."
    });
  });

  it("redirects back to login when the username is unknown", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "No active JobOps user exists for that username." }), {
        headers: {
          "Content-Type": "application/json"
        },
        status: 404
      })
    );
    const { POST } = await import("./route");

    const response = await POST(
      new Request("http://next.test/jobops/api/dashboard-auth/login", {
        body: new URLSearchParams({
          username: "unknown-user",
          password: "test-password",
          returnTo: "/jobops/applications"
        }),
        headers: {
          "Content-Type": "application/x-www-form-urlencoded"
        },
        method: "POST"
      })
    );

    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("/jobops/login?error=1&returnTo=%2Fjobops%2Fapplications");
    expect(response.headers.get("set-cookie")).toBeNull();
  });
});
