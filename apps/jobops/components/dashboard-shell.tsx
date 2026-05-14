import React from "react";
import Link from "next/link";
import { AiCommandCenter } from "./ai-command-center";
import { dashboardWorkflows } from "../lib/workflows";

export function DashboardShell({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="dashboard-shell">
      <header className="top-bar">
        <Link className="brand" href="/">
          <span>JobOps</span>
          <small>AI command center</small>
        </Link>
      </header>
      <div className="command-shell">
        <AiCommandCenter />
        <nav className="workspace-tabs" aria-label="Workspace tabs">
          {dashboardWorkflows.map((workflow) => (
            <Link className="workspace-tab" href={workflow.href} key={workflow.id}>
              {workflow.label}
            </Link>
          ))}
        </nav>
      </div>
      <div className="workspace-content" aria-label="Active workspace content">
        {children}
      </div>
    </div>
  );
}
