export type JobOpsServerSession =
  | {
      isAuthenticated: true;
      user: unknown;
      workspace: unknown;
      candidateProfile: unknown;
    }
  | {
      isAuthenticated: false;
    };
