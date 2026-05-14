import React from "react";
import { readFile } from "node:fs/promises";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AiCommandCenter, starterPrompts } from "./ai-command-center";
import {
  classifyCommand,
  createPlannedAction,
  workspaceRoutes,
  type PlannedCommandAction,
  type WorkspaceTab
} from "../lib/command-center-actions";

describe("AI command center", () => {
  it("renders prominently with starter prompts", () => {
    const html = renderToStaticMarkup(<AiCommandCenter />);

    expect(html).toContain("AI command center");
    expect(html).toContain("Ask JobOps to work across your search.");
    expect(html).toContain("Here&#x27;s a job URL. Add it to my jobs list.");
    for (const prompt of starterPrompts.slice(1)) {
      expect(html).toContain(prompt);
    }
  });

  it("creates a planned action card from a submitted command plan", () => {
    const plannedAction = createPlannedAction("Here's a job URL. Add it to my jobs list.", "action-test");
    const html = renderToStaticMarkup(<AiCommandCenter initialActions={[plannedAction]} />);

    expect(plannedAction).toMatchObject({
      type: "add_job_from_url",
      status: "planned",
      targetWorkspace: "jobs"
    });
    expect(html).toContain("Add job from URL");
    expect(html).toContain("add_job_from_url");
    expect(html).toContain("Jobs");
  });

  it("links planned action CTAs to the expected workspace routes", () => {
    const workspaces = Object.keys(workspaceRoutes) as WorkspaceTab[];

    for (const workspace of workspaces) {
      const route = workspaceRoutes[workspace];
      const action: PlannedCommandAction = {
        id: `action-${workspace}`,
        type: "unknown",
        title: `Open ${workspace}`,
        summary: `Planned action for ${workspace}.`,
        status: "planned",
        targetWorkspace: workspace,
        ctaLabel: `Open ${workspace}`
      };
      const html = renderToStaticMarkup(<AiCommandCenter initialActions={[action]} />);

      expect(html).toContain(`href="${route}"`);
      expect(html).toContain(`Open ${workspace}`);
    }
  });

  it("shows a non-action affordance when no target workspace exists", () => {
    const html = renderToStaticMarkup(
      <AiCommandCenter
        initialActions={[
          {
            id: "action-unknown",
            type: "unknown",
            title: "Review command",
            summary: "JobOps needs more information before routing.",
            status: "planned"
          }
        ]}
      />
    );

    expect(html).toContain("Planned");
    expect(html).not.toContain("href=");
  });

  it("classifies common command examples into planned action types", () => {
    expect(classifyCommand("Here's a job URL. Add it to my jobs list.").type).toBe("add_job_from_url");
    expect(classifyCommand("Follow this company.").type).toBe("follow_company");
    expect(classifyCommand("Which jobs should I apply to today?").type).toBe("prioritize_jobs");
    expect(classifyCommand("Prioritize my saved jobs.").type).toBe("prioritize_jobs");
    expect(classifyCommand("Generate application materials for this role.").type).toBe("generate_materials");
    expect(classifyCommand("Mark this job as applied.").type).toBe("mark_applied");
    expect(classifyCommand("Update my profile with this project.").type).toBe("update_profile");
    expect(classifyCommand("What should I follow up on this week?").type).toBe("follow_up_review");
    expect(classifyCommand("Make something happen.").type).toBe("unknown");
  });

  it("keeps command handling local and avoids live model calls in Next.js", async () => {
    const source = await readFile(new URL("./ai-command-center.tsx", import.meta.url), "utf-8");
    const actionSource = await readFile(new URL("../lib/command-center-actions.ts", import.meta.url), "utf-8");
    const combinedSource = `${source}\n${actionSource}`;

    expect(combinedSource).not.toContain("fetch(");
    expect(combinedSource).not.toContain("/api/command");
    expect(combinedSource).not.toContain("/v1/command");
    expect(combinedSource).not.toContain("GEMINI_API_KEY");
    expect(combinedSource).not.toContain("@jobops/model-connector");
    expect(combinedSource).not.toContain("generateContent");
    expect(combinedSource).toContain("Real command handling should go through FastAPI");
  });
});
