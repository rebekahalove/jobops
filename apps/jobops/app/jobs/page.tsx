import React from "react";
import { JobDiscoveryDiagnostics, JobsList } from "../../components/jobs-list";

export default function JobsPage() {
  return (
    <>
      <div className="workspace-diagnostics" aria-label="Job discovery diagnostics">
        <JobDiscoveryDiagnostics />
      </div>
      <JobsList />
    </>
  );
}
