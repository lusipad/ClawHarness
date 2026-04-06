"use client";

import { useEffect, useMemo, useState } from "react";

type RunSummary = {
  run_id: string;
  provider_type: string;
  task_id: string;
  task_key: string;
  session_id: string;
  executor_type: string;
  status: string;
  repo_id: string | null;
  branch_name: string | null;
  workspace_path: string | null;
  pr_id: string | null;
  ci_run_id: string | null;
  chat_thread_id: string | null;
  retry_count: number;
  started_at: string | null;
  updated_at: string | null;
  last_error: string | null;
};

type RunListPayload = {
  summary?: {
    total_runs: number;
    active_runs: number;
    terminal_runs: number;
    status_counts: Record<string, number>;
  };
  runs: RunSummary[];
};

type AuditEntry = {
  id: number;
  run_id: string;
  event_type: string;
  payload: unknown;
  created_at: string;
};

type AuditPayload = {
  run: RunSummary;
  audit: AuditEntry[];
};

type GraphEntry = {
  id?: number;
  run_id?: string;
  stage?: string;
  artifact_type?: string;
  artifact_name?: string;
  path?: string | null;
  external_url?: string | null;
  payload?: unknown;
  created_at: string;
};

type RelationSummary = {
  relation_type: string;
  agent_role: string | null;
  created_at: string;
};

type ChildRunGraph = RelationSummary & {
  run: RunSummary;
  latest_checkpoint: GraphEntry | null;
  latest_conclusion: {
    artifact_name?: string;
    created_at: string;
    payload?: unknown;
  } | null;
  artifact_count: number;
  checkpoint_count: number;
};

type GraphPayload = {
  run: RunSummary;
  parent_run: RunSummary | null;
  parent_relation?: RelationSummary | null;
  child_runs: ChildRunGraph[];
  checkpoints: GraphEntry[];
  artifacts: GraphEntry[];
};

const STATUS_OPTIONS = [
  "",
  "claimed",
  "planning",
  "coding",
  "opening_pr",
  "awaiting_ci",
  "awaiting_review",
  "awaiting_human",
  "completed",
  "failed",
  "cancelled",
];

function formatTime(value: string | null) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", { hour12: false });
}

function payloadToString(payload: unknown) {
  if (payload == null) {
    return "";
  }
  if (typeof payload === "string") {
    return payload;
  }
  try {
    return JSON.stringify(payload, null, 2);
  } catch {
    return String(payload);
  }
}

function payloadToObject(payload: unknown) {
  if (payload && typeof payload === "object" && !Array.isArray(payload)) {
    return payload as Record<string, unknown>;
  }
  return null;
}

function getConclusionSummary(payload: unknown) {
  const record = payloadToObject(payload);
  if (!record) {
    return null;
  }
  const summary = record.summary;
  return typeof summary === "string" && summary.trim() ? summary : null;
}

function getConclusionStatus(payload: unknown) {
  const record = payloadToObject(payload);
  if (!record) {
    return null;
  }
  const status = record.status;
  return typeof status === "string" && status.trim() ? status : null;
}

export default function ClawHarnessPage() {
  const [status, setStatus] = useState("");
  const [taskKey, setTaskKey] = useState("");
  const [data, setData] = useState<RunListPayload | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [audit, setAudit] = useState<AuditPayload | null>(null);
  const [graph, setGraph] = useState<GraphPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [auditLoading, setAuditLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [graphError, setGraphError] = useState<string | null>(null);

  const queryString = useMemo(() => {
    const query = new URLSearchParams();
    query.set("limit", "50");
    if (status) {
      query.set("status", status);
    }
    if (taskKey.trim()) {
      query.set("task_key", taskKey.trim());
    }
    return query.toString();
  }, [status, taskKey]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch(`/api/clawharness/runs?${queryString}`, { cache: "no-store" })
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload?.detail || payload?.error || "加载失败");
        }
        return payload as RunListPayload;
      })
      .then((payload) => {
        if (cancelled) {
          return;
        }
        setData(payload);
        const nextSelected = payload.runs[0]?.run_id ?? null;
        setSelectedRunId((current) => (current && payload.runs.some((run) => run.run_id === current) ? current : nextSelected));
      })
      .catch((fetchError) => {
        if (!cancelled) {
          setError(fetchError instanceof Error ? fetchError.message : String(fetchError));
          setData(null);
          setSelectedRunId(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [queryString]);

  useEffect(() => {
    if (!selectedRunId) {
      setAudit(null);
      setGraph(null);
      setAuditLoading(false);
      setAuditError(null);
      return;
    }
    let cancelled = false;
    setAuditLoading(true);
    setAuditError(null);
    setGraphError(null);
    const loadAudit = fetch(`/api/clawharness/runs/${encodeURIComponent(selectedRunId)}/audit`, { cache: "no-store" })
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload?.detail || payload?.error || "审计加载失败");
        }
        return payload as AuditPayload;
      })
      .then((auditPayload) => {
        if (!cancelled) {
          setAudit(auditPayload);
        }
      })
      .catch((fetchError) => {
        if (!cancelled) {
          setAuditError(fetchError instanceof Error ? fetchError.message : String(fetchError));
          setAudit(null);
        }
      });
    const loadGraph = fetch(`/api/clawharness/runs/${encodeURIComponent(selectedRunId)}/graph`, { cache: "no-store" })
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload?.detail || payload?.error || "图谱加载失败");
        }
        return payload as GraphPayload;
      })
      .then((graphPayload) => {
        if (!cancelled) {
          setGraph(graphPayload);
        }
      })
      .catch((fetchError) => {
        if (!cancelled) {
          setGraphError(fetchError instanceof Error ? fetchError.message : String(fetchError));
          setGraph(null);
        }
      });

    Promise.allSettled([loadAudit, loadGraph]).finally(() => {
      if (!cancelled) {
        setAuditLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [selectedRunId]);

  return (
    <div className="min-h-screen bg-[var(--bg)] text-[var(--text)]">
      <div className="mx-auto max-w-7xl px-4 py-6 md:px-8">
        <div className="mb-6 border border-[var(--border)] bg-[var(--panel)]/90 p-5 shadow-[0_12px_32px_rgba(0,0,0,0.16)]">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <div className="text-xs uppercase tracking-[0.28em] text-[var(--text-muted)]">ClawHarness</div>
              <h1 className="mt-2 text-3xl font-semibold">运行态 Bot View</h1>
              <p className="mt-2 max-w-3xl text-sm text-[var(--text-muted)]">
                这个页面通过 sidecar 内部代理读取 ClawHarness bridge 的只读 API，用于查看任务运行、状态迁移和审计链。
              </p>
            </div>
            <a
              href="/"
              className="inline-flex items-center justify-center border border-[var(--accent)]/35 bg-[var(--accent)]/12 px-4 py-2 text-sm font-medium text-[var(--accent)] transition-colors hover:bg-[var(--accent)]/18"
            >
              返回 OpenClaw 总览
            </a>
          </div>
          <div className="mt-5 grid gap-4 md:grid-cols-4">
            <label className="flex flex-col gap-2 text-sm">
              <span className="text-[var(--text-muted)]">状态过滤</span>
              <select
                value={status}
                onChange={(event) => setStatus(event.target.value)}
                className="border border-[var(--border)] bg-[var(--bg)] px-3 py-2 outline-none"
              >
                {STATUS_OPTIONS.map((item) => (
                  <option key={item || "all"} value={item}>
                    {item || "全部"}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-2 text-sm md:col-span-2">
              <span className="text-[var(--text-muted)]">任务键过滤</span>
              <input
                value={taskKey}
                onChange={(event) => setTaskKey(event.target.value)}
                placeholder="例如 AB#123 或具体 task_key"
                className="border border-[var(--border)] bg-[var(--bg)] px-3 py-2 outline-none"
              />
            </label>
            <div className="grid grid-cols-3 gap-2 text-sm">
              <div className="border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">总 Run</div>
                <div className="mt-1 text-xl font-semibold">{data?.summary?.total_runs ?? "-"}</div>
              </div>
              <div className="border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">活跃</div>
                <div className="mt-1 text-xl font-semibold">{data?.summary?.active_runs ?? "-"}</div>
              </div>
              <div className="border border-[var(--border)] bg-[var(--bg)] px-3 py-2">
                <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">终态</div>
                <div className="mt-1 text-xl font-semibold">{data?.summary?.terminal_runs ?? "-"}</div>
              </div>
            </div>
          </div>
        </div>

        <div className="grid gap-6 xl:grid-cols-[1.2fr_1fr]">
          <section className="border border-[var(--border)] bg-[var(--panel)]/92 p-4 shadow-[0_12px_32px_rgba(0,0,0,0.16)]">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold">最近运行</h2>
              <div className="text-xs text-[var(--text-muted)]">按 `updated_at` 倒序，最多 50 条</div>
            </div>
            {loading ? (
              <div className="py-8 text-sm text-[var(--text-muted)]">正在加载运行列表...</div>
            ) : error ? (
              <div className="border border-amber-400/30 bg-amber-500/10 p-4 text-sm text-amber-200">{error}</div>
            ) : data && data.runs.length > 0 ? (
              <div className="space-y-3">
                {data.runs.map((run) => {
                  const selected = run.run_id === selectedRunId;
                  return (
                    <button
                      key={run.run_id}
                      type="button"
                      onClick={() => setSelectedRunId(run.run_id)}
                      className={`w-full border p-4 text-left transition-colors ${
                        selected
                          ? "border-[var(--accent)] bg-[var(--accent)]/12"
                          : "border-[var(--border)] bg-[var(--bg)]/86 hover:bg-[var(--panel)]"
                      }`}
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold">{run.task_key}</span>
                        <span className="border border-[var(--border)] px-2 py-0.5 text-[11px] uppercase tracking-[0.18em] text-[var(--text-muted)]">
                          {run.status}
                        </span>
                        <span className="text-xs text-[var(--text-muted)]">{run.run_id}</span>
                      </div>
                      <div className="mt-3 grid gap-2 text-sm md:grid-cols-2">
                        <div>
                          <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">分支 / PR / CI</div>
                          <div className="mt-1 break-all">
                            {run.branch_name || "-"}
                            <br />
                            PR: {run.pr_id || "-"} / CI: {run.ci_run_id || "-"}
                          </div>
                        </div>
                        <div>
                          <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">最近更新时间</div>
                          <div className="mt-1">{formatTime(run.updated_at)}</div>
                          {run.last_error ? <div className="mt-1 text-rose-300">{run.last_error}</div> : null}
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="py-8 text-sm text-[var(--text-muted)]">当前没有匹配的运行记录。</div>
            )}
          </section>

          <section className="border border-[var(--border)] bg-[var(--panel)]/92 p-4 shadow-[0_12px_32px_rgba(0,0,0,0.16)]">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold">审计时间线</h2>
              <div className="text-xs text-[var(--text-muted)]">
                {selectedRunId ? `当前 Run: ${selectedRunId}` : "请选择左侧运行"}
              </div>
            </div>
            {auditLoading ? (
              <div className="py-8 text-sm text-[var(--text-muted)]">正在加载审计链...</div>
            ) : auditError ? (
              <div className="border border-amber-400/30 bg-amber-500/10 p-4 text-sm text-amber-200">{auditError}</div>
            ) : audit ? (
              <div className="space-y-3">
                {graph ? (
                  <div className="border border-[var(--border)] bg-[var(--bg)]/86 p-4 text-sm">
                    <div className="grid gap-3 md:grid-cols-2">
                      <div>
                        <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">Parent / Children</div>
                        <div className="mt-2">
                          Parent: {graph.parent_run ? graph.parent_run.run_id : "-"}
                          <br />
                          Children:{" "}
                          {graph.child_runs.length > 0
                            ? graph.child_runs
                                .map((item) => `${item.agent_role || item.relation_type}:${item.run.run_id}`)
                                .join(", ")
                            : "-"}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">Checkpoints / Artifacts</div>
                        <div className="mt-2">
                          Checkpoints: {graph.checkpoints.length}
                          <br />
                          Artifacts: {graph.artifacts.length}
                        </div>
                      </div>
                    </div>
                    {graph.child_runs.length > 0 ? (
                      <div className="mt-4">
                        <div className="mb-2 text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">Agent 子 Run</div>
                        <div className="space-y-2">
                          {graph.child_runs.map((child) => {
                            const conclusionStatus = getConclusionStatus(child.latest_conclusion?.payload);
                            const conclusionSummary = getConclusionSummary(child.latest_conclusion?.payload);
                            return (
                              <div key={child.run.run_id} className="border border-[var(--border)] px-3 py-3">
                                <div className="flex flex-wrap items-center gap-2">
                                  <span className="font-medium">{child.agent_role || child.relation_type}</span>
                                  <span className="border border-[var(--border)] px-2 py-0.5 text-[11px] uppercase tracking-[0.18em] text-[var(--text-muted)]">
                                    {child.run.status}
                                  </span>
                                  {conclusionStatus ? (
                                    <span className="text-xs text-[var(--accent)]">{conclusionStatus}</span>
                                  ) : null}
                                  <span className="text-xs text-[var(--text-muted)]">{child.run.run_id}</span>
                                </div>
                                <div className="mt-2 text-xs text-[var(--text-muted)]">
                                  Relation: {child.relation_type} | Checkpoints: {child.checkpoint_count} | Artifacts: {child.artifact_count}
                                </div>
                                {conclusionSummary ? <div className="mt-2 text-sm">{conclusionSummary}</div> : null}
                                {child.latest_checkpoint ? (
                                  <div className="mt-2 text-xs text-[var(--text-muted)]">
                                    Latest checkpoint: {child.latest_checkpoint.stage || "-"} / {formatTime(child.latest_checkpoint.created_at)}
                                  </div>
                                ) : null}
                                {child.run.last_error ? <div className="mt-2 text-sm text-rose-300">{child.run.last_error}</div> : null}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    ) : null}
                    {graph.checkpoints.length > 0 ? (
                      <div className="mt-4">
                        <div className="mb-2 text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">Latest Checkpoints</div>
                        <div className="space-y-2">
                          {graph.checkpoints.map((checkpoint) => (
                            <div key={`checkpoint-${checkpoint.id ?? checkpoint.created_at}`} className="border border-[var(--border)] px-3 py-2">
                              <div className="flex items-center justify-between gap-2">
                                <span className="font-medium">{checkpoint.stage}</span>
                                <span className="text-xs text-[var(--text-muted)]">{formatTime(checkpoint.created_at)}</span>
                              </div>
                              {checkpoint.payload ? (
                                <pre className="mt-2 overflow-auto border border-[var(--border)] bg-[#0b0f14] p-3 text-xs leading-5 text-[#dbe7f3]">
                                  {payloadToString(checkpoint.payload)}
                                </pre>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    {graph.artifacts.length > 0 ? (
                      <div className="mt-4">
                        <div className="mb-2 text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">Artifacts</div>
                        <div className="space-y-2">
                          {graph.artifacts.map((artifact) => (
                            <div key={`artifact-${artifact.id ?? artifact.created_at}`} className="border border-[var(--border)] px-3 py-2">
                              <div className="flex items-center justify-between gap-2">
                                <span className="font-medium">{artifact.artifact_type} / {artifact.artifact_name}</span>
                                <span className="text-xs text-[var(--text-muted)]">{formatTime(artifact.created_at)}</span>
                              </div>
                              {artifact.path ? <div className="mt-1 text-xs text-[var(--text-muted)]">{artifact.path}</div> : null}
                              {artifact.payload ? (
                                <pre className="mt-2 overflow-auto border border-[var(--border)] bg-[#0b0f14] p-3 text-xs leading-5 text-[#dbe7f3]">
                                  {payloadToString(artifact.payload)}
                                </pre>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </div>
                ) : graphError ? (
                  <div className="border border-amber-400/30 bg-amber-500/10 p-4 text-sm text-amber-200">{graphError}</div>
                ) : null}
                <div className="border border-[var(--border)] bg-[var(--bg)]/86 p-4 text-sm">
                  <div className="flex flex-wrap gap-3">
                    <div>任务：{audit.run.task_key}</div>
                    <div>状态：{audit.run.status}</div>
                    <div>会话：{audit.run.session_id}</div>
                  </div>
                  <div className="mt-2 text-[var(--text-muted)]">工作区：{audit.run.workspace_path || "-"}</div>
                </div>
                {audit.audit.length > 0 ? (
                  audit.audit.map((entry) => (
                    <div key={entry.id} className="border border-[var(--border)] bg-[var(--bg)]/86 p-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="font-medium">{entry.event_type}</div>
                        <div className="text-xs text-[var(--text-muted)]">{formatTime(entry.created_at)}</div>
                      </div>
                      {entry.payload ? (
                        <pre className="mt-3 overflow-auto border border-[var(--border)] bg-[#0b0f14] p-3 text-xs leading-5 text-[#dbe7f3]">
                          {payloadToString(entry.payload)}
                        </pre>
                      ) : null}
                    </div>
                  ))
                ) : (
                  <div className="py-8 text-sm text-[var(--text-muted)]">该 Run 还没有审计事件。</div>
                )}
              </div>
            ) : (
              <div className="py-8 text-sm text-[var(--text-muted)]">请选择左侧运行以查看审计链。</div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
