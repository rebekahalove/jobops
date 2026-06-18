"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import type { CompanyDiscoveryDiagnosticsStatus } from "../lib/command-center-contract";

const COMPANY_DISCOVERY_DIAGNOSTICS_POLL_INTERVAL_MS = 2500;

type PendingDiagnostics = {
  commandPreview?: string | null;
  startedAt?: string | null;
};

export function CompanyDiscoveryDiagnostics({
  apiBasePath = "/api",
  initialRun = null
}: {
  apiBasePath?: string;
  initialRun?: CompanyDiscoveryDiagnosticsStatus | null;
}) {
  const [latestRun, setLatestRun] = useState<CompanyDiscoveryDiagnosticsStatus | null>(initialRun);
  const [pendingRun, setPendingRun] = useState<PendingDiagnostics | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const pendingStartedAtRef = useRef<string | null>(null);

  const loadLatestRun = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await fetch(`${apiBasePath}/companies/discovery-runs/latest`, { cache: "no-store" });
      const payload = (await response.json().catch(() => null)) as unknown;
      if (response.status === 404) {
        if (!pendingStartedAtRef.current) {
          setLatestRun(null);
          setStatusMessage("No recent company discovery diagnostics found.");
        }
        return false;
      }
      if (!response.ok || !isCompanyDiscoveryDiagnosticsStatus(payload)) {
        setStatusMessage(`Company discovery diagnostics could not be loaded (HTTP ${response.status}).`);
        return false;
      }
      if (pendingStartedAtRef.current && !isDiagnosticsAtOrAfter(payload.createdAt, pendingStartedAtRef.current)) {
        setStatusMessage("Waiting for router/source diagnostics...");
        return false;
      }
      pendingStartedAtRef.current = null;
      setLatestRun(payload);
      setPendingRun(null);
      setStatusMessage(null);
      return true;
    } catch {
      setStatusMessage("Company discovery diagnostics API is unavailable.");
      return false;
    } finally {
      setIsLoading(false);
    }
  }, [apiBasePath]);

  useEffect(() => {
    let active = true;

    async function loadIfActive() {
      if (active) {
        await loadLatestRun();
      }
    }

    function handleDiscoveryStarted(event: Event) {
      const detail = event instanceof CustomEvent && isRecord(event.detail) ? event.detail : {};
      const startedAt = new Date().toISOString();
      pendingStartedAtRef.current = startedAt;
      setPendingRun({
        commandPreview: typeof detail.commandPreview === "string" ? detail.commandPreview : null,
        startedAt
      });
      setLatestRun(null);
      setStatusMessage("Waiting for router/source diagnostics...");
    }

    function handleDiscoveryCompleted() {
      loadIfActive();
    }

    loadIfActive();
    window.addEventListener("jobops:company-discovery-started", handleDiscoveryStarted);
    window.addEventListener("jobops:company-discovery-completed", handleDiscoveryCompleted);
    window.addEventListener("jobops:companies-updated", loadIfActive);
    return () => {
      active = false;
      window.removeEventListener("jobops:company-discovery-started", handleDiscoveryStarted);
      window.removeEventListener("jobops:company-discovery-completed", handleDiscoveryCompleted);
      window.removeEventListener("jobops:companies-updated", loadIfActive);
    };
  }, [loadLatestRun]);

  useEffect(() => {
    if (!pendingRun) {
      return;
    }
    let cancelled = false;
    let timeoutId: number | null = null;

    async function pollLatestRun() {
      await loadLatestRun();
      if (!cancelled && pendingStartedAtRef.current) {
        timeoutId = window.setTimeout(pollLatestRun, COMPANY_DISCOVERY_DIAGNOSTICS_POLL_INTERVAL_MS);
      }
    }

    timeoutId = window.setTimeout(pollLatestRun, COMPANY_DISCOVERY_DIAGNOSTICS_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timeoutId) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [loadLatestRun, pendingRun]);

  return <CompanyDiscoveryDiagnosticsPanel isLoading={isLoading} pendingRun={pendingRun} run={latestRun} statusMessage={statusMessage} />;
}

function CompanyDiscoveryDiagnosticsPanel({
  run,
  pendingRun,
  isLoading,
  statusMessage
}: {
  run: CompanyDiscoveryDiagnosticsStatus | null;
  pendingRun: PendingDiagnostics | null;
  isLoading: boolean;
  statusMessage: string | null;
}) {
  const isOpen = Boolean(pendingRun || run?.status === "failed" || run?.status === "running");
  const summaryText = pendingRun
    ? "Company discovery is starting..."
    : run
      ? companyDiscoveryDigest(run)
      : statusMessage || (isLoading ? "Loading company discovery diagnostics..." : "No recent company discovery diagnostics found.");
  const theirStack = run?.theirStack ?? {};
  const firstPartySync = run?.firstPartySync ?? {};
  const providerRows = run?.providerDiagnostics ?? [];

  return (
    <section className="job-discovery-diagnostics company-discovery-diagnostics" aria-labelledby="company-discovery-diagnostics-title">
      <details open={isOpen}>
        <summary>
          <span>
            <strong id="company-discovery-diagnostics-title">Company discovery diagnostics</strong>
            <small>{summaryText}</small>
          </span>
          <span className="diagnostics-toggle-label">Details</span>
        </summary>

        <div className="job-discovery-diagnostics-body">
          {pendingRun ? (
            <>
              <section className="diagnostics-section">
                <h3>Summary</h3>
                <p className="diagnostics-muted">Waiting for router/source diagnostics...</p>
                {pendingRun.commandPreview ? <p className="diagnostics-muted">Command: {pendingRun.commandPreview}</p> : null}
              </section>
              <section className="diagnostics-section">
                <h3>Source timeline / Provider calls</h3>
                <div className="diagnostics-provider-list">
                  <article className="diagnostics-provider-row">
                    <div className="diagnostics-event-header">
                      <strong>Command router</strong>
                      <span>Started</span>
                    </div>
                    <div className="diagnostics-event-meta">
                      <span>Router</span>
                      <span>Command router</span>
                    </div>
                    {pendingRun.commandPreview ? <p className="diagnostics-muted">Request: Command preview: {pendingRun.commandPreview}</p> : null}
                  </article>
                  <article className="diagnostics-provider-row">
                    <div className="diagnostics-event-header">
                      <strong>Company discovery source</strong>
                      <span>Waiting</span>
                    </div>
                    <div className="diagnostics-event-meta">
                      <span>Company source</span>
                      <span>Provider pending</span>
                    </div>
                    <p className="diagnostics-muted">Waiting for TheirStack or model-grounded discovery diagnostics...</p>
                  </article>
                </div>
              </section>
            </>
          ) : run ? (
            <>
              <section className="diagnostics-section">
                <h3>Summary</h3>
                <dl className="diagnostics-grid">
                  <DiagnosticItem label="Status" value={formatStatus(run.status)} />
                  <DiagnosticItem label="Source path" value={formatStatus(run.sourcePath || "unknown")} />
                  <DiagnosticItem label="Source provider" value={formatStatus(run.sourceProvider || "unknown")} />
                  <DiagnosticItem label="Saved companies" value={formatNumber(run.savedCompanyCount) ?? "0"} />
                  <DiagnosticItem label="Linked companies" value={formatNumber(run.linkedCompanyCount) ?? "0"} />
                  <DiagnosticItem label="Duplicates" value={formatNumber(run.duplicateCompanyCount) ?? "0"} />
                  <DiagnosticItem label="Skipped" value={formatNumber(run.skippedCompanyCount) ?? "0"} />
                  <DiagnosticItem label="Zero result reason" value={run.zeroNewCompanyReason ? formatStatus(run.zeroNewCompanyReason) : "None"} />
                </dl>
              </section>

              <section className="diagnostics-section">
                <h3>Routing / planner</h3>
                <dl className="diagnostics-grid">
                  <DiagnosticItem label="Router action" value={formatStatus(run.routerAction || "unknown")} />
                  <DiagnosticItem label="Router confidence" value={formatStatus(run.routerConfidence || "unknown")} />
                  <DiagnosticItem label="Preflight blocked" value={run.companyDiscoveryPreflightBlocked ? "Yes" : "No"} />
                  <DiagnosticItem label="Preflight reason" value={run.preflightReason ? formatStatus(run.preflightReason) : "None"} />
                  <DiagnosticItem label="Search grounding" value={formatBoolean(run.searchGroundingEnabled)} />
                  <DiagnosticItem label="Model" value={[run.modelProvider, run.modelName].filter(Boolean).join(" / ") || "Unknown"} />
                </dl>
              </section>

              <section className="diagnostics-section">
                <h3>Data source</h3>
                <p className="diagnostics-muted">{dataSourceSummary(run)}</p>
                {run.searchQueriesUsed?.length ? <p className="diagnostics-muted">Search queries: {run.searchQueriesUsed.join(", ")}</p> : null}
                {run.discoveryAngles?.length ? <p className="diagnostics-muted">Discovery angles: {run.discoveryAngles.join(", ")}</p> : null}
              </section>

              <section className="diagnostics-section">
                <h3>Source timeline / Provider calls</h3>
                {providerRows.length ? (
                  <div className="diagnostics-provider-list">
                    {providerRows.map((row, index) => (
                      <CompanyProviderDiagnosticRow row={row} key={`${row.stage}-${row.provider}-${row.label}-${index}`} />
                    ))}
                  </div>
                ) : (
                  <p className="diagnostics-muted">
                    {run.diagnosticMessages?.[0] || "No provider-call detail was recorded for this company discovery run."}
                  </p>
                )}
              </section>

              {run.sourcePath === "model_grounded_company_discovery" ? (
                <section className="diagnostics-section">
                  <h3>Model-grounded search</h3>
                  <dl className="diagnostics-grid">
                    <DiagnosticItem label="Model provider" value={formatStatus(run.modelProvider || run.sourceProvider || "unknown")} />
                    <DiagnosticItem label="Model name" value={run.modelName || "Unknown"} />
                    <DiagnosticItem label="Search grounding enabled" value={formatBoolean(run.searchGroundingEnabled)} />
                  </dl>
                </section>
              ) : null}

              <section className="diagnostics-section">
                <h3>TheirStack</h3>
                <dl className="diagnostics-grid">
                  <DiagnosticItem label="Checked" value={formatBoolean(theirStack.checked)} />
                  <DiagnosticItem label="Enabled" value={formatBoolean(theirStack.enabled)} />
                  <DiagnosticItem label="Used" value={formatBoolean(theirStack.used)} />
                  <DiagnosticItem label="Skipped reason" value={theirStack.skippedReason ? formatStatus(theirStack.skippedReason) : "None"} />
                  <DiagnosticItem label="Requested pages" value={formatNumber(theirStack.requestedPages) ?? "0"} />
                  <DiagnosticItem label="Fetched pages" value={formatNumber(theirStack.fetchedPages) ?? "0"} />
                  <DiagnosticItem label="Failed pages" value={formatNumber(theirStack.failedPages) ?? "0"} />
                  <DiagnosticItem label="Raw companies" value={formatNumber(theirStack.rawCompanyCount) ?? "0"} />
                  <DiagnosticItem label="Normalized" value={formatNumber(theirStack.normalizedCompanyCount) ?? "0"} />
                  <DiagnosticItem label="Linked" value={formatNumber(theirStack.linkedCandidateCompanyCount) ?? "0"} />
                </dl>
                {theirStack.requestShape && Object.keys(theirStack.requestShape).length ? (
                  <p className="diagnostics-muted">Request shape: {formatRequestShape(theirStack.requestShape)}</p>
                ) : null}
                {theirStack.errorMessage ? <p className="diagnostics-muted">Error: {theirStack.errorMessage}</p> : null}
              </section>

              <section className="diagnostics-section">
                <h3>First-party verification</h3>
                <dl className="diagnostics-grid">
                  <DiagnosticItem label="Attempted" value={formatBoolean(firstPartySync.attempted)} />
                  <DiagnosticItem label="Providers" value={firstPartySync.providers?.length ? firstPartySync.providers.map(formatStatus).join(", ") : "None"} />
                  <DiagnosticItem label="Greenhouse selected" value={formatList(firstPartySync.greenhouseBoardsSelected)} />
                  <DiagnosticItem label="Greenhouse synced" value={formatList(firstPartySync.greenhouseBoardsSynced)} />
                  <DiagnosticItem label="Ashby selected" value={formatList(firstPartySync.ashbyBoardsSelected)} />
                  <DiagnosticItem label="Ashby synced" value={formatList(firstPartySync.ashbyBoardsSynced)} />
                  <DiagnosticItem label="Completed syncs" value={formatNumber(firstPartySync.completedCount) ?? "0"} />
                  <DiagnosticItem label="Failed syncs" value={formatNumber(firstPartySync.failedCount) ?? "0"} />
                  <DiagnosticItem label="Normalized jobs" value={formatNumber(firstPartySync.normalizedJobCount) ?? "0"} />
                </dl>
                <p className="diagnostics-muted">TheirStack hiring signals are not verified jobs until first-party Greenhouse or Ashby sync runs.</p>
              </section>

              <section className="diagnostics-section">
                <h3>Companies saved</h3>
                {run.companies?.length ? (
                  <div className="diagnostics-provider-list">
                    {run.companies.slice(0, 12).map((company, index) => (
                      <article className="diagnostics-provider-row" key={`${company.name}-${index}`}>
                        <div className="diagnostics-event-header">
                          <strong>{company.name || "Unknown company"}</strong>
                          <span>{formatStatus(company.discoverySource || "unknown")}</span>
                        </div>
                        <p className="diagnostics-muted">
                          Data source: {formatCompanyDataOrigin(company.dataOriginSource, company.dataOriginSourceType)}
                        </p>
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className="diagnostics-muted">No saved-company rows were recorded for this run.</p>
                )}
              </section>
              {run.diagnosticMessages?.length ? (
                <section className="diagnostics-section">
                  <h3>Diagnostic messages</h3>
                  {run.diagnosticMessages.map((message, index) => (
                    <p className="diagnostics-muted" key={`${message}-${index}`}>
                      {message}
                    </p>
                  ))}
                </section>
              ) : null}
            </>
          ) : (
            <section className="diagnostics-section">
              <h3>Summary</h3>
              <p className="diagnostics-muted">{statusMessage || "Loading latest company discovery diagnostics..."}</p>
            </section>
          )}
        </div>
      </details>
    </section>
  );
}

function CompanyProviderDiagnosticRow({ row }: { row: NonNullable<CompanyDiscoveryDiagnosticsStatus["providerDiagnostics"]>[number] }) {
  const requestItems = formatDiagnosticSummaryItems(row.requestSummary);
  const resultItems = formatDiagnosticSummaryItems(row.resultSummary);
  const error = formatDiagnosticError(row.error);

  return (
    <article className="diagnostics-provider-row">
      <div className="diagnostics-event-header">
        <strong>{row.label || formatStatus(row.provider || "Provider call")}</strong>
        <span>{formatStatus(row.status || "unknown")}</span>
      </div>
      <div className="diagnostics-event-meta">
        <span>{formatStatus(row.stage || "unknown stage")}</span>
        <span>{formatStatus(row.provider || "unknown provider")}</span>
      </div>
      {requestItems.length ? <p className="diagnostics-muted">Request: {requestItems.join("; ")}</p> : null}
      {resultItems.length ? <p className="diagnostics-muted">Result: {resultItems.join("; ")}</p> : null}
      {error ? <p className="diagnostics-muted">Error: {error}</p> : null}
    </article>
  );
}

function DiagnosticItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value || "None"}</dd>
    </div>
  );
}

function companyDiscoveryDigest(run: CompanyDiscoveryDiagnosticsStatus) {
  if (run.theirStack?.checked && !run.theirStack.enabled) {
    return `Latest company discovery: TheirStack unavailable - ${formatStatus(run.theirStack.skippedReason || "missing_api_key")}.`;
  }
  if (run.theirStack?.used) {
    return `Latest company discovery: TheirStack checked ${formatNumber(run.theirStack.rawCompanyCount) ?? "0"} companies, linked ${formatNumber(run.linkedCompanyCount) ?? "0"} leads, synced ${formatNumber(run.firstPartySync?.completedCount) ?? "0"} first-party boards.`;
  }
  if (run.sourcePath === "model_grounded_company_discovery") {
    return `Latest company discovery: ${formatStatus(run.sourceProvider || "model-grounded")} model-grounded discovery saved ${formatNumber(run.savedCompanyCount) ?? "0"} companies.`;
  }
  if (run.status === "failed") {
    return "Latest company discovery failed.";
  }
  return `Latest company discovery: ${formatStatus(run.sourcePath || "unknown")} saved ${formatNumber(run.savedCompanyCount) ?? "0"} companies.`;
}

function dataSourceSummary(run: CompanyDiscoveryDiagnosticsStatus) {
  if (run.theirStack?.used) {
    return "Company data came from TheirStack company search; first-party board sync is shown separately.";
  }
  if (run.sourcePath === "model_grounded_company_discovery") {
    return `Company data came from model-grounded discovery${run.searchGroundingEnabled === true ? " with search grounding enabled" : ""}.`;
  }
  return "Company data source details are limited for this run.";
}

function formatCompanyDataOrigin(source?: string | null, type?: string | null) {
  if (!source || source === "unknown") {
    return "Unknown";
  }
  if (source === "theirstack") {
    return "TheirStack company search";
  }
  if (source === "user") {
    return "User-entered";
  }
  if (source === "gemini_search_grounding") {
    return "Gemini search grounding";
  }
  return displayUrlHost(source) || formatStatus(type || source);
}

function formatRequestShape(value: Record<string, unknown>) {
  return Object.entries(value)
    .slice(0, 8)
    .map(([key, item]) => `${formatStatus(key)}=${formatDiagnosticValue(item)}`)
    .join(", ");
}

function formatDiagnosticSummaryItems(value?: Record<string, unknown> | null) {
  if (!value) {
    return [];
  }
  return Object.entries(value)
    .filter(([, item]) => item !== null && item !== undefined && item !== "")
    .slice(0, 10)
    .map(([key, item]) => `${formatStatus(key)}: ${formatDiagnosticValue(item)}`);
}

function formatDiagnosticValue(value: unknown): string {
  if (Array.isArray(value)) {
    return value.length ? value.slice(0, 6).map((item) => formatDiagnosticValue(item)).join(", ") : "None";
  }
  if (isRecord(value)) {
    const entries = Object.entries(value)
      .filter(([, item]) => item !== null && item !== undefined && item !== "")
      .slice(0, 6)
      .map(([key, item]) => `${formatStatus(key)}=${formatDiagnosticValue(item)}`);
    return entries.length ? entries.join(", ") : "None";
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  if (typeof value === "number") {
    return formatNumber(value) ?? String(value);
  }
  return String(value);
}

function formatDiagnosticError(value: unknown): string | null {
  if (!value) {
    return null;
  }
  if (typeof value === "string") {
    return value;
  }
  if (isRecord(value)) {
    const message = value.message;
    if (typeof message === "string" && message.trim()) {
      return message;
    }
    const items = formatDiagnosticSummaryItems(value);
    return items.length ? items.join("; ") : null;
  }
  return null;
}

function formatList(values?: string[] | null) {
  return values?.length ? values.join(", ") : "None";
}

function formatBoolean(value?: boolean | null) {
  if (value === true) {
    return "Yes";
  }
  if (value === false) {
    return "No";
  }
  return "Unknown";
}

function formatNumber(value?: number | null) {
  return typeof value === "number" ? new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(value) : null;
}

function formatStatus(value?: string | null) {
  if (!value) {
    return "Unknown";
  }
  return value
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/_/g, " ")
    .replace(/^\w/, (letter) => letter.toUpperCase());
}

function displayUrlHost(value?: string | null) {
  if (!value) {
    return null;
  }
  try {
    return new URL(value).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

function isCompanyDiscoveryDiagnosticsStatus(value: unknown): value is CompanyDiscoveryDiagnosticsStatus {
  return isRecord(value) && typeof value.id === "string" && typeof value.status === "string";
}

function isDiagnosticsAtOrAfter(createdAt: string | null | undefined, startedAt: string) {
  if (!createdAt) {
    return false;
  }
  const createdTime = Date.parse(createdAt);
  const startedTime = Date.parse(startedAt);
  if (!Number.isFinite(createdTime) || !Number.isFinite(startedTime)) {
    return true;
  }
  return createdTime >= startedTime - 1000;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
