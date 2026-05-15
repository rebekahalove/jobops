import { DashboardLogin } from "../../components/dashboard-login";
import { resolveSafeDashboardReturnTo } from "../../lib/dashboard-auth";

type LoginPageProps = {
  searchParams?: Promise<{
    error?: string;
    returnTo?: string;
  }>;
};

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const params = await searchParams;
  const returnTo = resolveSafeDashboardReturnTo(params?.returnTo, "/");

  return <DashboardLogin error={Boolean(params?.error)} returnTo={returnTo} />;
}
