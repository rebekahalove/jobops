"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { AiCommandCenter } from "./ai-command-center";
import { dashboardWorkflows } from "../lib/workflows";
import { getWorkspaceRoute } from "../lib/command-center-actions";
import type { WorkspaceTab } from "../lib/command-center-actions";

export function DashboardShell({
  apiBasePath = "/api",
  basePath = "",
  children
}: Readonly<{
  apiBasePath?: string;
  basePath?: string;
  children: React.ReactNode;
}>) {
  const pathname = usePathname();

  return (
    <div className="dashboard-shell">
      <header className="top-bar">
        <Link className="brand" href={basePath || "/"}>
          <span>JobOps</span>
          <small>AI command center</small>
        </Link>
      </header>
      <div className="command-shell">
        <AiCommandCenter
          activeWorkspace={activeWorkspaceFromPathname(pathname, basePath)}
          apiBasePath={apiBasePath}
          workspaceBasePath={basePath}
        />
        <nav className="workspace-tabs" aria-label="Workspace tabs">
          {dashboardWorkflows.map((workflow) => {
            const href = getWorkspaceRoute(workflow.id, basePath);

            return (
              <Link
                aria-current={isActiveWorkspace(pathname, href) ? "page" : undefined}
                className={`workspace-tab${isActiveWorkspace(pathname, href) ? " active" : ""}`}
                href={href}
                key={workflow.id}
              >
                {workflow.label}
              </Link>
            );
          })}
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

function activeWorkspaceFromPathname(pathname: string | null, basePath: string): WorkspaceTab | undefined {
  if (!pathname) {
    return undefined;
  }

  const workflow = dashboardWorkflows.find((item) => isActiveWorkspace(pathname, getWorkspaceRoute(item.id, basePath)));
  return workflow?.id as WorkspaceTab | undefined;
}
