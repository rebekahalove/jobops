"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { AiCommandCenter } from "./ai-command-center";
import { dashboardWorkflows } from "../lib/workflows";
import type { WorkspaceTab } from "../lib/command-center-actions";

export function DashboardShell({ children }: Readonly<{ children: React.ReactNode }>) {
  const pathname = usePathname();

  return (
    <div className="dashboard-shell">
      <header className="top-bar">
        <Link className="brand" href="/">
          <span>JobOps</span>
          <small>AI command center</small>
        </Link>
      </header>
      <div className="command-shell">
        <AiCommandCenter activeWorkspace={activeWorkspaceFromPathname(pathname)} />
        <nav className="workspace-tabs" aria-label="Workspace tabs">
          {dashboardWorkflows.map((workflow) => (
            <Link
              aria-current={isActiveWorkspace(pathname, workflow.href) ? "page" : undefined}
              className={`workspace-tab${isActiveWorkspace(pathname, workflow.href) ? " active" : ""}`}
              href={workflow.href}
              key={workflow.id}
            >
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

export function isActiveWorkspace(pathname: string | null, href: string) {
  if (!pathname) {
    return false;
  }

  return pathname === href || pathname.startsWith(`${href}/`);
}

function activeWorkspaceFromPathname(pathname: string | null): WorkspaceTab | undefined {
  if (!pathname) {
    return undefined;
  }

  const workflow = dashboardWorkflows.find((item) => isActiveWorkspace(pathname, item.href));
  return workflow?.id as WorkspaceTab | undefined;
}
