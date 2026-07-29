import type { RunUsage } from "../types";
import { StatusBadge } from "./StatusBadge";

const compactNumber = new Intl.NumberFormat(undefined, {
  notation: "compact",
  maximumFractionDigits: 1,
});
const exactNumber = new Intl.NumberFormat();

export function formatTokens(value: number): string {
  return value < 1000 ? exactNumber.format(value) : compactNumber.format(value);
}

export function formatCost(value: number): string {
  if (value > 0 && value < 0.01) {
    return `$${value.toLocaleString(undefined, { minimumFractionDigits: 4, maximumFractionDigits: 4 })}`;
  }
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function UsageBreakdown({ data }: { data: RunUsage }) {
  return <div className="run-usage-popover">
    <header>
      <div><strong>AI usage</strong><span>All prompt-node attempts, including retries</span></div>
      <div><b>{formatTokens(data.usage.totalTokens)} tokens</b><small>{formatCost(data.usage.cost.total)} estimated cost</small></div>
    </header>
    <div className="run-usage-totals">
      <div><span>Input</span><strong>{formatTokens(data.usage.input)}</strong></div>
      <div><span>Output</span><strong>{formatTokens(data.usage.output)}</strong></div>
      <div><span>Cache read</span><strong>{formatTokens(data.usage.cacheRead)}</strong></div>
      <div><span>Cache write</span><strong>{formatTokens(data.usage.cacheWrite)}</strong></div>
      <div><span>Model calls</span><strong>{exactNumber.format(data.usage.requestCount)}</strong></div>
    </div>
    <div className="run-usage-table-wrap">
      <table>
        <thead><tr><th>Prompt / attempt</th><th>Status</th><th>Input</th><th>Output</th><th>Cache R/W</th><th>Total</th><th>Cost</th></tr></thead>
        <tbody>{data.nodes.map((node) => <NodeUsageRows key={node.node_execution_id} node={node} />)}</tbody>
      </table>
    </div>
  </div>;
}

function NodeUsageRows({ node }: { node: RunUsage["nodes"][number] }) {
  return <>
    <tr className="run-usage-node-row">
      <td><strong>{node.node_id}</strong><code>{node.node_path}</code></td>
      <td><StatusBadge status={node.status} /></td>
      <td>{formatTokens(node.usage.input)}</td>
      <td>{formatTokens(node.usage.output)}</td>
      <td>{formatTokens(node.usage.cacheRead)} / {formatTokens(node.usage.cacheWrite)}</td>
      <td><strong>{formatTokens(node.usage.totalTokens)}</strong></td>
      <td>{formatCost(node.usage.cost.total)}</td>
    </tr>
    {node.attempts.map((attempt) => <tr key={attempt.attempt_id} className="run-usage-attempt-row">
      <td>↳ Attempt {attempt.attempt_number}</td>
      <td><StatusBadge status={attempt.status} /></td>
      <td>{formatTokens(attempt.usage.input)}</td>
      <td>{formatTokens(attempt.usage.output)}</td>
      <td>{formatTokens(attempt.usage.cacheRead)} / {formatTokens(attempt.usage.cacheWrite)}</td>
      <td>{formatTokens(attempt.usage.totalTokens)}</td>
      <td>{formatCost(attempt.usage.cost.total)}</td>
    </tr>)}
  </>;
}

export function RunUsageSummary({
  data,
  loading = false,
  error = false,
}: {
  data?: RunUsage;
  loading?: boolean;
  error?: boolean;
}) {
  if (loading && !data) {
    return <div className="run-usage-overview"><span>AI usage</span><strong>Calculating…</strong><small>Collecting Pi model calls</small></div>;
  }
  if (error && !data) {
    return <div className="run-usage-overview"><span>AI usage</span><strong>Unavailable</strong><small>Usage could not be loaded</small></div>;
  }
  if (!data || data.usage.requestCount === 0) {
    return <div className="run-usage-overview"><span>AI usage</span><strong>0 tokens</strong><small>No Pi model calls recorded</small></div>;
  }
  return <details className="run-usage-overview">
    <summary>
      <span>AI usage</span>
      <strong>{formatTokens(data.usage.totalTokens)} tokens</strong>
      <small>{data.usage.requestCount} model call{data.usage.requestCount === 1 ? "" : "s"} · {formatCost(data.usage.cost.total)}</small>
    </summary>
    <UsageBreakdown data={data} />
  </details>;
}
