import type { Metadata } from "next";
import { DashboardShell } from "../../../jobops/components/dashboard-shell";

export const metadata: Metadata = {
  title: "JobOps Command Center | Rebekah Love",
  description: "AI-first command center shell for private job-search operations."
};

export default function JobOpsLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <DashboardShell apiBasePath="/jobops/api" basePath="/jobops">
      {children}
    </DashboardShell>
  );
}
