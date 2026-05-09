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
    expect(html).toContain("Dashboard");
  });

  it("renders primary navigation without auth assumptions", () => {
    const html = renderToStaticMarkup(
      <DashboardShell>
        <DashboardHome />
      </DashboardShell>
    );

    expect(html).toContain("Primary navigation");
    expect(html).toContain("Profile");
    expect(html).toContain("Jobs");
    expect(html).toContain("Fit Scoring");
    expect(html).not.toContain("Sign in");
    expect(html).not.toContain("Log in");
  });

  it("emphasizes the profile-first empty state", () => {
    const html = renderToStaticMarkup(<DashboardHome />);

    expect(html).toContain("Recommended first step");
    expect(html).toContain("Open profile workspace");
    expect(html).toContain("upload or paste a resume");
    expect(html).toContain("clarifying questions");
  });
});
