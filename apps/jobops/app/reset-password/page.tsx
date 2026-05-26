import { PasswordResetForm } from "./password-reset-form";
import { resolveSafeDashboardReturnTo } from "../../lib/dashboard-auth";

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
  const returnTo = resolveSafeDashboardReturnTo(params?.returnTo, "/");
  const token = typeof params?.token === "string" ? params.token : "";
  const username = typeof params?.username === "string" ? params.username : "";

  return <PasswordResetForm error={Boolean(params?.error)} returnTo={returnTo} token={token} username={username} />;
}
