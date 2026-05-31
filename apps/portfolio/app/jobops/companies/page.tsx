import React from "react";

import { CompaniesList } from "../../../../jobops/components/companies-list";

export default function JobOpsCompaniesPage() {
  return <CompaniesList apiBasePath="/jobops/api" />;
}
