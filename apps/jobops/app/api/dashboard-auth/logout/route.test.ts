import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../../lib/server-env", () => ({
  getJobOpsApiServerConfig: vi.fn(async () => ({
    apiBaseUrl: "http://api.test",
    internalApiKey: "test-internal-key"
  }))
}));

describe("dashboard auth logout route", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("revokes the backend session before clearing the browser cookie", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));
    const { POST } = await import("./route");

    const response = await POST(
      new Request("http://next.test/jobops/api/dashboard-auth/logout", {
        headers: {
          Cookie: "other=value; jobops_session=session-token; theme=light"
        },
        method: "POST"
      })
    );

    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("/jobops/login");
    expect(response.headers.get("set-cookie")).toContain("jobops_session=; Max-Age=0");
    expect(globalThis.fetch).toHaveBeenCalledWith("http://api.test/v1/auth/logout", {
      method: "POST",
      headers: {
        Cookie: "jobops_session=session-token",
        "X-JobOps-Internal-Key": "test-internal-key"
      }
    });
  });

  it("clears the browser cookie even when backend revoke fails", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("backend down"));
    const { GET } = await import("./route");

    const response = await GET(
      new Request("http://next.test/api/dashboard-auth/logout", {
        headers: {
          Cookie: "jobops_session=session-token"
        }
      })
    );

    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("/login");
    expect(response.headers.get("set-cookie")).toContain("jobops_session=; Max-Age=0");
  });
});
