import { InviteAcceptForm } from "../../../../../jobops/app/invite/invite-accept-form";

type InvitePageProps = {
  params: Promise<{ token: string }>;
};

export default async function InvitePage({ params }: InvitePageProps) {
  const { token } = await params;
  return <InviteAcceptForm basePath="/jobops" token={token} />;
}
