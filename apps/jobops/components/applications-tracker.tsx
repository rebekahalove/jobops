"use client";

import React, { useEffect, useMemo, useState } from "react";

export const applicationStatuses = ["saved", "applied", "interviewing", "rejected", "offer", "closed", "withdrawn"] as const;

export type ApplicationStatus = (typeof applicationStatuses)[number];

export type TrackedApplication = {
  id: string;
  company_name: string;
  job_title: string;
  job_url: string | null;
  location: string | null;
  source: string | null;
  date_applied: string | null;
  status: ApplicationStatus;
  notes: string;
  next_follow_up_date: string | null;
  created_at: string;
  updated_at: string;
};

type ApplicationFormState = {
  companyName: string;
  jobTitle: string;
  jobUrl: string;
  location: string;
  source: string;
  dateApplied: string;
  status: ApplicationStatus;
  notes: string;
  nextFollowUpDate: string;
};

const emptyForm: ApplicationFormState = {
  companyName: "",
  jobTitle: "",
  jobUrl: "",
  location: "",
  source: "",
  dateApplied: "",
  status: "saved",
  notes: "",
  nextFollowUpDate: ""
};

export function ApplicationsTracker({ initialApplications = [] }: { initialApplications?: TrackedApplication[] }) {
  const [applications, setApplications] = useState(initialApplications);
  const [form, setForm] = useState<ApplicationFormState>(emptyForm);
  const [statusDrafts, setStatusDrafts] = useState<Record<string, ApplicationStatus>>({});
  const [message, setMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    let active = true;

    async function loadApplications() {
      try {
        const response = await fetch("/api/applications", { cache: "no-store" });
        if (!response.ok) {
          return;
        }
        const payload = (await response.json()) as TrackedApplication[];
        if (active) {
          setApplications(payload);
        }
      } catch {
        if (active) {
          setMessage("Application API is unavailable. Start FastAPI to load saved records.");
        }
      }
    }

    loadApplications();
    return () => {
      active = false;
    };
  }, []);

  const sortedApplications = useMemo(
    () =>
      [...applications].sort((left, right) => {
        const leftDate = left.next_follow_up_date ?? left.date_applied ?? left.created_at;
        const rightDate = right.next_follow_up_date ?? right.date_applied ?? right.created_at;
        return rightDate.localeCompare(leftDate);
      }),
    [applications]
  );

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setMessage("");

    try {
      const response = await fetch("/api/applications", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          company_name: form.companyName,
          job_title: form.jobTitle,
          job_url: form.jobUrl || null,
          location: form.location || null,
          source: form.source || null,
          date_applied: form.dateApplied || null,
          status: form.status,
          notes: form.notes,
          next_follow_up_date: form.nextFollowUpDate || null
        })
      });

      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error ?? payload.detail ?? "Could not save application.");
      }

      setApplications((current) => [payload as TrackedApplication, ...current]);
      setForm(emptyForm);
      setMessage("Application saved.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save application.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function updateStatus(application: TrackedApplication) {
    const nextStatus = statusDrafts[application.id] ?? application.status;
    setMessage("");

    try {
      const response = await fetch(`/api/applications/${application.id}/status`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ status: nextStatus })
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error ?? payload.detail ?? "Could not update status.");
      }

      setApplications((current) => current.map((item) => (item.id === application.id ? (payload as TrackedApplication) : item)));
      setMessage("Status updated.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not update status.");
    }
  }

  return (
    <main className="dashboard-main application-workspace">
      <section className="page-heading">
        <p className="eyebrow">Manual tracker MVP</p>
        <h1>Applications</h1>
        <p>Track jobs you have saved or applied to, including status, source, notes, and the next follow-up date.</p>
      </section>

      <section className="application-layout" aria-label="Application tracker">
        <form className="application-form" onSubmit={handleSubmit}>
          <div>
            <p className="eyebrow">Add application</p>
            <h2>Manual entry</h2>
          </div>
          <div className="application-form-grid">
            <label>
              <span className="field-label">Company</span>
              <input
                required
                suppressHydrationWarning
                value={form.companyName}
                onChange={(event) => setForm({ ...form, companyName: event.target.value })}
              />
            </label>
            <label>
              <span className="field-label">Job title</span>
              <input
                required
                suppressHydrationWarning
                value={form.jobTitle}
                onChange={(event) => setForm({ ...form, jobTitle: event.target.value })}
              />
            </label>
            <label>
              <span className="field-label">Job URL</span>
              <input
                suppressHydrationWarning
                type="url"
                value={form.jobUrl}
                onChange={(event) => setForm({ ...form, jobUrl: event.target.value })}
              />
            </label>
            <label>
              <span className="field-label">Location</span>
              <input
                suppressHydrationWarning
                value={form.location}
                onChange={(event) => setForm({ ...form, location: event.target.value })}
              />
            </label>
            <label>
              <span className="field-label">Source</span>
              <input
                suppressHydrationWarning
                value={form.source}
                onChange={(event) => setForm({ ...form, source: event.target.value })}
              />
            </label>
            <label>
              <span className="field-label">Status</span>
              <select
                suppressHydrationWarning
                value={form.status}
                onChange={(event) => setForm({ ...form, status: event.target.value as ApplicationStatus })}
              >
                {applicationStatuses.map((status) => (
                  <option key={status} value={status}>
                    {formatStatus(status)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span className="field-label">Date applied</span>
              <input
                suppressHydrationWarning
                type="date"
                value={form.dateApplied}
                onChange={(event) => setForm({ ...form, dateApplied: event.target.value })}
              />
            </label>
            <label>
              <span className="field-label">Next follow-up</span>
              <input
                suppressHydrationWarning
                type="date"
                value={form.nextFollowUpDate}
                onChange={(event) => setForm({ ...form, nextFollowUpDate: event.target.value })}
              />
            </label>
          </div>
          <label>
            <span className="field-label">Notes</span>
            <textarea
              className="small-textarea"
              suppressHydrationWarning
              value={form.notes}
              onChange={(event) => setForm({ ...form, notes: event.target.value })}
            />
          </label>
          <button className="primary-action button-action" disabled={isSubmitting} suppressHydrationWarning type="submit">
            {isSubmitting ? "Saving..." : "Save application"}
          </button>
          {message ? <p className="application-message">{message}</p> : null}
        </form>

        <section className="application-list" aria-labelledby="application-list-title">
          <div className="application-list-header">
            <div>
              <p className="eyebrow">Pipeline</p>
              <h2 id="application-list-title">Saved applications</h2>
            </div>
            <span>{applications.length}</span>
          </div>
          {sortedApplications.length > 0 ? (
            <div className="application-table-wrap">
              <table className="application-table">
                <thead>
                  <tr>
                    <th scope="col">Role</th>
                    <th scope="col">Status</th>
                    <th scope="col">Follow-up</th>
                    <th scope="col">Notes</th>
                    <th scope="col">Edit status</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedApplications.map((application) => (
                    <tr key={application.id}>
                      <td>
                        <strong>{application.job_title}</strong>
                        <span>{application.company_name}</span>
                        {application.job_url ? <a href={application.job_url}>Job post</a> : null}
                      </td>
                      <td>
                        <span className={`application-status application-status-${application.status}`}>
                          {formatStatus(application.status)}
                        </span>
                      </td>
                      <td>{formatDate(application.next_follow_up_date)}</td>
                      <td>{application.notes || "No notes yet"}</td>
                      <td>
                        <div className="status-edit">
                          <select
                            aria-label={`Status for ${application.company_name} ${application.job_title}`}
                            suppressHydrationWarning
                            value={statusDrafts[application.id] ?? application.status}
                            onChange={(event) =>
                              setStatusDrafts({
                                ...statusDrafts,
                                [application.id]: event.target.value as ApplicationStatus
                              })
                            }
                          >
                            {applicationStatuses.map((status) => (
                              <option key={status} value={status}>
                                {formatStatus(status)}
                              </option>
                            ))}
                          </select>
                          <button className="secondary-action" suppressHydrationWarning type="button" onClick={() => updateStatus(application)}>
                            Save
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="empty-state-block">
              <h2>No applications yet</h2>
              <p>Add the first job you saved or applied to. Job intake, fit scoring, and generated materials can attach later.</p>
            </div>
          )}
        </section>
      </section>
    </main>
  );
}

function formatStatus(status: ApplicationStatus) {
  return status.replace(/_/g, " ").replace(/^\w/, (letter) => letter.toUpperCase());
}

function formatDate(value: string | null) {
  if (!value) {
    return "Not set";
  }

  const [year, month, day] = value.split("-");
  if (!year || !month || !day) {
    return value;
  }

  return `${month}/${day}/${year}`;
}
