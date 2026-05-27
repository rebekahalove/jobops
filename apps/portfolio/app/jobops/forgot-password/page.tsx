import { ForgotPasswordForm } from "../../../../jobops/app/forgot-password/forgot-password-form";

type ForgotPasswordPageProps = {
  searchParams?: Promise<{
    sent?: string;
  }>;
};

export default async function MountedForgotPasswordPage({ searchParams }: ForgotPasswordPageProps) {
  const params = await searchParams;
  const sent = Boolean(params?.sent);

  return <ForgotPasswordForm basePath="/jobops" sent={sent} />;
}
