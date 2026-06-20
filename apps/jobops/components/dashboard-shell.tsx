"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
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
  enableAdminNav,
  isAdmin = false,
  children
}: Readonly<{
  apiBasePath?: string;
  appMetadata?: JobOpsAppMetadata;
  basePath?: string;
  enableAdminNav?: boolean;
  isAdmin?: boolean;
  children: React.ReactNode;
}>) {
  const pathname = usePathname();
  const isPublicPath = isPublicDashboardPath(pathname, basePath);
  const isAccountPath = isAccountDashboardPath(pathname, basePath);
  const isAdminPath = isAdminDashboardPath(pathname, basePath);
  const allowAdminNav = enableAdminNav ?? basePath === "";
  const showAdminNav = useAdminNavigation({ apiBasePath, enabled: allowAdminNav && !isPublicPath, initialIsAdmin: allowAdminNav && isAdmin });

  useSessionValidityRedirect({ apiBasePath, basePath, enabled: !isPublicPath, pathname });

  if (isPublicPath) {
    return (
      <div className="jobops-page-frame">
        {children}
        <JobOpsFooter appMetadata={appMetadata} basePath={basePath} />
      </div>
    );
  }

  if (isAccountPath || isAdminPath) {
    return (
      <div className="dashboard-shell account-shell">
        <TopBar basePath={basePath} isAdmin={showAdminNav} />
        {children}
        <DashboardFooter appMetadata={appMetadata} basePath={basePath} />
      </div>
    );
  }

  return (
    <div className="dashboard-shell">
      <TopBar basePath={basePath} isAdmin={showAdminNav} />
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
      <DashboardFooter appMetadata={appMetadata} basePath={basePath} />
    </div>
  );
}

function TopBar({ basePath, isAdmin }: { basePath: string; isAdmin: boolean }) {
  return (
    <header className="top-bar">
      <Link className="brand" href={basePath || "/"}>
        <span>JobOps</span>
        <small>AI command center</small>
      </Link>
      <div className="top-bar-actions">
        <Link className="top-bar-link" href={basePath || "/"}>
          Command Center
        </Link>
        <Link className="top-bar-link" href={`${basePath}/about`}>
          About JobOps
        </Link>
        <Link className="top-bar-link" href={`${basePath}/account`}>
          Account
        </Link>
        {isAdmin ? (
          <Link className="top-bar-link" href={`${basePath}/admin/users`}>
            Admin
          </Link>
        ) : null}
        <form action={`${basePath}/api/dashboard-auth/logout`} method="post">
          <button className="logout-button" type="submit">
            Log out
          </button>
        </form>
      </div>
    </header>
  );
}

function DashboardFooter({ appMetadata, basePath }: { appMetadata: JobOpsAppMetadata; basePath: string }) {
  return (
    <footer className="dashboard-footer">
      <Link href={`${basePath}/about`}>Public Alpha Page</Link>
      <Link href={`${basePath}/privacy`}>Privacy</Link>
      <JobOpsMetadataLine appMetadata={appMetadata} />
    </footer>
  );
}

function JobOpsFooter({ appMetadata, basePath }: { appMetadata: JobOpsAppMetadata; basePath: string }) {
  return (
    <footer className="dashboard-footer public-page-footer">
      <Link href={`${basePath}/privacy`}>Privacy</Link>
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
        if (response.status !== 401 && response.status !== 403) {
          return;
        }
      } catch {
        if (isCancelled) {
          return;
        }
        return;
      }

      redirectToLogin(basePath, pathname);
    }

    checkSession();

    return () => {
      isCancelled = true;
    };
  }, [apiBasePath, basePath, enabled, pathname]);
}

function useAdminNavigation({
  apiBasePath,
  enabled,
  initialIsAdmin
}: {
  apiBasePath: string;
  enabled: boolean;
  initialIsAdmin: boolean;
}) {
  const [isAdmin, setIsAdmin] = useState(initialIsAdmin);

  useEffect(() => {
    setIsAdmin(initialIsAdmin);
  }, [initialIsAdmin]);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    let isCancelled = false;

    async function checkAdminStatus() {
      try {
        const response = await fetch(`${apiBasePath}/me`, {
          cache: "no-store",
          credentials: "same-origin"
        });
        if (!response.ok || isCancelled) {
          return;
        }
        const payload = await response.json();
        if (!isCancelled) {
          setIsAdmin(payload?.result?.user?.userType === "admin");
        }
      } catch {
        if (!isCancelled) {
          setIsAdmin(initialIsAdmin);
        }
      }
    }

    checkAdminStatus();

    return () => {
      isCancelled = true;
    };
  }, [apiBasePath, enabled, initialIsAdmin]);

  return isAdmin;
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
    localPath === "/forgot-password" ||
    localPath === "/accept-invite" ||
    localPath === "/privacy" ||
    localPath.startsWith("/invite/") ||
    localPath === "/portfolio" ||
    localPath.startsWith("/portfolio/")
  );
}

function isAccountDashboardPath(pathname: string | null, basePath: string) {
  if (!pathname) {
    return false;
  }

  const localPath = basePath && pathname.startsWith(basePath) ? pathname.slice(basePath.length) || "/" : pathname;
  return localPath === "/account" || localPath.startsWith("/account/");
}

function isAdminDashboardPath(pathname: string | null, basePath: string) {
  if (!pathname) {
    return false;
  }

  const localPath = basePath && pathname.startsWith(basePath) ? pathname.slice(basePath.length) || "/" : pathname;
  return localPath === "/admin" || localPath.startsWith("/admin/");
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
