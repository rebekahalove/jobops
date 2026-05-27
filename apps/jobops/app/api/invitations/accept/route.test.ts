import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../../lib/server-env", () => ({
  getJobOpsApiServerConfig: vi.fn(async () => ({
    apiBaseUrl: "http://api.test",
    internalApiKey: "test-internal-key"
  }))
}));

describe("invitation accept route", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("redirects with a relative mounted path after accepting an invite", async () => {
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
      new Request("http://rebekahalove.dev/jobops/api/invitations/accept", {
        body: new URLSearchParams({
          token: "test-token-with-enough-length-1234567890",
          username: "new-user",
          displayName: "New User",
          password: "new secure password"
        }),
        headers: {
          "Content-Type": "application/x-www-form-urlencoded"
        },
        method: "POST"
      })
    );

    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("/jobops");
    expect(response.headers.get("location")).not.toContain("http://");
    expect(response.headers.get("set-cookie")).toContain("jobops_session=test-session");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://api.test/v1/invitations/accept",
      expect.objectContaining({
        body: JSON.stringify({
          token: "test-token-with-enough-length-1234567890",
          username: "new-user",
          display_name: "New User",
          password: "new secure password"
        })
      })
    );
  });
});
