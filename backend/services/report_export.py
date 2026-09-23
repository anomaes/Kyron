# The embedded, self-contained HTML and CSS intentionally keeps individual declarations intact.
# ruff: noqa: E501

from __future__ import annotations

import json
from html import escape
from typing import Any
from urllib.parse import urlparse


class _SafeHtml(str):
    pass


def render_traceability_report_html(report: dict[str, Any]) -> str:
    """Render a portable, self-contained view of a run report."""
    run = _mapping(report.get("run"))
    project_name = _text(run.get("project_name"), "Unknown project")
    workflow_id = _text(run.get("root_workflow_id"), "Unknown workflow")
    status = _text(run.get("status"), "UNKNOWN")
    frozen = bool(report.get("frozen"))
    gates = _mappings(report.get("gates"))
    invocations = _mappings(report.get("invocations"))
    waves = _mappings(report.get("waves"))
    nodes = _mappings(report.get("nodes"))
    change_requests = _mappings(report.get("change_requests"))
    audit_events = _mappings(report.get("audit_events"))
    lifecycle_events = _mappings(report.get("post_run_lifecycle"))

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:">
  <title>{_h(project_name)} · {_h(workflow_id)} · Kyron traceability report</title>
  <style>{_styles()}</style>
</head>
<body>
  <main>
    <header class="report-header">
      <div>
        <p class="eyebrow">Kyron traceability report</p>
        <h1>{_h(workflow_id)}</h1>
        <p class="subtitle">{_h(project_name)}</p>
      </div>
      <span class="status">{_h(status)}</span>
    </header>
    <p class="record-note">{_h(_record_note(frozen))}</p>

    <section>
      <h2>Execution summary</h2>
      <dl class="facts">
        {_fact("Run ID", run.get("id"))}
        {_fact("Triggered by", _actor(_mapping(run.get("triggered_by"))))}
        {_fact("Created", run.get("created_at"))}
        {_fact("Started", run.get("started_at"))}
        {_fact("Finished", run.get("finished_at"))}
        {_fact("Delivery mode", run.get("delivery_mode"))}
        {_fact("Generated", report.get("generated_at"))}
        {_fact("Record", "Frozen final record" if frozen else "Live snapshot")}
      </dl>
      {_error_block(run)}
    </section>

    <section>
      <h2>Source and delivery provenance</h2>
      <dl class="facts">
        {_fact("Base ref", run.get("base_ref"))}
        {_fact("Base commit", run.get("base_commit_sha"), code=True)}
        {_fact("Workflow definition", run.get("workflow_definition_commit_sha"), code=True)}
        {_fact("Subject", _subject(run))}
        {_fact("Subject commit", run.get("subject_commit_sha"), code=True)}
        {_fact("Checked subject HEAD", run.get("subject_current_head_sha"), code=True)}
        {_fact("Run branch", run.get("branch_name"), code=True)}
        {_fact("Final commit", run.get("final_commit_sha"), code=True)}
        {_fact("Verification", _verification(run))}
        {_fact("Change request", _link(run.get("change_request_url")))}
      </dl>
    </section>

    <section>
      <h2>Workflow invocations <span class="count">{len(invocations)}</span></h2>
      {_invocations_table(invocations)}
    </section>

    <section>
      <h2>Execution waves <span class="count">{len(waves)}</span></h2>
      {_waves_table(waves, invocations)}
    </section>

    <section>
      <h2>Node executions <span class="count">{len(nodes)}</span></h2>
      {_nodes_table(nodes)}
    </section>

    <section>
      <h2>Approval and feedback gates <span class="count">{len(gates)}</span></h2>
      {_gates(gates)}
    </section>

    <section>
      <h2>Change requests <span class="count">{len(change_requests)}</span></h2>
      {_change_requests_table(change_requests)}
    </section>

    <section>
      <h2>Run audit events <span class="count">{len(audit_events)}</span></h2>
      {_audit_table(audit_events)}
    </section>

    <section>
      <h2>Post-run lifecycle <span class="count">{len(lifecycle_events)}</span></h2>
      {_lifecycle_table(lifecycle_events)}
    </section>

    <footer>
      Schema version {_h(report.get("schema_version"))} · Run {_h(run.get("id"))}
    </footer>
  </main>
</body>
</html>"""


def _record_note(frozen: bool) -> str:
    if frozen:
        return "This is the immutable terminal execution record. Post-run lifecycle events are appended separately."
    return "This is a live snapshot of an active execution and may change until the run reaches a terminal state."


def _invocations_table(items: list[dict[str, Any]]) -> str:
    rows = [
        (
            item.get("workflow_id"),
            item.get("invocation_path"),
            item.get("status"),
            item.get("started_at"),
            item.get("finished_at"),
        )
        for item in items
    ]
    return _table(("Workflow", "Invocation path", "Status", "Started", "Finished"), rows)


def _waves_table(
    items: list[dict[str, Any]], invocations: list[dict[str, Any]]
) -> str:
    paths = {_text(item.get("id")): item.get("invocation_path") for item in invocations}
    rows = [
        (
            paths.get(_text(item.get("invocation_id")), item.get("invocation_id")),
            item.get("wave_index"),
            item.get("status"),
            item.get("start_commit_sha"),
            item.get("end_commit_sha"),
            item.get("started_at"),
            item.get("finished_at"),
            item.get("error_message") or "—",
        )
        for item in items
    ]
    return _table(
        ("Invocation", "Wave", "Status", "Start commit", "End commit", "Started", "Finished", "Error"),
        rows,
    )


def _nodes_table(items: list[dict[str, Any]]) -> str:
    rows = [
        (
            item.get("node_path"),
            item.get("node_type"),
            item.get("status"),
            item.get("current_attempt"),
            item.get("started_at"),
            item.get("finished_at"),
            item.get("error_message") or "—",
        )
        for item in items
    ]
    return _table(("Node", "Type", "Status", "Attempts", "Started", "Finished", "Error"), rows)


def _gates(gates: list[dict[str, Any]]) -> str:
    if not gates:
        return _empty("No approval or feedback gates were recorded.")
    return "".join(_gate(gate, index) for index, gate in enumerate(gates, start=1))


def _gate(gate: dict[str, Any], index: int) -> str:
    policy = _mapping(gate.get("policy_snapshot"))
    eligible = _mapping(gate.get("eligible_snapshot"))
    eligible_by_key = {
        _text(item.get("key")): item for item in _mappings(eligible.get("requirements"))
    }
    requirements: list[tuple[Any, ...]] = []
    for requirement in _mappings(policy.get("requirements")):
        eligible_requirement = eligible_by_key.get(_text(requirement.get("key")), {})
        actors = ", ".join(
            _actor(actor) for actor in _mappings(eligible_requirement.get("users"))
        )
        requirements.append(
            (
                requirement.get("name") or requirement.get("key"),
                requirement.get("quorum"),
                actors or "None snapshotted",
            )
        )

    decisions: list[tuple[Any, ...]] = []
    for decision in _mappings(gate.get("decisions")):
        event = _text(decision.get("event_type"))
        if decision.get("superseded"):
            event = f"{event} (superseded)"
        decisions.append(
            (
                event,
                _actor(_mapping(decision.get("actor_snapshot"))),
                ", ".join(_strings(decision.get("requirement_keys"))) or "—",
                decision.get("source"),
                decision.get("created_at"),
                decision.get("message") or "—",
            )
        )

    policy_name = policy.get("name") or gate.get("policy_key") or "Approval policy"
    return f"""
      <article class="gate">
        <div class="gate-heading">
          <div>
            <p class="eyebrow">Gate {index} · {_h(gate.get("invocation_path"))}</p>
            <h3>{_h(policy_name)} · {_h(gate.get("node_id"))}</h3>
          </div>
          <span class="status">{_h(gate.get("status"))}</span>
        </div>
        <dl class="facts compact">
          {_fact("Node path", gate.get("node_path"), code=True)}
          {_fact("Iteration", gate.get("iteration"))}
          {_fact("Checkpoint commit", gate.get("checkpoint_commit_sha"), code=True)}
          {_fact("Opened", gate.get("opened_at"))}
          {_fact("Resolved", gate.get("resolved_at"))}
          {_fact("Policy key", gate.get("policy_key"), code=True)}
        </dl>
        <h4>Policy requirements and eligible reviewers</h4>
        {_table(("Requirement", "Quorum", "Eligible reviewers"), requirements)}
        <h4>Decisions</h4>
        {_table(("Decision", "Actor", "Matched requirements", "Source", "At", "Message"), decisions)}
      </article>"""


def _change_requests_table(items: list[dict[str, Any]]) -> str:
    rows = [
        (
            item.get("kind"),
            item.get("provider"),
            f"#{item.get('provider_number')}" if item.get("provider_number") is not None else "—",
            item.get("status"),
            f"{_text(item.get('source_branch'))} → {_text(item.get('target_branch'))}",
            _link(item.get("url")),
            item.get("head_sha"),
        )
        for item in items
    ]
    return _table(("Kind", "Provider", "Number", "Status", "Branches", "URL", "Head"), rows)


def _audit_table(items: list[dict[str, Any]]) -> str:
    rows = [
        (
            item.get("created_at"),
            item.get("action"),
            _actor(_mapping(item.get("actor_snapshot"))),
            item.get("target_type"),
            item.get("target_id"),
            _json_text(item.get("details")),
        )
        for item in items
    ]
    return _table(("At", "Action", "Actor", "Target type", "Target", "Details"), rows)


def _lifecycle_table(items: list[dict[str, Any]]) -> str:
    rows = [
        (
            item.get("created_at"),
            item.get("event_type"),
            item.get("provider"),
            f"@{_text(item.get('actor_username'))}",
            item.get("merge_commit_sha"),
        )
        for item in items
    ]
    return _table(("At", "Event", "Provider", "Actor", "Merge commit"), rows)


def _table(headers: tuple[str, ...], rows: list[tuple[Any, ...]]) -> str:
    if not rows:
        return _empty("No records.")
    heading = "".join(f"<th>{_h(header)}</th>" for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_cell(value)}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f'<div class="table-wrap"><table><thead><tr>{heading}</tr></thead><tbody>{body}</tbody></table></div>'


def _fact(label: str, value: Any, *, code: bool = False) -> str:
    content = _cell(value)
    if code and content != "—":
        content = f"<code>{content}</code>"
    return f"<div><dt>{_h(label)}</dt><dd>{content}</dd></div>"


def _error_block(run: dict[str, Any]) -> str:
    if not run.get("error_type") and not run.get("error_message"):
        return ""
    return (
        '<div class="error"><strong>'
        + _h(run.get("error_type") or "Execution error")
        + "</strong><p>"
        + _h(run.get("error_message") or "No error detail was recorded.")
        + "</p></div>"
    )


def _subject(run: dict[str, Any]) -> str:
    kind = _text(run.get("subject_type"))
    reference = _text(run.get("subject_ref"))
    target = _text(run.get("subject_target_ref"))
    value = " ".join(part for part in (kind, reference) if part)
    return f"{value} → {target}" if target else value


def _verification(run: dict[str, Any]) -> str:
    conclusion = _text(run.get("verification_conclusion"))
    freshness = _text(run.get("verification_freshness"))
    return " · ".join(value for value in (conclusion, freshness) if value)


def _actor(actor: dict[str, Any]) -> str:
    name = _text(actor.get("display_name"))
    username = _text(actor.get("provider_username") or actor.get("username"))
    email = _text(actor.get("email"))
    identifier = username or email or _text(actor.get("user_id"), "Unknown actor")
    if name and identifier and name != identifier:
        return f"{name} ({identifier})"
    return name or identifier


def _link(value: Any) -> str:
    url = _text(value)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return url or "—"
    safe = _h(url)
    return _SafeHtml(f'<a href="{safe}">{safe}</a>')


def _json_text(value: Any) -> str:
    if value in (None, {}, []):
        return "—"
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(", ", ": "))


def _cell(value: Any) -> str:
    if isinstance(value, _SafeHtml):
        return value
    text = _text(value)
    return _h(text, "—")


def _empty(message: str) -> str:
    return f'<p class="empty">{_h(message)}</p>'


def _h(value: Any, default: str = "") -> str:
    return escape(_text(value, default), quote=True)


def _text(value: Any, default: str = "") -> str:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _mappings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_mapping(item) for item in value if isinstance(item, dict)]


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value]


def _styles() -> str:
    return """
    :root { color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, sans-serif; color: #20231d; background: #f1f1ec; }
    * { box-sizing: border-box; }
    body { margin: 0; }
    main { width: min(1180px, calc(100% - 32px)); margin: 32px auto; background: #fff; border: 1px solid #d9dbd2; border-radius: 12px; overflow: hidden; }
    .report-header { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; padding: 36px 40px 24px; background: #20231d; color: #fff; }
    h1 { margin: 3px 0 4px; font-size: 30px; }
    h2 { margin: 0 0 16px; font-size: 17px; }
    h3 { margin: 4px 0 0; font-size: 15px; }
    h4 { margin: 22px 0 9px; font-size: 12px; }
    .subtitle { margin: 0; color: #bfc4b5; }
    .eyebrow { margin: 0; color: #7d8275; font-size: 10px; font-weight: 700; letter-spacing: .09em; text-transform: uppercase; }
    .report-header .eyebrow { color: #c8f064; }
    .status { display: inline-block; padding: 6px 9px; border-radius: 999px; background: #e8f5c8; color: #39520e; font-size: 10px; font-weight: 800; letter-spacing: .05em; }
    .record-note { margin: 0; padding: 12px 40px; border-bottom: 1px solid #e1e2dc; background: #f7f8f3; color: #5e6358; font-size: 12px; }
    section { padding: 28px 40px; border-bottom: 1px solid #e1e2dc; break-inside: avoid; }
    .count { margin-left: 5px; color: #7d8275; font-size: 12px; }
    .facts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; margin: 0; background: #e1e2dc; border: 1px solid #e1e2dc; border-radius: 8px; overflow: hidden; }
    .facts > div { min-width: 0; padding: 12px; background: #fafaf7; }
    .facts.compact { grid-template-columns: repeat(3, minmax(0, 1fr)); margin-top: 16px; }
    dt { color: #777c70; font-size: 9px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; }
    dd { margin: 4px 0 0; overflow-wrap: anywhere; font-size: 12px; }
    code { font: 10px ui-monospace, SFMono-Regular, Menlo, monospace; }
    .gate { margin-top: 14px; padding: 19px; border: 1px solid #dfe1d8; border-radius: 9px; break-inside: avoid; }
    .gate-heading { display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; }
    .table-wrap { overflow-x: auto; border: 1px solid #e1e2dc; border-radius: 7px; }
    table { width: 100%; border-collapse: collapse; font-size: 10px; }
    th, td { padding: 9px 10px; border-bottom: 1px solid #e7e8e2; text-align: left; vertical-align: top; overflow-wrap: anywhere; }
    th { background: #f3f4ef; color: #6c7166; font-size: 8px; letter-spacing: .05em; text-transform: uppercase; }
    tr:last-child td { border-bottom: 0; }
    a { color: #4f31a7; }
    .empty { margin: 0; padding: 14px; border-radius: 7px; background: #f5f5f1; color: #74796e; font-size: 11px; }
    .error { margin-top: 12px; padding: 12px; border: 1px solid #efc8c3; border-radius: 7px; background: #fff1ef; color: #8d2f25; font-size: 11px; }
    .error p { margin: 4px 0 0; }
    footer { padding: 18px 40px; color: #7b8074; font-size: 9px; }
    @media (max-width: 760px) { .facts, .facts.compact { grid-template-columns: 1fr; } main { width: 100%; margin: 0; border: 0; border-radius: 0; } section, .report-header { padding-left: 20px; padding-right: 20px; } }
    @media print { :root { background: #fff; } main { width: 100%; margin: 0; border: 0; } .report-header { print-color-adjust: exact; } section { padding: 20px 24px; } a { color: inherit; text-decoration: none; } }
    """
