import React from "react";
import { readFile } from "node:fs/promises";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DashboardHome } from "./dashboard-home";
import { DashboardShell } from "./dashboard-shell";

let mockPathname = "/applications";

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname
}));

describe("JobOps dashboard shell", () => {
  beforeEach(() => {
    mockPathname = "/applications";
  });

  it("renders the dashboard app shell", () => {
    const html = renderToStaticMarkup(
      <DashboardShell>
        <DashboardHome />
      </DashboardShell>
    );

    expect(html).toContain("JobOps");
    expect(html).toContain("AI command center");
    expect(html).toContain("Log out");
    expect(html).toContain('action="/api/dashboard-auth/logout"');
    expect(html).not.toContain("No recent job discovery diagnostics yet.");
    expect(html).toContain("JobOps alpha · dev · build local");
  });

  it("does not redirect to login on transient session-check failures", async () => {
    const source = await readFile(new URL("./dashboard-shell.tsx", import.meta.url), "utf-8");

    expect(source).toContain("response.status !== 401 && response.status !== 403");
    expect(source).toContain("redirectToLogin(basePath, pathname)");
  });

  it("renders workspace tabs without auth assumptions", () => {
    const html = renderToStaticMarkup(
      <DashboardShell>
        <DashboardHome />
      </DashboardShell>
    );

    expect(html).toContain("Workspace tabs");
    expect(html).toContain("Profile");
    expect(html).toContain("Companies");
    expect(html).toContain("Jobs");
    expect(html).toContain("Applications");
    expect(html).toContain("Materials");
    expect(html).toContain("Follow-ups");
    expect(html).not.toContain("Sign in");
    expect(html).not.toContain("Log in");
  });

  it("keeps Profile and Applications accessible from the shell", () => {
    const html = renderToStaticMarkup(
      <DashboardShell>
        <DashboardHome />
      </DashboardShell>
    );

    expect(html).toContain('href="/profile"');
    expect(html).toContain('href="/applications"');
  });

  it("shows the Admin navigation link only for admin users", () => {
    const normalHtml = renderToStaticMarkup(
      <DashboardShell>
        <DashboardHome />
      </DashboardShell>
    );
    const adminHtml = renderToStaticMarkup(
      <DashboardShell isAdmin>
        <DashboardHome />
      </DashboardShell>
    );

    expect(normalHtml).not.toContain('href="/admin/users"');
    expect(adminHtml).toContain('href="/admin/users"');
    expect(adminHtml).toContain("Admin");
  });

  it("can enable the Admin navigation link for the mounted JobOps dashboard", () => {
    const mountedHtml = renderToStaticMarkup(
      <DashboardShell apiBasePath="/jobops/api" basePath="/jobops" enableAdminNav isAdmin>
        <DashboardHome />
      </DashboardShell>
    );
    const defaultMountedHtml = renderToStaticMarkup(
      <DashboardShell apiBasePath="/jobops/api" basePath="/jobops" isAdmin>
        <DashboardHome />
      </DashboardShell>
    );

    expect(mountedHtml).toContain('href="/jobops/admin/users"');
    expect(defaultMountedHtml).not.toContain('href="/jobops/admin/users"');
  });

  it("renders the mounted JobOps command center with mounted workspace routes", () => {
    mockPathname = "/jobops/jobs";
    const html = renderToStaticMarkup(
      <DashboardShell apiBasePath="/jobops/api" basePath="/jobops" enableAdminNav>
        <DashboardHome basePath="/jobops" />
      </DashboardShell>
    );

    expect(html).toContain("AI command center");
    expect(html).toContain("Ask JobOps to work across your search.");
    expect(html).toContain("Show examples");
    expect(html).toContain('href="/jobops/jobs"');
    expect(html).toContain('action="/jobops/api/dashboard-auth/logout"');
  });

  it("marks the current workspace tab as active", () => {
    const html = renderToStaticMarkup(
      <DashboardShell>
        <DashboardHome />
      </DashboardShell>
    );

    expect(html).toContain('href="/applications"');
    expect(html).toContain('aria-current="page"');
    expect(html).toContain('class="workspace-tab active"');
  });

  it("renders account settings outside the command center workspace chrome", () => {
    mockPathname = "/account";
    const html = renderToStaticMarkup(
      <DashboardShell>
        <main className="dashboard-main account-settings-page">
          <h2>Manage your JobOps alpha account.</h2>
        </main>
      </DashboardShell>
    );

    expect(html).toContain("Manage your JobOps alpha account.");
    expect(html).toContain('href="/account"');
    expect(html).toContain("Log out");
    expect(html).not.toContain("Workspace tabs");
    expect(html).not.toContain("Active workspace content");
  });

  it("renders admin pages outside the command center workspace chrome", () => {
    mockPathname = "/admin/users";
    const html = renderToStaticMarkup(
      <DashboardShell isAdmin>
        <main className="admin-users-page">
          <h1>Manage Users</h1>
        </main>
      </DashboardShell>
    );

    expect(html).toContain("Manage Users");
    expect(html).toContain('href="/admin/users"');
    expect(html).toContain("Log out");
    expect(html).not.toContain("Workspace tabs");
    expect(html).not.toContain("Active workspace content");
  });

  it("presents the command-center plus workspace model", () => {
    const html = renderToStaticMarkup(<DashboardHome />);

    expect(html).toContain("One command center, structured workspaces underneath.");
    expect(html).toContain("Open workspace");
    expect(html).toContain("Watched companies");
    expect(html).toContain("Manual application tracking is available now");
  });
});
