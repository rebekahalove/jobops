import React from "react";
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
    expect(html).toContain("JobOps alpha · dev · build local");
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

  it("presents the command-center plus workspace model", () => {
    const html = renderToStaticMarkup(<DashboardHome />);

    expect(html).toContain("One command center, structured workspaces underneath.");
    expect(html).toContain("Open workspace");
    expect(html).toContain("Watched companies");
    expect(html).toContain("Manual application tracking is available now");
  });
});
