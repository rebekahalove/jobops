import { InviteAcceptForm } from "../../../../jobops/app/invite/invite-accept-form";

type AcceptInvitePageProps = {
  searchParams: Promise<{ token?: string }>;
};

export default async function MountedAcceptInvitePage({ searchParams }: AcceptInvitePageProps) {
  const { token = "" } = await searchParams;
  return <InviteAcceptForm actionPath="/api/invitations/accept" basePath="/jobops" token={token} />;
}
