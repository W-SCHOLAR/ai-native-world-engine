import { useState, type FormEvent } from "react";

import type { InterventionTemplate, RunControlCommand } from "../../app/runtimeTypes";
import type { InterventionLogItem, SovereignIntentLogItem } from "../../types/ui";
import type { AgentNode, RunStatus } from "./viewerTypes";

const INTERVENTION_TEMPLATES: Array<{ id: InterventionTemplate; label: string }> = [
  { id: "signal", label: "释放信号" },
  { id: "supply", label: "投放补给" },
  { id: "policy", label: "施加政策" },
];

type Props = {
  selected: AgentNode | null;
  runId?: string;
  runStatus?: RunStatus;
  controlState: "active" | "paused" | "canceled";
  pendingControl: RunControlCommand | null;
  pendingIntervention: InterventionTemplate | null;
  pendingSovereignIntent: boolean;
  interventionLog: InterventionLogItem[];
  sovereignIntentLog: SovereignIntentLogItem[];
  runtimeAuthority: "authoritative_engine" | "static_visual_demo" | "local_projection_fallback";
  status: string;
  onRunControl?: (command: RunControlCommand) => void;
  onRunIntervention?: (nodeId: string, nodeName: string, template: InterventionTemplate) => void;
  onSovereignIntent?: (text: string) => void;
};

export function ViewerInteractionBar({
  selected,
  runId,
  runStatus,
  controlState,
  pendingControl,
  pendingIntervention,
  pendingSovereignIntent,
  interventionLog,
  sovereignIntentLog,
  runtimeAuthority,
  status,
  onRunControl,
  onRunIntervention,
  onSovereignIntent,
}: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const [intentText, setIntentText] = useState("");
  const terminalRun = runStatus === "completed" || runStatus === "failed" || controlState === "canceled";
  const canWrite = runtimeAuthority === "authoritative_engine" && Boolean(runId) && !terminalRun;
  const latestIntent = sovereignIntentLog[0];
  const latestIntervention = interventionLog[0];

  function submitIntent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = intentText.trim();
    if (!canWrite || pendingSovereignIntent || !text) return;
    onSovereignIntent?.(text);
    setIntentText("");
  }

  return (
    <aside
      aria-label="世界交互"
      className="viewer-interaction-bar"
      data-collapsed={collapsed ? "yes" : "no"}
      data-runtime-ready={canWrite ? "yes" : "no"}
    >
      <div className="interaction-bar-summary">
        <div className="interaction-runtime-state">
          <i data-state={controlState} />
          <span>{runId ? `${runStatus ?? "queued"} · ${controlState}` : status}</span>
        </div>
        <strong>{selected?.name ?? "选择一个节点进行干预"}</strong>
        <button
          aria-expanded={!collapsed}
          className="interaction-collapse"
          onClick={() => setCollapsed((value) => !value)}
          type="button"
        >
          {collapsed ? "展开互动" : "收起"}
        </button>
      </div>

      {collapsed ? null : (
        <div className="interaction-bar-content">
          <section className="interaction-run-control" aria-label="运行控制">
            <span>RUN</span>
            {controlState === "paused" ? (
              <button
                disabled={!canWrite || Boolean(pendingControl)}
                onClick={() => onRunControl?.("resume")}
                type="button"
              >
                {pendingControl === "resume" ? "Resuming" : "Resume"}
              </button>
            ) : (
              <button
                disabled={!canWrite || Boolean(pendingControl)}
                onClick={() => onRunControl?.("pause")}
                type="button"
              >
                {pendingControl === "pause" ? "Pausing" : "Pause"}
              </button>
            )}
          </section>

          <section className="interaction-interventions" aria-label="干预模板">
            {INTERVENTION_TEMPLATES.map((template) => (
              <button
                className="intervention-button"
                data-template={template.id}
                disabled={!canWrite || !selected || Boolean(pendingIntervention)}
                key={template.id}
                onClick={() => selected && onRunIntervention?.(selected.id, selected.name, template.id)}
                type="button"
              >
                {pendingIntervention === template.id ? "Queuing" : template.label}
              </button>
            ))}
          </section>

          <form className="interaction-sovereign-intent" aria-label="国王视角下旨" onSubmit={submitIntent}>
            <input
              aria-label="旨意"
              disabled={!canWrite || pendingSovereignIntent}
              maxLength={180}
              onChange={(event: { target: { value: string } }) => setIntentText(event.target.value)}
              placeholder="向世界下达开放意图…"
              type="text"
              value={intentText}
            />
            <button disabled={!canWrite || pendingSovereignIntent || !intentText.trim()} type="submit">
              {pendingSovereignIntent ? "Queuing" : "下旨"}
            </button>
          </form>

          <section className="interaction-receipts" aria-label="互动回执">
            {latestIntent ? (
              <article data-status={latestIntent.status}>
                <b>旨意</b>
                <span>{latestIntent.title || latestIntent.summary}</span>
                <em>{receiptStatus(latestIntent.status, latestIntent.appliedTick)}</em>
              </article>
            ) : null}
            {latestIntervention ? (
              <article data-status={latestIntervention.status}>
                <b>干预</b>
                <span>{latestIntervention.summary}</span>
                <em>{receiptStatus(latestIntervention.status, latestIntervention.appliedTick)}</em>
              </article>
            ) : null}
            {!latestIntent && !latestIntervention ? <p>干预后，世界回执会显示在这里</p> : null}
          </section>
        </div>
      )}
    </aside>
  );
}

function receiptStatus(status: "queued" | "applied" | "rejected", appliedTick?: number | string) {
  if (status === "applied") return appliedTick === undefined ? "Applied" : `Applied · T${appliedTick}`;
  if (status === "rejected") return "Rejected";
  return "Queued";
}
