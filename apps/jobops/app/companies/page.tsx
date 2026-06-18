import React from "react";
import { CompanyDiscoveryDiagnostics } from "../../components/company-discovery-diagnostics";
import { CompaniesList } from "../../components/companies-list";

export default function CompaniesPage() {
  return (
    <>
      <div className="workspace-diagnostics" aria-label="Company discovery diagnostics">
        <CompanyDiscoveryDiagnostics />
      </div>
      <CompaniesList />
    </>
  );
}
