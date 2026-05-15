import { DashboardLogin } from "../../../../jobops/components/dashboard-login";
import { resolveSafeDashboardReturnTo } from "../../../../jobops/lib/dashboard-auth";

type LoginPageProps = {
  searchParams?: Promise<{
    error?: string;
    returnTo?: string;
  }>;
};

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const params = await searchParams;
  const returnTo = resolveSafeDashboardReturnTo(params?.returnTo, "/jobops");

  return <DashboardLogin basePath="/jobops" error={Boolean(params?.error)} returnTo={returnTo} />;
}
