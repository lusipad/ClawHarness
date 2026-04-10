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

type CommandPayload = {
  ok: boolean;
  command: string;
  run_id: string | null;
  response_type: string;
  text: string;
  attachments?: Array<{ title?: string }>;
};

type CompletionSummary = {
  prCompleted: AuditEntry | null;
  prPayload: Record<string, unknown> | null;
  taskSyncEvent: AuditEntry | null;
  taskSyncPayload: Record<string, unknown> | null;
  taskSyncResult: "completed" | "failed" | "not_attempted";
};

type InterventionAction = {
  kind: "pause" | "resume" | "escalate" | "add-context";
  title: string;
  createdAt: string;
  detail: string | null;
  userLabel: string | null;
  providerType: string | null;
  targetRunId: string | null;
};

type InterventionSummary = {
  stateLabel: string;
  stateTone: "neutral" | "info" | "warning" | "success" | "danger";
  recommendation: string;
  blockReason: string | null;
  threadId: string | null;
  latestAction: InterventionAction | null;
  recentActions: InterventionAction[];
  latestContextText: string | null;
  contextCount: number;
  latestImageSummary: string | null;
  latestImageError: string | null;
  canPause: boolean;
  canResume: boolean;
  canEscalate: boolean;
  canAddContext: boolean;
  actionHint: string;
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

function latestAuditEntry(entries: AuditEntry[], ...eventTypes: string[]) {
  return [...entries].reverse().find((entry) => eventTypes.includes(entry.event_type)) ?? null;
}

function getDisplayValue(value: unknown) {
  if (typeof value === "string" && value.trim()) {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return null;
}

function readField(record: Record<string, unknown> | null, key: string) {
  if (!record) {
    return null;
  }
  return getDisplayValue(record[key]);
}

function latestCheckpoint(entries: GraphEntry[], ...stages: string[]) {
  return [...entries].reverse().find((entry) => entry.stage && stages.includes(entry.stage)) ?? null;
}

function snippet(value: string | null, limit = 120) {
  if (!value) {
    return null;
  }
  if (value.length <= limit) {
    return value;
  }
  return `${value.slice(0, limit - 1)}...`;
}

function buildCheckpointAction(checkpoint: GraphEntry): InterventionAction | null {
  const payload = payloadToObject(checkpoint.payload);
  if (checkpoint.stage === "chat_pause") {
    const command = readField(payload, "command") === "escalate" ? "escalate" : "pause";
    return {
      kind: command,
      title: command === "escalate" ? "升级为人工介入" : "暂停运行",
      createdAt: checkpoint.created_at,
      detail: readField(payload, "reason"),
      userLabel: readField(payload, "user_label"),
      providerType: readField(payload, "provider_type"),
      targetRunId: readField(payload, "target_run_id"),
    };
  }
  if (checkpoint.stage === "chat_resume") {
    return {
      kind: "resume",
      title: "恢复运行",
      createdAt: checkpoint.created_at,
      detail: readField(payload, "restored_status"),
      userLabel: readField(payload, "user_label"),
      providerType: readField(payload, "provider_type"),
      targetRunId: null,
    };
  }
  return null;
}

function buildContextAction(entry: AuditEntry): InterventionAction | null {
  if (entry.event_type !== "chat_context_added") {
    return null;
  }
  const payload = payloadToObject(entry.payload);
  return {
    kind: "add-context",
    title: "追加上下文",
    createdAt: entry.created_at,
    detail: readField(payload, "text"),
    userLabel: readField(payload, "user_label"),
    providerType: readField(payload, "provider_type"),
    targetRunId: readField(payload, "target_run_id"),
  };
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
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [commandLoading, setCommandLoading] = useState(false);
  const [commandError, setCommandError] = useState<string | null>(null);
  const [commandResult, setCommandResult] = useState<string | null>(null);
  const [contextInput, setContextInput] = useState("");

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

  const completionSummary = useMemo<CompletionSummary | null>(() => {
    if (!audit) {
      return null;
    }
    const prCompleted = latestAuditEntry(audit.audit, "pr_completed");
    const prPayload = payloadToObject(prCompleted?.payload);
    const taskSyncEvent = latestAuditEntry(
      audit.audit,
      "task_completion_synced",
      "task_completion_sync_failed",
    );
    const taskSyncPayload =
      payloadToObject(taskSyncEvent?.payload) || payloadToObject(prPayload?.task_sync);
    const taskSyncResult =
      taskSyncEvent?.event_type === "task_completion_sync_failed" || readField(taskSyncPayload, "result") === "failed"
        ? "failed"
        : taskSyncPayload
          ? "completed"
          : "not_attempted";
    return {
      prCompleted,
      prPayload,
      taskSyncEvent,
      taskSyncPayload,
      taskSyncResult,
    };
  }, [audit]);

  const interventionSummary = useMemo<InterventionSummary | null>(() => {
    if (!audit) {
      return null;
    }

    const checkpoints = graph?.checkpoints ?? [];
    const latestPause = latestCheckpoint(checkpoints, "chat_pause");
    const latestCommand = latestAuditEntry(audit.audit, "chat_command_received");
    const latestContext = latestAuditEntry(audit.audit, "chat_context_added");
    const latestImageCompleted = latestAuditEntry(audit.audit, "image_analysis_completed");
    const latestImageFailed = latestAuditEntry(audit.audit, "image_analysis_failed");
    const contextEntries = audit.audit.filter((entry) => entry.event_type === "chat_context_added");
    const recentActions = [
      ...checkpoints
        .map((entry) => buildCheckpointAction(entry))
        .filter((entry): entry is InterventionAction => Boolean(entry)),
      ...audit.audit
        .map((entry) => buildContextAction(entry))
        .filter((entry): entry is InterventionAction => Boolean(entry)),
    ]
      .sort((left, right) => right.createdAt.localeCompare(left.createdAt))
      .slice(0, 5);

    const terminal = ["completed", "failed", "cancelled"].includes(audit.run.status);
    const isAwaitingHuman = audit.run.status === "awaiting_human";
    let stateLabel = "自动执行中";
    let stateTone: InterventionSummary["stateTone"] = "info";
    let recommendation = "当前处于自动闭环阶段，可补充上下文，必要时手动暂停或升级。";
    if (isAwaitingHuman) {
      stateLabel = "等待人工处理";
      stateTone = "warning";
      recommendation = "当前 run 已被人工暂停或升级，建议先判断阻塞原因，再恢复执行或继续补充上下文。";
    } else if (audit.run.status === "completed") {
      stateLabel = "闭环已完成";
      stateTone = "success";
      recommendation = "运行已经收口，建议只读检查审计、PR 与任务同步结果。";
    } else if (audit.run.status === "failed") {
      stateLabel = "运行失败";
      stateTone = "danger";
      recommendation = "先查看失败原因与最近上下文，再决定是否人工接管或重新发起后续操作。";
    } else if (audit.run.status === "cancelled") {
      stateLabel = "运行已取消";
      stateTone = "neutral";
      recommendation = "当前 run 已终止，不建议继续通过控制面追加操作。";
    }

    const blockReason =
      audit.run.last_error || readField(payloadToObject(latestPause?.payload), "reason");
    const threadId =
      audit.run.chat_thread_id || readField(payloadToObject(latestCommand?.payload), "conversation_id");

    let actionHint = "可执行暂停、升级和追加上下文。";
    if (terminal) {
      actionHint = "当前 run 已终态，建议只读查看；控制动作默认不再开放。";
    } else if (isAwaitingHuman) {
      actionHint = "当前 run 正在等待人工，优先使用“恢复运行”或继续补充上下文。";
    }

    return {
      stateLabel,
      stateTone,
      recommendation,
      blockReason,
      threadId,
      latestAction: recentActions[0] ?? null,
      recentActions,
      latestContextText: readField(payloadToObject(latestContext?.payload), "text"),
      contextCount: contextEntries.length,
      latestImageSummary: readField(payloadToObject(latestImageCompleted?.payload), "summary"),
      latestImageError: readField(payloadToObject(latestImageFailed?.payload), "error"),
      canPause: !terminal && !isAwaitingHuman,
      canResume: isAwaitingHuman,
      canEscalate: !terminal && !isAwaitingHuman,
      canAddContext: !terminal,
      actionHint,
    };
  }, [audit, graph]);

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
  }, [queryString, refreshNonce]);

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
  }, [selectedRunId, refreshNonce]);

  async function runCommand(command: string, body: Record<string, unknown> = {}) {
    if (!selectedRunId) {
      return;
    }
    setCommandLoading(true);
    setCommandError(null);
    setCommandResult(null);
    try {
      const response = await fetch(`/api/clawharness/runs/${encodeURIComponent(selectedRunId)}/command`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          command,
          user_label: "bot-view",
          ...body,
        }),
      });
      const payload = (await response.json()) as CommandPayload & { detail?: string; error?: string };
      if (!response.ok || !payload.ok) {
        throw new Error(payload.text || payload.detail || payload.error || "命令执行失败");
      }
      setCommandResult(payload.text);
      if (command === "add-context") {
        setContextInput("");
      }
      setRefreshNonce((value) => value + 1);
    } catch (fetchError) {
      setCommandError(fetchError instanceof Error ? fetchError.message : String(fetchError));
    } finally {
      setCommandLoading(false);
    }
  }

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
                <div className="border border-[var(--border)] bg-[var(--bg)]/86 p-4 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">Completion Summary</div>
                      <div className="mt-1 text-[var(--text-muted)]">聚合展示 PR 合并后的 run 完成与 provider 任务回写结果。</div>
                    </div>
                    <div
                      className={`border px-2 py-1 text-[11px] uppercase tracking-[0.18em] ${
                        completionSummary?.prCompleted
                          ? "border-emerald-400/35 bg-emerald-500/10 text-emerald-100"
                          : "border-[var(--border)] text-[var(--text-muted)]"
                      }`}
                    >
                      {completionSummary?.prCompleted ? "闭环已到达" : "等待合并"}
                    </div>
                  </div>
                  {completionSummary?.prCompleted ? (
                    <div className="mt-4 grid gap-3 lg:grid-cols-2">
                      <div className="border border-[var(--border)] px-3 py-3">
                        <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">PR Merge</div>
                        <div className="mt-2 text-sm">
                          PR: {readField(completionSummary.prPayload, "pr_id") || audit.run.pr_id || "-"}
                          <br />
                          状态: {readField(completionSummary.prPayload, "status") || "-"} / Merge:{" "}
                          {readField(completionSummary.prPayload, "merge_status") || "-"}
                          <br />
                          时间: {formatTime(readField(completionSummary.prPayload, "closed_date"))}
                        </div>
                        <div className="mt-2 text-xs text-[var(--text-muted)]">
                          审计事件：{completionSummary.prCompleted.event_type} / {formatTime(completionSummary.prCompleted.created_at)}
                        </div>
                      </div>
                      <div className="border border-[var(--border)] px-3 py-3">
                        <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">Merge Commit</div>
                        <div className="mt-2 break-all text-sm">
                          {readField(completionSummary.prPayload, "merge_commit") || "-"}
                        </div>
                        <div className="mt-2 text-xs text-[var(--text-muted)]">
                          {readField(completionSummary.prPayload, "source_branch") || "-"} →{" "}
                          {readField(completionSummary.prPayload, "target_branch") || "-"}
                        </div>
                      </div>
                      <div className="border border-[var(--border)] px-3 py-3">
                        <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">Task Sync</div>
                        <div
                          className={`mt-2 inline-flex border px-2 py-1 text-[11px] uppercase tracking-[0.18em] ${
                            completionSummary.taskSyncResult === "failed"
                              ? "border-amber-400/35 bg-amber-500/10 text-amber-100"
                              : completionSummary.taskSyncResult === "completed"
                                ? "border-emerald-400/35 bg-emerald-500/10 text-emerald-100"
                                : "border-[var(--border)] text-[var(--text-muted)]"
                          }`}
                        >
                          {completionSummary.taskSyncResult === "failed"
                            ? "回写失败"
                            : completionSummary.taskSyncResult === "completed"
                              ? "已回写"
                              : "未执行"}
                        </div>
                        <div className="mt-2 text-sm">
                          结果: {readField(completionSummary.taskSyncPayload, "result") || "-"}
                          <br />
                          任务状态: {readField(completionSummary.taskSyncPayload, "task_state") || "-"}
                        </div>
                        <div className="mt-2 text-xs text-[var(--text-muted)]">
                          {completionSummary.taskSyncEvent
                            ? `${completionSummary.taskSyncEvent.event_type} / ${formatTime(completionSummary.taskSyncEvent.created_at)}`
                            : "当前 provider 未记录单独的任务同步事件"}
                        </div>
                      </div>
                      <div className="border border-[var(--border)] px-3 py-3">
                        <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">Sync Notes</div>
                        <div className="mt-2 break-all text-sm">
                          {readField(completionSummary.taskSyncPayload, "error") || "任务同步失败不会回滚 run completed，只记审计并继续闭环。"}
                        </div>
                        <div className="mt-2 text-xs text-[var(--text-muted)]">
                          Task ID: {readField(completionSummary.taskSyncPayload, "task_id") || audit.run.task_id || "-"}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="mt-4 text-sm text-[var(--text-muted)]">
                      当前 run 还没有记录到 `pr_completed` 审计事件，说明尚未到达 PR 合并闭环。
                    </div>
                  )}
                </div>
                <div className="border border-[var(--border)] bg-[var(--bg)]/86 p-4 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">Intervention Status</div>
                      <div className="mt-1 text-[var(--text-muted)]">聚合当前 run 的人工介入态势、最近操作与上下文补充结果。</div>
                    </div>
                    <div
                      className={`border px-2 py-1 text-[11px] uppercase tracking-[0.18em] ${
                        interventionSummary?.stateTone === "success"
                          ? "border-emerald-400/35 bg-emerald-500/10 text-emerald-100"
                          : interventionSummary?.stateTone === "warning"
                            ? "border-amber-400/35 bg-amber-500/10 text-amber-100"
                            : interventionSummary?.stateTone === "danger"
                              ? "border-rose-400/35 bg-rose-500/10 text-rose-100"
                              : interventionSummary?.stateTone === "info"
                                ? "border-sky-400/35 bg-sky-500/10 text-sky-100"
                                : "border-[var(--border)] text-[var(--text-muted)]"
                      }`}
                    >
                      {interventionSummary?.stateLabel || "待分析"}
                    </div>
                  </div>
                  {interventionSummary ? (
                    <div className="mt-4 space-y-4">
                      <div className="border border-[var(--border)] px-3 py-3">
                        <div className="text-sm">{interventionSummary.recommendation}</div>
                        <div className="mt-2 text-xs text-[var(--text-muted)]">{interventionSummary.actionHint}</div>
                      </div>
                      <div className="grid gap-3 lg:grid-cols-2">
                        <div className="border border-[var(--border)] px-3 py-3">
                          <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">人工阻塞 / 线程</div>
                          <div className="mt-2 text-sm">
                            阻塞原因: {interventionSummary.blockReason || "无"}
                            <br />
                            会话线程: {interventionSummary.threadId || "-"}
                          </div>
                        </div>
                        <div className="border border-[var(--border)] px-3 py-3">
                          <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">最近人工动作</div>
                          {interventionSummary.latestAction ? (
                            <div className="mt-2 text-sm">
                              {interventionSummary.latestAction.title}
                              <br />
                              {snippet(interventionSummary.latestAction.detail, 100) || "无额外说明"}
                              <div className="mt-2 text-xs text-[var(--text-muted)]">
                                {interventionSummary.latestAction.userLabel || "unknown"} /{" "}
                                {interventionSummary.latestAction.providerType || "unknown"} /{" "}
                                {formatTime(interventionSummary.latestAction.createdAt)}
                              </div>
                            </div>
                          ) : (
                            <div className="mt-2 text-sm text-[var(--text-muted)]">当前还没有人工干预记录。</div>
                          )}
                        </div>
                        <div className="border border-[var(--border)] px-3 py-3">
                          <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">上下文补充</div>
                          <div className="mt-2 text-sm">
                            已追加次数: {interventionSummary.contextCount}
                            <br />
                            最近内容: {snippet(interventionSummary.latestContextText, 110) || "无"}
                          </div>
                        </div>
                        <div className="border border-[var(--border)] px-3 py-3">
                          <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">图片识别 / 异常</div>
                          <div className="mt-2 text-sm">
                            {snippet(interventionSummary.latestImageSummary, 110) ||
                              snippet(interventionSummary.latestImageError, 110) ||
                              "当前没有图片识别结果"}
                          </div>
                        </div>
                      </div>
                      {interventionSummary.recentActions.length > 0 ? (
                        <div>
                          <div className="mb-2 text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">Recent Interventions</div>
                          <div className="space-y-2">
                            {interventionSummary.recentActions.map((action, index) => (
                              <div key={`${action.kind}-${action.createdAt}-${index}`} className="border border-[var(--border)] px-3 py-2">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                  <span className="font-medium">{action.title}</span>
                                  <span className="text-xs text-[var(--text-muted)]">{formatTime(action.createdAt)}</span>
                                </div>
                                <div className="mt-1 text-sm">{snippet(action.detail, 140) || "无额外说明"}</div>
                                <div className="mt-1 text-xs text-[var(--text-muted)]">
                                  {action.userLabel || "unknown"} / {action.providerType || "unknown"}
                                  {action.targetRunId ? ` / target ${action.targetRunId}` : ""}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
                <div className="border border-[var(--border)] bg-[var(--bg)]/86 p-4 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">Controlled Actions</div>
                      <div className="mt-1 text-[var(--text-muted)]">
                        这些动作会通过受控 token 调用 bridge 控制 API，并写入同一条审计链。
                      </div>
                    </div>
                    <div className="text-xs text-[var(--text-muted)]">{commandLoading ? "执行中..." : "ready"}</div>
                  </div>
                  <div className="mt-3 text-xs text-[var(--text-muted)]">{interventionSummary?.actionHint || "请选择 run 后执行控制动作。"}</div>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <button
                      type="button"
                      title={interventionSummary?.canPause ? "将当前 run 切换为 awaiting_human" : "当前状态不适合暂停"}
                      disabled={commandLoading || !interventionSummary?.canPause}
                      onClick={() => runCommand("pause", { reason: "Paused from bot-view" })}
                      className="border border-amber-400/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      暂停运行
                    </button>
                    <button
                      type="button"
                      title={interventionSummary?.canResume ? "恢复到暂停前状态" : "当前状态不需要恢复"}
                      disabled={commandLoading || !interventionSummary?.canResume}
                      onClick={() => runCommand("resume")}
                      className="border border-emerald-400/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      恢复运行
                    </button>
                    <button
                      type="button"
                      title={interventionSummary?.canEscalate ? "标记为需要人工接管" : "当前状态不适合升级"}
                      disabled={commandLoading || !interventionSummary?.canEscalate}
                      onClick={() => runCommand("escalate", { reason: "Escalated from bot-view" })}
                      className="border border-rose-400/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      升级人工
                    </button>
                  </div>
                  <div className="mt-4">
                    <label className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-muted)]">Add Context</label>
                    <textarea
                      value={contextInput}
                      onChange={(event) => setContextInput(event.target.value)}
                      rows={4}
                      placeholder="补充限制条件、风险说明、人工判断或下一步要求"
                      className="mt-2 w-full border border-[var(--border)] bg-[#0b0f14] px-3 py-2 text-sm text-[#dbe7f3] outline-none"
                    />
                    <div className="mt-2 flex items-center justify-between gap-3">
                      <div className="text-xs text-[var(--text-muted)]">
                        当前目标：{selectedRunId}
                      </div>
                      <button
                        type="button"
                        title={interventionSummary?.canAddContext ? "把新的限制、判断或图片说明写入 run 审计链" : "终态 run 默认不再追加上下文"}
                        disabled={commandLoading || !contextInput.trim() || !interventionSummary?.canAddContext}
                        onClick={() => runCommand("add-context", { context_text: contextInput.trim() })}
                        className="border border-[var(--accent)]/35 bg-[var(--accent)]/12 px-3 py-2 text-sm text-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        追加上下文
                      </button>
                    </div>
                  </div>
                  {commandError ? (
                    <div className="mt-3 border border-amber-400/30 bg-amber-500/10 p-3 text-sm text-amber-200">{commandError}</div>
                  ) : null}
                  {commandResult ? (
                    <div className="mt-3 border border-[var(--accent)]/25 bg-[var(--accent)]/8 p-3 text-sm text-[var(--text)] whitespace-pre-wrap">{commandResult}</div>
                  ) : null}
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
