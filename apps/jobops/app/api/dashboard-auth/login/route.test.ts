import { afterEach, describe, expect, it, vi } from "vitest";
import { DASHBOARD_AUTH_COOKIE_NAME } from "../../../../lib/dashboard-auth";

describe("dashboard auth login route", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("sets an HttpOnly auth cookie after the correct password", async () => {
    vi.stubEnv("APP_ENV", "prod");
    vi.stubEnv("JOBOPS_DASHBOARD_COOKIE_SECRET", "test-cookie-secret");
    vi.stubEnv("JOBOPS_DASHBOARD_PASSWORD", "correct-password");
    const { POST } = await import("./route");

    const response = await POST(
      new Request("http://next.test/jobops/api/dashboard-auth/login", {
        body: new URLSearchParams({
          password: "correct-password",
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
    expect(response.headers.get("location")).toBe("http://next.test/jobops/applications");
    expect(setCookie).toContain(`${DASHBOARD_AUTH_COOKIE_NAME}=`);
    expect(setCookie).toContain("HttpOnly");
    expect(setCookie).toContain("SameSite=lax");
    expect(setCookie).toContain("Secure");
    expect(setCookie).not.toContain("correct-password");
  });

  it("does not set an auth cookie after an incorrect password", async () => {
    vi.stubEnv("JOBOPS_DASHBOARD_COOKIE_SECRET", "test-cookie-secret");
    vi.stubEnv("JOBOPS_DASHBOARD_PASSWORD", "correct-password");
    const { POST } = await import("./route");

    const response = await POST(
      new Request("http://next.test/jobops/api/dashboard-auth/login", {
        body: new URLSearchParams({
          password: "wrong-password",
          returnTo: "/jobops/applications"
        }),
        headers: {
          "Content-Type": "application/x-www-form-urlencoded"
        },
        method: "POST"
      })
    );

    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe(
      "http://next.test/jobops/login?error=1&returnTo=%2Fjobops%2Fapplications"
    );
    expect(response.headers.get("set-cookie")).toBeNull();
  });
});
