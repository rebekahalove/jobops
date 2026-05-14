import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { DashboardHome } from "./dashboard-home";
import { DashboardShell } from "./dashboard-shell";

describe("JobOps dashboard shell", () => {
  it("renders the dashboard app shell", () => {
    const html = renderToStaticMarkup(
      <DashboardShell>
        <DashboardHome />
      </DashboardShell>
    );

    expect(html).toContain("JobOps");
    expect(html).toContain("AI command center");
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

  it("presents the command-center plus workspace model", () => {
    const html = renderToStaticMarkup(<DashboardHome />);

    expect(html).toContain("One command center, structured workspaces underneath.");
    expect(html).toContain("Open workspace");
    expect(html).toContain("Watched companies");
    expect(html).toContain("Manual application tracking is available now");
  });
});
