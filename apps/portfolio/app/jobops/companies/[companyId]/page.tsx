import React from "react";
import { CompanyDetail } from "../../../../../jobops/components/company-detail";

type PageProps = {
  params: Promise<{ companyId: string }>;
};

export default async function JobOpsCompanyDetailPage({ params }: PageProps) {
  const { companyId } = await params;
  return <CompanyDetail apiBasePath="/jobops/api" companyId={companyId} workspaceBasePath="/jobops" />;
}
