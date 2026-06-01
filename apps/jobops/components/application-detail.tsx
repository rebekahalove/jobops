"use client";

import Link from "next/link";
import React, { useEffect, useState } from "react";
import {
  ApplicationMaterials,
  actionResultMessage,
  apiErrorMessage,
  canMarkApplied,
  canReopenTerminal,
  canMarkTerminal,
  formatDateOnly,
  formatDateTime,
  formatOptionalStatus,
  formatStatus,
  underlyingStatusClass,
  type ApplicationMaterialBundle,
  type TrackedApplication
} from "./applications-tracker";

export function ApplicationDetail({
  apiBasePath = "/api",
  applicationId,
  initialApplication = null,
  workspaceBasePath = ""
}: {
  apiBasePath?: string;
  applicationId: string;
  initialApplication?: TrackedApplication | null;
  workspaceBasePath?: string;
}) {
  const [application, setApplication] = useState<TrackedApplication | null>(initialApplication);
  const [message, setMessage] = useState("");
  const [messageKind, setMessageKind] = useState<"success" | "error" | "info">("info");
  const [pendingStatus, setPendingStatus] = useState(false);
  const [pendingArchive, setPendingArchive] = useState(false);
  const [pendingMaterials, setPendingMaterials] = useState(false);

  useEffect(() => {
    if (!message) {
      return;
    }
    const timeout = window.setTimeout(() => setMessage(""), messageKind === "error" ? 9000 : 5200);
    return () => window.clearTimeout(timeout);
  }, [message, messageKind]);

  useEffect(() => {
    let active = true;

    async function loadApplication() {
      try {
        const response = await fetch(`${apiBasePath}/applications/${applicationId}`, { cache: "no-store" });
        const payload = await response.json().catch(() => null);
        if (!response.ok) {
          if (response.status === 404) {
            const fallbackApplication = await loadApplicationFromList(apiBasePath, applicationId);
            if (fallbackApplication) {
              if (active) {
                setApplication(fallbackApplication);
                setMessage("");
              }
              return;
            }
          }
          if (active) {
            setMessageKind("error");
            setMessage(apiErrorMessage(payload, response.status));
          }
          return;
        }
        if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
          if (active) {
            setMessageKind("error");
            setMessage("Applications API returned an unexpected response.");
          }
          return;
        }
        if (active) {
          setApplication(payload as TrackedApplication);
          setMessage("");
        }
      } catch {
        if (active) {
          setMessageKind("error");
          setMessage("Application API is unavailable. Start FastAPI to load this application.");
        }
      }
    }

    loadApplication();
    return () => {
      active = false;
    };
  }, [apiBasePath, applicationId]);

  async function markApplied() {
    if (!application) {
      return;
    }
    setPendingStatus(true);
    setMessage("");

    try {
      const response = await fetch(`${apiBasePath}/applications/${application.id}/status`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ status: "applied" })
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(apiErrorMessage(payload, response.status));
      }
      setApplication(payload as TrackedApplication);
      setMessageKind("success");
      setMessage("Application marked applied.");
      window.dispatchEvent(new CustomEvent("jobops:applications-updated"));
      window.dispatchEvent(new CustomEvent("jobops:jobs-updated"));
    } catch (error) {
      setMessageKind("error");
      setMessage(error instanceof Error ? error.message : "Could not mark application as applied.");
    } finally {
      setPendingStatus(false);
    }
  }

  async function postApplicationAction(action: "archive" | "restore" | "reject" | "withdraw" | "reopen", fallbackMessage: string) {
    if (!application) {
      return;
    }
    setPendingArchive(true);
    setMessage("");

    try {
      const response = await fetch(`${apiBasePath}/applications/${application.id}/${action}`, { method: "POST" });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(apiErrorMessage(payload, response.status));
      }
      if (!payload || typeof payload !== "object" || !("application" in payload)) {
        throw new Error("Applications API returned an unexpected response.");
      }
      setApplication(payload.application as TrackedApplication);
      setMessageKind("success");
      setMessage(actionResultMessage(payload, fallbackMessage));
      window.dispatchEvent(new CustomEvent("jobops:applications-updated"));
      window.dispatchEvent(new CustomEvent("jobops:jobs-updated"));
    } catch (error) {
      setMessageKind("error");
      setMessage(error instanceof Error ? error.message : `Could not ${action} application.`);
    } finally {
      setPendingArchive(false);
    }
  }

  async function generateMaterials() {
    if (!application) {
      return;
    }
    setPendingMaterials(true);
    setMessage("");

    try {
      const response = await fetch(`${apiBasePath}/applications/${application.id}/materials/generate`, {
        method: "POST"
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(apiErrorMessage(payload, response.status));
      }
      if (!payload || typeof payload !== "object" || !("bundle" in payload)) {
        throw new Error("Materials API returned an unexpected response.");
      }
      const bundle = payload.bundle as ApplicationMaterialBundle;
      setApplication({ ...application, latest_material_bundle: bundle, updated_at: bundle.updated_at });
      setMessageKind("success");
      setMessage("Application materials generated.");
      window.dispatchEvent(new CustomEvent("jobops:applications-updated"));
    } catch (error) {
      setMessageKind("error");
      setMessage(error instanceof Error ? error.message : "Could not generate application materials.");
    } finally {
      setPendingMaterials(false);
    }
  }

  if (!application) {
    return (
      <main className="dashboard-main application-detail-workspace">
        <Link className="detail-back-link" href={`${workspaceBasePath}/applications`}>
          Back to Applications
        </Link>
        <section className="empty-state-block">
          <h1>Application not loaded</h1>
          <p>{message || "Loading application details..."}</p>
        </section>
      </main>
    );
  }

  return (
    <main className="dashboard-main application-detail-workspace">
      <Link className="detail-back-link" href={`${workspaceBasePath}/applications`}>
        Back to Applications
      </Link>

      <section className="application-detail-header">
        <div>
          <p className="eyebrow">Application detail</p>
          <h1>
            {application.company_name}: {application.job_title}
          </h1>
        </div>
        <div className="application-card-badges application-detail-badges" aria-label="Application status">
          <span className={`application-status application-status-${underlyingStatusClass(application.status)}`}>
            {formatStatus(application.status)}
          </span>
          {application.archived_at ? <span className="application-status application-status-archived">Archived</span> : null}
        </div>
      </section>

      {message ? <p className={`profile-workspace-message ${messageKind}`}>{message}</p> : null}

      <section className="application-detail-panel" aria-labelledby="application-detail-title">
        <div className="application-detail-panel-heading">
          <h2 id="application-detail-title">Application information</h2>
          <div className="company-links application-detail-actions" aria-label={`${application.job_title} actions`}>
            {application.job_url ? (
              <a href={application.job_url} rel="noopener noreferrer" target="_blank">
                Job post
              </a>
            ) : null}
            {application.apply_url && application.apply_url !== application.job_url ? (
              <a href={application.apply_url} rel="noopener noreferrer" target="_blank">
                Apply link
              </a>
            ) : null}
            {!application.archived_at && canMarkApplied(application) ? (
              <button className="secondary-action compact-action" disabled={pendingStatus} type="button" onClick={markApplied}>
                {pendingStatus ? "Saving..." : "Mark applied"}
              </button>
            ) : null}
            {!application.archived_at ? (
              <>
                <button
                  className="secondary-action compact-action"
                  disabled={pendingArchive}
                  type="button"
                  onClick={() => postApplicationAction("archive", "Application archived. Saved materials and history were preserved.")}
                >
                  {pendingArchive ? "Saving..." : "Archive"}
                </button>
                {canMarkTerminal(application) ? (
                  <>
                    <button
                      className="secondary-action compact-action"
                      disabled={pendingArchive}
                      type="button"
                      onClick={() =>
                        postApplicationAction("reject", "Application marked rejected and archived. Saved materials and history were preserved.")
                      }
                    >
                      Reject
                    </button>
                    <button
                      className="secondary-action compact-action"
                      disabled={pendingArchive}
                      type="button"
                      onClick={() =>
                        postApplicationAction("withdraw", "Application marked withdrawn and archived. Saved materials and history were preserved.")
                      }
                    >
                      Withdraw
                    </button>
                  </>
                ) : null}
              </>
            ) : (
              <>
                <button
                  className="secondary-action compact-action"
                  disabled={pendingArchive}
                  type="button"
                  onClick={() => postApplicationAction("restore", "Application restored. Saved materials and history were preserved.")}
                >
                  {pendingArchive ? "Saving..." : "Restore"}
                </button>
              </>
            )}
            {canReopenTerminal(application) ? (
              <button
                className="secondary-action compact-action"
                disabled={pendingArchive}
                type="button"
                onClick={() => postApplicationAction("reopen", "Application moved back to Applied. Rejection or withdrawal details were cleared.")}
              >
                {pendingArchive ? "Saving..." : "Move back to Applied"}
              </button>
            ) : null}
          </div>
        </div>

        <dl className="application-detail-grid application-detail-primary-grid">
          <DetailItem label="Company" value={application.company_name} />
          <DetailItem className="application-detail-wide" label="Job title" value={application.job_title} />
          <DetailItem label="Location" value={application.location || formatOptionalStatus(application.remote_work_mode ?? null)} />
          <DetailItem label="Compensation" value={application.salary_text || "Unknown"} />
          <DetailItem label="Employment" value={application.employment_type || "Unknown"} />
          <DetailItem label="Posted" value={formatDateOnly(application.posting_date ?? null)} />
          <DetailItem label="Follow-up" value={formatDateOnly(application.next_follow_up_date)} />
        </dl>

        {application.saved_job_id || application.job_id ? (
          <div className="application-linked-job-action">
            <Link className="secondary-action compact-action" href={savedJobHref(application, workspaceBasePath)}>
              View saved job
            </Link>
          </div>
        ) : null}

        <details className="application-detail-metadata">
          <summary>More details</summary>
          <dl className="application-detail-grid application-detail-secondary-grid">
            <DetailItem label="Source" value={application.source || application.source_provider || "Unknown"} />
            <DetailItem label="Status" value={formatStatus(application.status)} />
            <DetailItem label="Date applied" value={formatDateOnly(application.date_applied)} />
            <DetailItem label="Created" value={formatDateTime(application.created_at)} />
            <DetailItem label="Updated" value={formatDateTime(application.updated_at)} />
            <DetailItem label="Archive" value={application.archived_at ? formatDateTime(application.archived_at) : "Active"} />
            {application.archived_reason ? <DetailItem className="application-detail-wide" label="Archived reason" value={application.archived_reason} /> : null}
            {application.archived_by_action ? <DetailItem label="Archived by" value={formatStatus(application.archived_by_action)} /> : null}
          </dl>
        </details>
      </section>

      <section className="application-detail-panel" aria-labelledby="application-notes-title">
        <h2 id="application-notes-title">Notes</h2>
        <p className="application-detail-body-text">{application.notes || "No notes yet."}</p>
        {application.fit_summary ? (
          <>
            <h3>Fit summary</h3>
            <p className="application-detail-body-text">{application.fit_summary}</p>
          </>
        ) : null}
      </section>

      <section className="application-detail-panel" aria-labelledby="application-materials-title">
        <div className="application-detail-panel-heading">
          <h2 id="application-materials-title">Materials</h2>
          {!application.archived_at ? (
            <button className="secondary-action compact-action" disabled={pendingMaterials} type="button" onClick={generateMaterials}>
              {pendingMaterials ? "Generating..." : application.latest_material_bundle ? "Regenerate materials" : "Generate materials"}
            </button>
          ) : null}
        </div>

        {application.latest_material_bundle ? (
          <ApplicationMaterials bundle={application.latest_material_bundle} defaultOpen roomy />
        ) : (
          <div className="empty-state-block application-detail-empty-materials">
            <h3>No materials generated yet.</h3>
            <p>Generate materials when this application is ready for a tailored bundle.</p>
          </div>
        )}
      </section>
    </main>
  );
}

async function loadApplicationFromList(apiBasePath: string, applicationId: string) {
  const response = await fetch(`${apiBasePath}/applications`, { cache: "no-store" });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !Array.isArray(payload)) {
    return null;
  }
  return (payload as TrackedApplication[]).find((item) => item.id === applicationId) ?? null;
}

function DetailItem({ className, label, value }: { className?: string; label: string; value: React.ReactNode }) {
  return (
    <div className={className}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function savedJobHref(application: TrackedApplication, workspaceBasePath: string) {
  if (application.saved_job_id) {
    return `${workspaceBasePath}/jobs#saved-job-${encodeURIComponent(application.saved_job_id)}`;
  }
  return `${workspaceBasePath}/jobs`;
}
