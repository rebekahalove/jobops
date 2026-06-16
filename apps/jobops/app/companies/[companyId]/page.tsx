import React from "react";
import { CompanyDetail } from "../../../components/company-detail";

type PageProps = {
  params: Promise<{ companyId: string }>;
};

export default async function CompanyDetailPage({ params }: PageProps) {
  const { companyId } = await params;
  return <CompanyDetail companyId={companyId} />;
}
