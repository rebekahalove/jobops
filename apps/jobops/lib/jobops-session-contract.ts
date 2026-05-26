export type JobOpsServerSession =
  | {
      isAuthenticated: true;
      user: {
        id?: string;
        email?: string;
        username?: string;
        displayName?: string;
        userType?: "user" | "admin" | string;
        passwordResetRequired?: boolean;
      };
      workspace: unknown;
      candidateProfile: unknown;
    }
  | {
      isAuthenticated: false;
    };
