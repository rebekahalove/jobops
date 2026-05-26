import type { Metadata } from "next";
import { DashboardShell } from "../../../jobops/components/dashboard-shell";
import { getJobOpsAppMetadata } from "../../../jobops/lib/app-metadata";
import { getCurrentJobOpsSession } from "../../../jobops/lib/jobops-session";

export const metadata: Metadata = {
  title: "JobOps Command Center | Rebekah Love",
  description: "AI-first command center shell for private job-search operations."
};

export default async function JobOpsLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  const appMetadata = getJobOpsAppMetadata();
  const session = await getCurrentJobOpsSession();

  return (
    <DashboardShell
      apiBasePath="/jobops/api"
      appMetadata={appMetadata}
      basePath="/jobops"
      enableAdminNav
      isAdmin={session.isAuthenticated && session.user.userType === "admin"}
    >
      {children}
    </DashboardShell>
  );
}
