import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { JOBOPS_SESSION_COOKIE_NAME, gateDashboardRequest, type DashboardAuthEnvironment } from "./dashboard-auth";

const configuredEnv: DashboardAuthEnvironment = {
  authDisabled: false,
  isProduction: true
};

describe("dashboard auth gate", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete process.env.JOBOPS_API_BASE_URL;
    delete process.env.JOBOPS_INTERNAL_API_KEY;
  });

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

  it("returns JSON 401 for protected API proxy paths with a stale session instead of redirecting to login HTML", async () => {
    process.env.JOBOPS_API_BASE_URL = "http://api.test";
    process.env.JOBOPS_INTERNAL_API_KEY = "test-internal-key";
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "JobOps authentication is required." }), { status: 401 })
    );

    const response = await gateDashboardRequest(
      new NextRequest("http://next.test/jobops/api/command-center", {
        headers: {
          cookie: `${JOBOPS_SESSION_COOKIE_NAME}=stale-session-token`
        }
      }),
      {
        dashboardBasePath: "/jobops",
        env: configuredEnv,
        loginPath: "/jobops/login"
      }
    );

    if (!response) {
      throw new Error("Expected dashboard gate response.");
    }
    expect(response.status).toBe(401);
    expect(response.headers.get("location")).toBeNull();
    expect(response.headers.get("set-cookie")).toContain(`${JOBOPS_SESSION_COOKIE_NAME}=; Max-Age=0`);
    await expect(response.json()).resolves.toEqual({
      ok: false,
      error: "JobOps authentication is required."
    });
  });

  it("redirects an unauthenticated dashboard landing path to the public about page", async () => {
    const response = await gateDashboardRequest(new NextRequest("http://next.test/jobops"), {
      dashboardBasePath: "/jobops",
      env: configuredEnv,
      loginPath: "/jobops/login"
    });

    if (!response) {
      throw new Error("Expected dashboard gate response.");
    }
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://next.test/jobops/about");
  });

  it("lets public info and public API routes through without a session", async () => {
    const aboutResponse = await gateDashboardRequest(new NextRequest("http://next.test/jobops/about"), {
      dashboardBasePath: "/jobops",
      env: configuredEnv,
      loginPath: "/jobops/login"
    });
    const apiResponse = await gateDashboardRequest(new NextRequest("http://next.test/jobops/api/public/jobops/metrics"), {
      dashboardBasePath: "/jobops",
      env: configuredEnv,
      loginPath: "/jobops/login"
    });

    expect(aboutResponse).toBeUndefined();
    expect(apiResponse).toBeUndefined();
  });

  it("lets the standalone accept-invite flow through without a session", async () => {
    const pageResponse = await gateDashboardRequest(new NextRequest("http://next.test/accept-invite?token=test"), {
      dashboardBasePath: "",
      env: configuredEnv,
      loginPath: "/login"
    });
    const apiResponse = await gateDashboardRequest(new NextRequest("http://next.test/api/invitations/accept"), {
      dashboardBasePath: "",
      env: configuredEnv,
      loginPath: "/login"
    });

    expect(pageResponse).toBeUndefined();
    expect(apiResponse).toBeUndefined();
  });

  it("lets requests with a backend session reach protected dashboard paths", async () => {
    process.env.JOBOPS_API_BASE_URL = "http://api.test";
    process.env.JOBOPS_INTERNAL_API_KEY = "test-internal-key";
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));

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
    expect(globalThis.fetch).toHaveBeenCalledWith("http://api.test/v1/auth/me", {
      cache: "no-store",
      headers: {
        Cookie: `${JOBOPS_SESSION_COOKIE_NAME}=test-session-token`,
        "X-JobOps-Internal-Key": "test-internal-key"
      }
    });
  });

  it("redirects protected dashboard paths when a stale backend session cookie is present", async () => {
    process.env.JOBOPS_API_BASE_URL = "http://api.test";
    process.env.JOBOPS_INTERNAL_API_KEY = "test-internal-key";
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "JobOps authentication is required." }), { status: 401 }));

    const response = await gateDashboardRequest(
      new NextRequest("http://next.test/jobops/applications", {
        headers: {
          cookie: `${JOBOPS_SESSION_COOKIE_NAME}=stale-session-token`
        }
      }),
      {
        dashboardBasePath: "/jobops",
        env: configuredEnv,
        loginPath: "/jobops/login"
      }
    );

    if (!response) {
      throw new Error("Expected dashboard gate response.");
    }
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://next.test/jobops/login?returnTo=%2Fjobops%2Fapplications");
    expect(response.headers.get("set-cookie")).toContain(`${JOBOPS_SESSION_COOKIE_NAME}=; Max-Age=0`);
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
