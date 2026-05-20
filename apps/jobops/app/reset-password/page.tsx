import { PasswordResetForm } from "./password-reset-form";
import { resolveSafeDashboardReturnTo } from "../../lib/dashboard-auth";

type ResetPasswordPageProps = {
  searchParams?: Promise<{
    error?: string;
    returnTo?: string;
    username?: string;
  }>;
};

export default async function ResetPasswordPage({ searchParams }: ResetPasswordPageProps) {
  const params = await searchParams;
  const returnTo = resolveSafeDashboardReturnTo(params?.returnTo, "/");
  const username = typeof params?.username === "string" ? params.username : "";

  return <PasswordResetForm error={Boolean(params?.error)} returnTo={returnTo} username={username} />;
}
