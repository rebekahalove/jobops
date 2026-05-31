import React from "react";
import { JobsList } from "../../../../jobops/components/jobs-list";

export default function JobOpsJobsPage() {
  return <JobsList apiBasePath="/jobops/api" />;
}
