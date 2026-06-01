import React from "react";
import { ApplicationDetail } from "../../../../../jobops/components/application-detail";

type PageProps = {
  params: Promise<{ applicationId: string }>;
};

export default async function JobOpsApplicationDetailPage({ params }: PageProps) {
  const { applicationId } = await params;
  return <ApplicationDetail apiBasePath="/jobops/api" applicationId={applicationId} workspaceBasePath="/jobops" />;
}
