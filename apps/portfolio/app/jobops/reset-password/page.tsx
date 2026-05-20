import { PasswordResetForm } from "../../../../jobops/app/reset-password/password-reset-form";
import { resolveSafeDashboardReturnTo } from "../../../../jobops/lib/dashboard-auth";

type ResetPasswordPageProps = {
  searchParams?: Promise<{
    error?: string;
    returnTo?: string;
    username?: string;
  }>;
};

export default async function ResetPasswordPage({ searchParams }: ResetPasswordPageProps) {
  const params = await searchParams;
  const returnTo = resolveSafeDashboardReturnTo(params?.returnTo, "/jobops");
  const username = typeof params?.username === "string" ? params.username : "";

  return <PasswordResetForm basePath="/jobops" error={Boolean(params?.error)} returnTo={returnTo} username={username} />;
}
