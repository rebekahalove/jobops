import React from "react";
import { JobDiscoveryDiagnostics, JobsList } from "../../../../jobops/components/jobs-list";

export default function JobOpsJobsPage() {
  return (
    <>
      <div className="workspace-diagnostics" aria-label="Job discovery diagnostics">
        <JobDiscoveryDiagnostics apiBasePath="/jobops/api" />
      </div>
      <JobsList apiBasePath="/jobops/api" workspaceBasePath="/jobops" />
    </>
  );
}
