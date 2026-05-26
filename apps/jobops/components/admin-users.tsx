"use client";

import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";

type AdminUser = {
  id: string;
  email: string;
  username: string;
  displayName: string;
  userType: "user" | "admin";
  status: string;
  createdAt: string | null;
  passwordResetRequired: boolean;
  passwordExpiresAt: string | null;
  hasPassword: boolean;
};

type AlphaRequest = {
  id: string;
  name: string;
  email: string;
  note: string;
  status: string;
  createdAt: string | null;
};

type UsersPayload = {
  result?: {
    users?: AdminUser[];
    adminCount?: number;
  };
};

type RequestsPayload = {
  result?: {
    requests?: AlphaRequest[];
  };
};

export function AdminUsersManager({ apiBasePath = "/api", currentUserId }: { apiBasePath?: string; currentUserId: string }) {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [requests, setRequests] = useState<AlphaRequest[]>([]);
  const [manualEmail, setManualEmail] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null);

  const lastAdminId = useMemo(() => {
    const activeAdmins = users.filter((user) => user.status === "active" && user.userType === "admin");
    return activeAdmins.length === 1 ? activeAdmins[0].id : null;
  }, [users]);

  useEffect(() => {
    void refresh();
  }, []);

  async function refresh() {
    setError("");
    const [usersResponse, requestsResponse] = await Promise.all([
      fetchJson<UsersPayload>(`${apiBasePath}/admin/users`),
      fetchJson<RequestsPayload>(`${apiBasePath}/admin/alpha-requests`)
    ]);
    setUsers(usersResponse.result?.users ?? []);
    setRequests(requestsResponse.result?.requests ?? []);
  }

  async function runAction(actionId: string, action: () => Promise<void>) {
    setBusyAction(actionId);
    setError("");
    setMessage("");
    try {
      await action();
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Action failed.");
    } finally {
      setBusyAction(null);
    }
  }

  async function inviteRequest(requestId: string) {
    await runAction(`request:${requestId}`, async () => {
      await fetchJson(`${apiBasePath}/admin/alpha-requests/${requestId}/invite`, { method: "POST", body: JSON.stringify({}) });
      setMessage("Invite sent for alpha request.");
      await refresh();
    });
  }

  async function sendManualInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runAction("manual-invite", async () => {
      await fetchJson(`${apiBasePath}/admin/invitations`, {
        method: "POST",
        body: JSON.stringify({ email: manualEmail.trim().toLowerCase() })
      });
      setManualEmail("");
      setMessage("Invite sent.");
      await refresh();
    });
  }

  async function setRole(user: AdminUser, userType: "user" | "admin") {
    await runAction(`role:${user.id}`, async () => {
      await fetchJson(`${apiBasePath}/admin/users/${user.id}/role`, {
        method: "PATCH",
        body: JSON.stringify({ user_type: userType })
      });
      setMessage(userType === "admin" ? "User is now an admin." : "Admin was changed back to user.");
      await refresh();
    });
  }

  async function expirePassword(user: AdminUser) {
    await runAction(`expire:${user.id}`, async () => {
      await fetchJson(`${apiBasePath}/admin/users/${user.id}/expire-password`, { method: "POST" });
      setMessage("Password reset link sent and active sessions revoked.");
      await refresh();
    });
  }

  async function confirmDelete() {
    if (!deleteTarget) {
      return;
    }
    await runAction(`delete:${deleteTarget.id}`, async () => {
      await fetchJson(`${apiBasePath}/admin/users/${deleteTarget.id}`, { method: "DELETE" });
      setDeleteTarget(null);
      setMessage("User account deleted.");
      await refresh();
    });
  }

  return (
    <main className="admin-users-page" aria-labelledby="admin-users-title">
      <header className="admin-users-header">
        <div>
          <p className="eyebrow">Admin</p>
          <h1 id="admin-users-title">Manage Users</h1>
        </div>
      </header>

      {message ? <p className="admin-status success">{message}</p> : null}
      {error ? <p className="admin-status error">{error}</p> : null}

      <section className="admin-section" aria-labelledby="manual-invite-title">
        <h2 id="manual-invite-title">Manual Invite</h2>
        <form className="admin-inline-form" onSubmit={sendManualInvite}>
          <label>
            <span>Email</span>
            <input autoComplete="email" inputMode="email" onChange={(event) => setManualEmail(event.target.value)} required type="email" value={manualEmail} />
          </label>
          <button className="primary-action button-action" disabled={busyAction === "manual-invite"} type="submit">
            Send Invite
          </button>
        </form>
      </section>

      <section className="admin-section" aria-labelledby="pending-requests-title">
        <h2 id="pending-requests-title">Pending Alpha Requests</h2>
        {requests.length ? (
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Name</th>
                  <th>Requested</th>
                  <th>Message</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {requests.map((request) => (
                  <tr key={request.id}>
                    <td>{request.email}</td>
                    <td>{request.name}</td>
                    <td>{formatDate(request.createdAt)}</td>
                    <td>{request.note || "-"}</td>
                    <td>
                      <button className="secondary-action" disabled={busyAction === `request:${request.id}`} onClick={() => inviteRequest(request.id)} type="button">
                        Invite
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="admin-empty">No pending alpha requests.</p>
        )}
      </section>

      <section className="admin-section" aria-labelledby="existing-users-title">
        <h2 id="existing-users-title">Existing Users</h2>
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Email</th>
                <th>Type</th>
                <th>Status</th>
                <th>Created</th>
                <th>Password</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => {
                const isSelf = user.id === currentUserId;
                const isLastAdmin = user.id === lastAdminId;
                return (
                  <tr key={user.id}>
                    <td>
                      <strong>{user.email}</strong>
                      <span>{user.username}</span>
                    </td>
                    <td>{user.userType}</td>
                    <td>{user.status}</td>
                    <td>{formatDate(user.createdAt)}</td>
                    <td>{passwordStatus(user)}</td>
                    <td>
                      <div className="admin-actions">
                        {user.userType === "admin" ? (
                          <button className="secondary-action" disabled={isSelf || isLastAdmin || busyAction === `role:${user.id}`} onClick={() => setRole(user, "user")} type="button">
                            Set User
                          </button>
                        ) : (
                          <button className="secondary-action" disabled={busyAction === `role:${user.id}`} onClick={() => setRole(user, "admin")} type="button">
                            Set Admin
                          </button>
                        )}
                        <button className="secondary-action" disabled={user.status !== "active" || busyAction === `expire:${user.id}`} onClick={() => expirePassword(user)} type="button">
                          Reset Password
                        </button>
                        <button className="danger-action" disabled={isSelf || isLastAdmin || busyAction === `delete:${user.id}`} onClick={() => setDeleteTarget(user)} type="button">
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <dialog className="admin-dialog" open={Boolean(deleteTarget)}>
        <h2>Delete user?</h2>
        <p>{deleteTarget ? `This will revoke access and mark ${deleteTarget.email} as deleted.` : ""}</p>
        <div className="admin-dialog-actions">
          <button className="secondary-action" onClick={() => setDeleteTarget(null)} type="button">
            Cancel
          </button>
          <button className="danger-action" disabled={deleteTarget ? busyAction === `delete:${deleteTarget.id}` : false} onClick={confirmDelete} type="button">
            Delete User
          </button>
        </div>
      </dialog>
    </main>
  );
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers || {})
    }
  });
  const payload = await response.json();
  if (!response.ok || payload?.ok === false) {
    throw new Error(payload?.detail || payload?.error || "Request failed.");
  }
  return payload as T;
}

function formatDate(value: string | null) {
  if (!value) {
    return "-";
  }
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function passwordStatus(user: AdminUser) {
  if (!user.hasPassword) {
    return "No password";
  }
  if (user.passwordResetRequired) {
    return "Reset required";
  }
  return "Active";
}
