import { PasswordResetForm } from "../../../../jobops/app/reset-password/password-reset-form";
import { resolveSafeDashboardReturnTo } from "../../../../jobops/lib/dashboard-auth";

type ResetPasswordPageProps = {
  searchParams?: Promise<{
    error?: string;
    returnTo?: string;
    token?: string;
    username?: string;
  }>;
};

export default async function ResetPasswordPage({ searchParams }: ResetPasswordPageProps) {
  const params = await searchParams;
  const returnTo = resolveSafeDashboardReturnTo(params?.returnTo, "/jobops");
  const token = typeof params?.token === "string" ? params.token : "";
  const username = typeof params?.username === "string" ? params.username : "";

  return <PasswordResetForm basePath="/jobops" error={Boolean(params?.error)} returnTo={returnTo} token={token} username={username} />;
}
