import type { Metadata } from "next";
import { DashboardShell } from "../components/dashboard-shell";
import { getJobOpsAppMetadata } from "../lib/app-metadata";
import { getCurrentJobOpsSession } from "../lib/jobops-session";
import "./globals.css";

export const metadata: Metadata = {
  title: "JobOps Command Center",
  description: "AI-first command center shell for private job-search operations."
};

export default async function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  const appMetadata = getJobOpsAppMetadata();
  const session = await getCurrentJobOpsSession();

  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>
        <DashboardShell appMetadata={appMetadata} isAdmin={session.isAuthenticated && session.user.userType === "admin"}>
          {children}
        </DashboardShell>
      </body>
    </html>
  );
}
