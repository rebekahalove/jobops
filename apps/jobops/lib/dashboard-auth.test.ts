import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";
import {
  DASHBOARD_AUTH_COOKIE_NAME,
  createDashboardAuthToken,
  gateDashboardRequest,
  type DashboardAuthEnvironment
} from "./dashboard-auth";

const configuredEnv: DashboardAuthEnvironment = {
  authDisabled: false,
  cookieSecret: "test-cookie-secret",
  isProduction: true,
  password: "test-password"
};

describe("dashboard auth gate", () => {
  it("redirects a protected dashboard path without a valid cookie", async () => {
    const response = await gateDashboardRequest(new NextRequest("http://next.test/jobops/applications"), {
      dashboardBasePath: "/jobops",
      env: configuredEnv,
      loginPath: "/jobops/login"
    });

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://next.test/jobops/login?returnTo=%2Fjobops%2Fapplications");
  });

  it("returns JSON 401 for protected API proxy paths without a valid cookie", async () => {
    const response = await gateDashboardRequest(new NextRequest("http://next.test/jobops/api/profile-draft"), {
      dashboardBasePath: "/jobops",
      env: configuredEnv,
      loginPath: "/jobops/login"
    });

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toEqual({
      ok: false,
      error: "JobOps dashboard authentication is required."
    });
  });

  it("lets authenticated requests reach protected dashboard paths", async () => {
    const token = await createDashboardAuthToken(configuredEnv.cookieSecret ?? "");
    const response = await gateDashboardRequest(
      new NextRequest("http://next.test/jobops/profile", {
        headers: {
          cookie: `${DASHBOARD_AUTH_COOKIE_NAME}=${token}`
        }
      }),
      {
        dashboardBasePath: "/jobops",
        env: configuredEnv,
        loginPath: "/jobops/login"
      }
    );

    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("leaves public portfolio paths unaffected", async () => {
    const response = await gateDashboardRequest(new NextRequest("http://next.test/"), {
      dashboardBasePath: "/jobops",
      env: configuredEnv,
      loginPath: "/jobops/login"
    });

    expect(response.headers.get("x-middleware-next")).toBe("1");
  });
});
