import React from "react";
import Link from "next/link";
import { dashboardWorkflows } from "../lib/workflows";

export function DashboardShell({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="dashboard-shell">
      <header className="top-bar">
        <Link className="brand" href="/">
          <span>JobOps</span>
          <small>Dashboard</small>
        </Link>
        <nav className="primary-nav" aria-label="Primary navigation">
          {dashboardWorkflows.map((workflow) => (
            <Link href={workflow.href} key={workflow.id}>
              {workflow.label}
            </Link>
          ))}
        </nav>
      </header>
      {children}
    </div>
  );
}
