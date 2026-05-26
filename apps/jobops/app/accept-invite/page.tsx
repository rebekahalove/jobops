import { InviteAcceptForm } from "../invite/invite-accept-form";

type AcceptInvitePageProps = {
  searchParams: Promise<{ token?: string }>;
};

export default async function AcceptInvitePage({ searchParams }: AcceptInvitePageProps) {
  const { token = "" } = await searchParams;
  return <InviteAcceptForm actionPath="/api/invitations/accept" token={token} />;
}
