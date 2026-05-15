import React from "react";
import { ApplicationsTracker } from "../../../../jobops/components/applications-tracker";

export default function JobOpsApplicationsPage() {
  return <ApplicationsTracker apiBasePath="/jobops/api" />;
}
