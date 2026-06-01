import React from "react";
import { ApplicationDetail } from "../../../components/application-detail";

type PageProps = {
  params: Promise<{ applicationId: string }>;
};

export default async function ApplicationDetailPage({ params }: PageProps) {
  const { applicationId } = await params;
  return <ApplicationDetail applicationId={applicationId} />;
}
