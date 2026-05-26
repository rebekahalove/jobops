"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";

type AccountMe = {
  user?: {
    email?: string;
    username?: string;
    displayName?: string;
  };
  workspace?: {
    slug?: string;
    name?: string;
  };
  candidateProfile?: {
    id?: string;
    displayName?: string;
  };
};

type Message = {
  kind: "success" | "error";
  text: string;
};

export function AccountSettings() {
  const [me, setMe] = useState<AccountMe | null>(null);
  const [message, setMessage] = useState<Message | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function loadMe() {
      try {
        const response = await fetch("/api/me", { cache: "no-store" });
        const payload = await response.json();
        if (!cancelled && response.ok && payload.ok) {
          setMe(payload.result);
        }
      } catch {
      }
    }
    void loadMe();
    return () => {
      cancelled = true;
    };
  }, []);

  async function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsBusy(true);
    setMessage(null);
    const formData = new FormData(event.currentTarget);
    const response = await fetch("/api/dashboard-auth/change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        currentPassword: textValue(formData.get("currentPassword")),
        newPassword: textValue(formData.get("newPassword"))
      })
    });
    setIsBusy(false);
    setMessage(
      response.ok
        ? { kind: "success", text: "Password updated." }
        : { kind: "error", text: "Password could not be updated." }
    );
    if (response.ok) {
      event.currentTarget.reset();
    }
  }

  async function deleteAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsBusy(true);
    setMessage(null);
    const formData = new FormData(event.currentTarget);
    const response = await fetch("/api/dashboard-auth/delete-account", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        confirmation: textValue(formData.get("confirmation")),
        currentPassword: textValue(formData.get("deletePassword")),
        candidateProfileId: me?.candidateProfile?.id
      })
    });
    setIsBusy(false);
    if (response.ok) {
      window.location.assign("/login");
      return;
    }
    setMessage({ kind: "error", text: "Account deletion could not be completed." });
  }

  return (
    <main className="dashboard-main account-settings-page">
      <section className="profile-command-strip" aria-labelledby="account-settings-title">
        <div>
          <p className="eyebrow">Account settings</p>
          <h2 id="account-settings-title">Manage your JobOps alpha account.</h2>
          <p>Use these controls for password updates, recovery readiness, and permanent alpha account deletion.</p>
        </div>
      </section>

      {message ? <p className={`profile-workspace-message ${message.kind}`}>{message.text}</p> : null}

      <div className="account-settings-grid">
        <section className="profile-side-card">
          <p className="eyebrow">Signed in as</p>
          <h3>{me?.user?.displayName || "JobOps user"}</h3>
          <p>{me?.user?.email || "Loading account details..."}</p>
          <p>{me?.workspace?.name || me?.workspace?.slug || ""}</p>
        </section>

        <section className="profile-side-card">
          <p className="eyebrow">Password</p>
          <h3>Change password</h3>
          <form className="login-form compact-account-form" onSubmit={changePassword}>
            <label>
              <span>Current password</span>
              <input autoComplete="current-password" name="currentPassword" required type="password" />
            </label>
            <label>
              <span>New password</span>
              <input autoComplete="new-password" minLength={12} name="newPassword" required type="password" />
            </label>
            <button className="primary-action button-action" disabled={isBusy} type="submit">
              Update password
            </button>
          </form>
        </section>

        <section className="profile-side-card danger-zone">
          <p className="eyebrow">Alpha data deletion</p>
          <h3>Delete my profile/account</h3>
          <p>
            This permanently deletes your alpha workspace/profile data, jobs, companies, applications, command
            interactions, generated outputs, and active sessions.
          </p>
          <form className="login-form compact-account-form" onSubmit={deleteAccount}>
            <label>
              <span>Type DELETE</span>
              <input autoComplete="off" name="confirmation" pattern="DELETE" required type="text" />
            </label>
            <label>
              <span>Current password</span>
              <input autoComplete="current-password" name="deletePassword" required type="password" />
            </label>
            <button className="button-action subtle-danger" disabled={isBusy} type="submit">
              Delete account permanently
            </button>
          </form>
        </section>
      </div>
    </main>
  );
}

function textValue(value: FormDataEntryValue | null) {
  return typeof value === "string" ? value.trim() : "";
}
