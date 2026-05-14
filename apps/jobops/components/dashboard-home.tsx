import React from "react";
import Link from "next/link";
import { dashboardWorkflows } from "../lib/workflows";

export function DashboardHome() {
  return (
    <main className="dashboard-main">
      <section className="page-heading" aria-labelledby="dashboard-title">
        <p className="eyebrow">Workspace overview</p>
        <h1 id="dashboard-title">One command center, structured workspaces underneath.</h1>
        <p>
          Use the JobOps agent above as the primary control surface. The tabs below keep profile, companies, jobs,
          applications, materials, and follow-ups available as focused workspaces.
        </p>
      </section>

      <section className="workflow-grid" aria-label="JobOps workflow areas">
        {dashboardWorkflows.map((workflow) => (
          <article className="workflow-card" key={workflow.id}>
            <div>
              <h2>{workflow.label}</h2>
              <p>{workflow.purpose}</p>
            </div>
            <p className="empty-state">{workflow.emptyState}</p>
            <Link href={workflow.href}>Open workspace</Link>
          </article>
        ))}
      </section>
    </main>
  );
}
