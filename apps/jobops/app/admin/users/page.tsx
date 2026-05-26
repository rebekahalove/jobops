import { AdminUsersManager } from "../../../components/admin-users";
import { getCurrentJobOpsSession } from "../../../lib/jobops-session";

export default async function AdminUsersPage() {
  const session = await getCurrentJobOpsSession();
  if (!session.isAuthenticated) {
    return (
      <main className="admin-users-page">
        <section className="admin-section">
          <h1>Sign in required</h1>
          <p>Use an admin account to manage JobOps Alpha users.</p>
        </section>
      </main>
    );
  }
  if (session.user.userType !== "admin") {
    return (
      <main className="admin-users-page">
        <section className="admin-section">
          <h1>Admin access required</h1>
          <p>Your account does not have access to Manage Users.</p>
          <dl className="admin-session-diagnostics" aria-label="Signed-in session details">
            <div>
              <dt>Signed in as</dt>
              <dd>{session.user.email || session.user.username || "Unknown user"}</dd>
            </div>
            <div>
              <dt>Role seen by JobOps</dt>
              <dd>{session.user.userType || "missing"}</dd>
            </div>
          </dl>
        </section>
      </main>
    );
  }

  return <AdminUsersManager currentUserId={session.user.id || ""} />;
}
