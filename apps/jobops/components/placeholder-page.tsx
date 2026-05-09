import React from "react";
import Link from "next/link";
import type { DashboardWorkflowId } from "../lib/workflows";
import { getWorkflow } from "../lib/workflows";

export function PlaceholderPage({ workflowId }: { workflowId: DashboardWorkflowId }) {
  const workflow = getWorkflow(workflowId);

  return (
    <main className="dashboard-main">
      <section className="placeholder-panel" aria-labelledby={`${workflow.id}-title`}>
        <Link className="back-link" href="/">
          Back to dashboard
        </Link>
        <p className="eyebrow">{workflow.recommendedStep ? "Recommended first step" : "Planned workflow"}</p>
        <h1 id={`${workflow.id}-title`}>{workflow.label}</h1>
        <p>{workflow.purpose}</p>
        <div className="empty-state-block">
          <h2>Empty State</h2>
          <p>{workflow.emptyState}</p>
        </div>
      </section>
    </main>
  );
}
