from backend.services.report_export import render_traceability_report_html


def test_report_export_contains_execution_provenance_and_gate_decisions() -> None:
    report = {
        "schema_version": 3,
        "frozen": True,
        "generated_at": "2026-09-23T12:00:00+00:00",
        "run": {
            "id": "run-id",
            "status": "COMPLETED",
            "root_workflow_id": "release",
            "project_name": "Kyron",
            "triggered_by": {"display_name": "Run Owner", "provider_username": "owner"},
            "base_ref": "main",
            "base_commit_sha": "a" * 40,
            "workflow_definition_commit_sha": "b" * 40,
            "subject_type": "BRANCH",
            "subject_ref": "feature/report",
            "subject_commit_sha": "c" * 40,
            "final_commit_sha": "d" * 40,
            "delivery_mode": "PROPOSE_CHANGES",
            "created_at": "2026-09-23T11:00:00+00:00",
            "started_at": "2026-09-23T11:01:00+00:00",
            "finished_at": "2026-09-23T11:10:00+00:00",
        },
        "invocations": [
            {
                "id": "invocation-id",
                "workflow_id": "release",
                "invocation_path": "root",
                "status": "SUCCESS",
                "started_at": "2026-09-23T11:01:00+00:00",
                "finished_at": "2026-09-23T11:10:00+00:00",
            }
        ],
        "waves": [
            {
                "invocation_id": "invocation-id",
                "wave_index": 1,
                "status": "SUCCESS",
                "start_commit_sha": "a" * 40,
                "end_commit_sha": "d" * 40,
                "started_at": "2026-09-23T11:01:00+00:00",
                "finished_at": "2026-09-23T11:04:00+00:00",
                "error_message": None,
            }
        ],
        "nodes": [
            {
                "node_path": "root/build",
                "node_type": "prompt",
                "status": "SUCCESS",
                "current_attempt": 1,
                "started_at": "2026-09-23T11:01:00+00:00",
                "finished_at": "2026-09-23T11:04:00+00:00",
                "error_message": None,
            }
        ],
        "gates": [
            {
                "invocation_path": "root",
                "node_id": "security-review",
                "node_path": "root/security-review",
                "iteration": 1,
                "status": "APPROVED",
                "checkpoint_commit_sha": "e" * 40,
                "policy_key": "security",
                "opened_at": "2026-09-23T11:05:00+00:00",
                "resolved_at": "2026-09-23T11:06:00+00:00",
                "policy_snapshot": {
                    "name": "Security review",
                    "requirements": [
                        {"key": "security", "name": "Security", "quorum": 1}
                    ],
                },
                "eligible_snapshot": {
                    "requirements": [
                        {
                            "key": "security",
                            "users": [
                                {
                                    "display_name": "Ada Approver",
                                    "provider_username": "ada",
                                }
                            ],
                        }
                    ]
                },
                "decisions": [
                    {
                        "event_type": "approval",
                        "actor_snapshot": {
                            "display_name": "Ada Approver",
                            "provider_username": "ada",
                        },
                        "requirement_keys": ["security"],
                        "source": "github",
                        "created_at": "2026-09-23T11:06:00+00:00",
                        "message": "Approved after review",
                        "superseded": False,
                    }
                ],
            }
        ],
        "change_requests": [],
        "audit_events": [],
        "post_run_lifecycle": [],
    }

    document = render_traceability_report_html(report)

    assert "Kyron traceability report" in document
    assert "Frozen final record" in document
    assert "Security review" in document
    assert "Ada Approver (ada)" in document
    assert "Approved after review" in document
    assert "e" * 40 in document
    assert "root/build" in document


def test_report_export_escapes_values_and_rejects_unsafe_links() -> None:
    report = {
        "schema_version": 2,
        "frozen": False,
        "generated_at": "2026-09-23T12:00:00+00:00",
        "run": {
            "id": "run-id",
            "status": "RUNNING",
            "root_workflow_id": '<script>alert("workflow")</script>',
            "project_name": "Project & Co",
            "triggered_by": {"display_name": '<img src=x onerror=alert("actor")>'},
            "change_request_url": "javascript:alert(1)",
        },
        "invocations": [],
        "gates": [],
        "change_requests": [],
        "audit_events": [],
        "post_run_lifecycle": [],
    }

    document = render_traceability_report_html(report)

    assert '<script>alert("workflow")</script>' not in document
    assert '&lt;script&gt;alert(&quot;' in document
    assert '<img src=x onerror=alert("actor")>' not in document
    assert 'href="javascript:' not in document
    assert "javascript:alert(1)" in document
