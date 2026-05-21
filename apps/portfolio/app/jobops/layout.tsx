import type { Metadata } from "next";
import { DashboardShell } from "../../../jobops/components/dashboard-shell";
import { getJobOpsAppMetadata } from "../../../jobops/lib/app-metadata";

export const metadata: Metadata = {
  title: "JobOps Command Center | Rebekah Love",
  description: "AI-first command center shell for private job-search operations."
};

export default function JobOpsLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  const appMetadata = getJobOpsAppMetadata();

  return (
    <DashboardShell apiBasePath="/jobops/api" appMetadata={appMetadata} basePath="/jobops">
      {children}
    </DashboardShell>
  );
}
