"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { AiCommandCenter } from "./ai-command-center";
import { dashboardWorkflows } from "../lib/workflows";
import { getWorkspaceRoute } from "../lib/command-center-actions";
import type { WorkspaceTab } from "../lib/command-center-actions";
import {
  FALLBACK_JOBOPS_APP_METADATA,
  formatJobOpsAppMetadata,
  formatJobOpsAppMetadataTitle,
  type JobOpsAppMetadata
} from "../lib/app-metadata-contract";

export function DashboardShell({
  apiBasePath = "/api",
  appMetadata = FALLBACK_JOBOPS_APP_METADATA,
  basePath = "",
  children
}: Readonly<{
  apiBasePath?: string;
  appMetadata?: JobOpsAppMetadata;
  basePath?: string;
  children: React.ReactNode;
}>) {
  const pathname = usePathname();
  const isPublicPath = isPublicDashboardPath(pathname, basePath);

  useSessionValidityRedirect({ apiBasePath, basePath, enabled: !isPublicPath, pathname });

  if (isPublicPath) {
    return (
      <div className="jobops-page-frame">
        {children}
        <JobOpsFooter appMetadata={appMetadata} />
      </div>
    );
  }

  return (
    <div className="dashboard-shell">
      <header className="top-bar">
        <Link className="brand" href={basePath || "/"}>
          <span>JobOps</span>
          <small>AI command center</small>
        </Link>
        <div className="top-bar-actions">
          <Link className="top-bar-link" href={`${basePath}/about`}>
            About JobOps
          </Link>
          <form action={`${basePath}/api/dashboard-auth/logout`} method="post">
            <button className="logout-button" type="submit">
              Log out
            </button>
          </form>
        </div>
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
      <footer className="dashboard-footer">
        <Link href={`${basePath}/about`}>Public Alpha Page</Link>
        <JobOpsMetadataLine appMetadata={appMetadata} />
      </footer>
    </div>
  );
}

function JobOpsFooter({ appMetadata }: { appMetadata: JobOpsAppMetadata }) {
  return (
    <footer className="dashboard-footer public-page-footer">
      <JobOpsMetadataLine appMetadata={appMetadata} />
    </footer>
  );
}

function JobOpsMetadataLine({ appMetadata }: { appMetadata: JobOpsAppMetadata }) {
  return (
    <p className="build-metadata" title={formatJobOpsAppMetadataTitle(appMetadata)}>
      {formatJobOpsAppMetadata(appMetadata)}
    </p>
  );
}

function useSessionValidityRedirect({
  apiBasePath,
  basePath,
  enabled,
  pathname
}: {
  apiBasePath: string;
  basePath: string;
  enabled: boolean;
  pathname: string | null;
}) {
  useEffect(() => {
    if (!enabled) {
      return;
    }

    let isCancelled = false;

    async function checkSession() {
      try {
        const response = await fetch(`${apiBasePath}/me`, {
          cache: "no-store",
          credentials: "same-origin"
        });
        if (isCancelled || response.ok) {
          if (response.ok) {
            const payload = await response.json();
            if (payload?.result?.user?.passwordResetRequired) {
              redirectToPasswordReset(basePath, pathname, payload.result.user.username);
            }
          }
          return;
        }
      } catch {
        if (isCancelled) {
          return;
        }
      }

      redirectToLogin(basePath, pathname);
    }

    checkSession();

    return () => {
      isCancelled = true;
    };
  }, [apiBasePath, basePath, enabled, pathname]);
}

function redirectToLogin(basePath: string, pathname: string | null) {
  const loginUrl = new URL(`${basePath}/login`, window.location.origin);
  loginUrl.searchParams.set("returnTo", pathname || basePath || "/");
  window.location.assign(`${loginUrl.pathname}${loginUrl.search}`);
}

function redirectToPasswordReset(basePath: string, pathname: string | null, username: string | undefined) {
  const resetUrl = new URL(`${basePath}/reset-password`, window.location.origin);
  if (username) {
    resetUrl.searchParams.set("username", username);
  }
  resetUrl.searchParams.set("returnTo", pathname || basePath || "/");
  window.location.assign(`${resetUrl.pathname}${resetUrl.search}`);
}

function isPublicDashboardPath(pathname: string | null, basePath: string) {
  if (!pathname) {
    return false;
  }

  const localPath = basePath && pathname.startsWith(basePath) ? pathname.slice(basePath.length) || "/" : pathname;
  return (
    localPath === "/about" ||
    localPath === "/login" ||
    localPath === "/reset-password" ||
    localPath === "/privacy" ||
    localPath.startsWith("/invite/") ||
    localPath === "/portfolio" ||
    localPath.startsWith("/portfolio/")
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
