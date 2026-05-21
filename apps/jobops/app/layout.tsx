import type { Metadata } from "next";
import { DashboardShell } from "../components/dashboard-shell";
import { getJobOpsAppMetadata } from "../lib/app-metadata";
import "./globals.css";

export const metadata: Metadata = {
  title: "JobOps Command Center",
  description: "AI-first command center shell for private job-search operations."
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  const appMetadata = getJobOpsAppMetadata();

  return (
    <html lang="en">
      <body>
        <DashboardShell appMetadata={appMetadata}>{children}</DashboardShell>
      </body>
    </html>
  );
}
