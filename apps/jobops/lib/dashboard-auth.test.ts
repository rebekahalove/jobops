import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";
import { JOBOPS_SESSION_COOKIE_NAME, gateDashboardRequest, type DashboardAuthEnvironment } from "./dashboard-auth";

const configuredEnv: DashboardAuthEnvironment = {
  authDisabled: false,
  isProduction: true
};

describe("dashboard auth gate", () => {
  it("redirects a protected dashboard path without a valid session", async () => {
    const response = await gateDashboardRequest(new NextRequest("http://next.test/jobops/applications"), {
      dashboardBasePath: "/jobops",
      env: configuredEnv,
      loginPath: "/jobops/login"
    });

    if (!response) {
      throw new Error("Expected dashboard gate response.");
    }
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://next.test/jobops/login?returnTo=%2Fjobops%2Fapplications");
  });

  it("returns JSON 401 for protected API proxy paths without a valid session", async () => {
    const response = await gateDashboardRequest(new NextRequest("http://next.test/jobops/api/profile-draft"), {
      dashboardBasePath: "/jobops",
      env: configuredEnv,
      loginPath: "/jobops/login"
    });

    if (!response) {
      throw new Error("Expected dashboard gate response.");
    }
    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toEqual({
      ok: false,
      error: "JobOps authentication is required."
    });
  });

  it("lets requests with a backend session reach protected dashboard paths", async () => {
    const response = await gateDashboardRequest(
      new NextRequest("http://next.test/jobops/profile", {
        headers: {
          cookie: `${JOBOPS_SESSION_COOKIE_NAME}=test-session-token`
        }
      }),
      {
        dashboardBasePath: "/jobops",
        env: configuredEnv,
        loginPath: "/jobops/login"
      }
    );

    expect(response).toBeUndefined();
  });

  it("leaves public portfolio paths unaffected", async () => {
    const response = await gateDashboardRequest(new NextRequest("http://next.test/"), {
      dashboardBasePath: "/jobops",
      env: configuredEnv,
      loginPath: "/jobops/login"
    });

    expect(response).toBeUndefined();
  });
});
