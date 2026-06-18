import React from "react";

import { CompanyDiscoveryDiagnostics } from "../../../../jobops/components/company-discovery-diagnostics";
import { CompaniesList } from "../../../../jobops/components/companies-list";

export default function JobOpsCompaniesPage() {
  return (
    <>
      <div className="workspace-diagnostics" aria-label="Company discovery diagnostics">
        <CompanyDiscoveryDiagnostics apiBasePath="/jobops/api" />
      </div>
      <CompaniesList apiBasePath="/jobops/api" workspaceBasePath="/jobops" />
    </>
  );
}
