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

  it("returns JSON 401 for mounted command-center stream requests without a valid session", async () => {
    const response = await gateDashboardRequest(new NextRequest("http://next.test/jobops/api/command-center/stream"), {
      dashboardBasePath: "/jobops",
      env: configuredEnv,
      loginPath: "/jobops/login"
    });

    if (!response) {
      throw new Error("Expected dashboard gate response.");
    }
    expect(response.status).toBe(401);
    expect(response.headers.get("content-type")).toContain("application/json");
    await expect(response.json()).resolves.toEqual({
      ok: false,
      error: "JobOps authentication is required."
    });
  });

  it("lets protected API proxy paths with a session cookie reach FastAPI auth", async () => {
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

    expect(response).toBeUndefined();
    expect(globalThis.fetch).not.toHaveBeenCalled();
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

  it("lets the mounted accept-invite flow through without a session", async () => {
    const pageResponse = await gateDashboardRequest(new NextRequest("http://next.test/jobops/accept-invite?token=test"), {
      dashboardBasePath: "/jobops",
      env: configuredEnv,
      loginPath: "/jobops/login"
    });
    const apiResponse = await gateDashboardRequest(new NextRequest("http://next.test/jobops/api/invitations/accept"), {
      dashboardBasePath: "/jobops",
      env: configuredEnv,
      loginPath: "/jobops/login"
    });

    expect(pageResponse).toBeUndefined();
    expect(apiResponse).toBeUndefined();
  });

  it("lets dashboard page refreshes with a session cookie through without backend validation", async () => {
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
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("lets dashboard page refreshes with a stale session cookie reach the page shell", async () => {
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

    expect(response).toBeUndefined();
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("does not perform backend validation in middleware for protected API proxy paths", async () => {
    process.env.JOBOPS_API_BASE_URL = "http://api.test";
    process.env.JOBOPS_INTERNAL_API_KEY = "test-internal-key";
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));

    const response = await gateDashboardRequest(
      new NextRequest("http://next.test/jobops/api/profile-draft", {
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
    expect(globalThis.fetch).not.toHaveBeenCalled();
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
