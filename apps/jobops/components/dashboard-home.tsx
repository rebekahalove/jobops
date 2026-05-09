import React from "react";
import Link from "next/link";
import { dashboardWorkflows } from "../lib/workflows";

export function DashboardHome() {
  const recommended = dashboardWorkflows.find((workflow) => workflow.recommendedStep);
  const otherWorkflows = dashboardWorkflows.filter((workflow) => !workflow.recommendedStep);

  return (
    <main className="dashboard-main">
      <section className="page-heading" aria-labelledby="dashboard-title">
        <p className="eyebrow">Job-search operations</p>
        <h1 id="dashboard-title">Build the profile first. Everything else gets stronger from there.</h1>
        <p>
          This dashboard will host profile intake, job tracking, fit scoring, application materials, and follow-up
          workflows. For now it is a clean shell with the profile workflow staged as the next build step.
        </p>
      </section>

      {recommended ? (
        <section className="recommended-panel" aria-labelledby="recommended-title">
          <div>
            <p className="eyebrow">Recommended first step</p>
            <h2 id="recommended-title">{recommended.label}</h2>
            <p>{recommended.purpose}</p>
            <p>{recommended.emptyState}</p>
          </div>
          <Link className="primary-action" href={recommended.href}>
            Open profile workspace
          </Link>
        </section>
      ) : null}

      <section className="workflow-grid" aria-label="JobOps workflow areas">
        {otherWorkflows.map((workflow) => (
          <article className="workflow-card" key={workflow.id}>
            <div>
              <h2>{workflow.label}</h2>
              <p>{workflow.purpose}</p>
            </div>
            <p className="empty-state">{workflow.emptyState}</p>
            <Link href={workflow.href}>View placeholder</Link>
          </article>
        ))}
      </section>
    </main>
  );
}
