#!/usr/bin/env python3
"""Comments, assignments, access_requests, sla_violations, audit_logs."""
import json
import random
import uuid
from datetime import timedelta

from _seed_base import bulk_insert, now_utc, past_range

COMMENT_TEMPLATES = [
    "Confirmed in production environment. Needs immediate fix.",
    "False positive — input is sanitized upstream at the API gateway.",
    "Risk accepted by security team. WAF rule deployed as mitigation.",
    "PR #%d created to address this finding. Blocked on QA sign-off.",
    "Triaged: exploitability is low due to network segmentation.",
    "CVE patched in upstream library. Updating dependency now.",
    "Appears to be a duplicate of a finding reported last month.",
    "Impact: CVSS 9.8. Escalating to incident response team.",
    "Workaround applied: disabled the affected feature flag.",
    "Fixed in commit %s. Please re-scan to verify closure.",
]


def gen_comments(conn, findings: list, users: list, fake) -> None:
    rows = []
    for f in random.sample(findings, int(len(findings) * 0.40)):
        for _ in range(random.randint(1, 3)):
            tmpl = random.choice(COMMENT_TEMPLATES)
            if "%d" in tmpl:
                text = tmpl % random.randint(100, 999)
            elif "%s" in tmpl:
                text = tmpl % fake.hexify("^" * 8)
            else:
                text = tmpl
            rows.append({
                "id": str(uuid.uuid4()),
                "finding_id": str(f["id"]),
                "user_id": str(random.choice(users)["id"]),
                "content": text,
                "created_at": past_range(0.1, 30),
                "updated_at": now_utc(),
            })
    bulk_insert(conn, "comments", rows, conflict="DO NOTHING")


def gen_assignments(conn, findings: list, users: list) -> None:
    pool = [u for u in users if "admin" not in u.get("email", "")] or users
    rows = []
    for f in findings:
        if f.get("current_status") in ("new", "confirmed") \
                and random.random() < 0.60:
            rows.append({
                "id": str(uuid.uuid4()),
                "finding_id": str(f["id"]),
                "user_id": str(random.choice(pool)["id"]),
                "assigned_at": past_range(0.1, 15),
                "created_at": past_range(0.1, 15),
            })
    bulk_insert(conn, "assignments", rows, conflict="DO NOTHING")


def gen_access_requests(conn, users: list, projects: list) -> None:
    non_admin = [u for u in users if "admin" not in u.get("email", "")]
    rows = []
    for _ in range(min(len(non_admin) * 2, 10)):
        u = random.choice(non_admin) if non_admin else users[0]
        p = random.choice(projects)
        status = random.choices(
            ["pending", "approved", "rejected"], [0.4, 0.4, 0.2]
        )[0]
        rows.append({
            "id": str(uuid.uuid4()),
            "user_id": str(u["id"]),
            "resource_type": "project",
            "resource_id": str(p["id"]),
            "requested_role": random.choice(
                ["viewer", "developer", "security_analyst", "auditor"]
            ),
            "status": status,
            "reason": random.choice(
                ["work_related", "audit", "security_review", "other"]
            ),
            "comment": (
                "Needed for Q2 security audit." if random.random() > 0.5 else None
            ),
            "reviewed_by_id": (
                str(random.choice(non_admin or users)["id"])
                if status != "pending" else None
            ),
            "reviewed_at": (
                past_range(0, 5) if status != "pending" else None
            ),
            "created_at": past_range(1, 60),
        })
    bulk_insert(conn, "access_requests", rows, conflict="DO NOTHING")


def gen_sla_violations(conn, findings: list) -> None:
    rows = []
    for f in findings:
        sla_exp = f.get("sla_expires_at")
        if not sla_exp:
            continue
        if sla_exp < now_utc() and random.random() < 0.7:
            rows.append({
                "id": str(uuid.uuid4()),
                "finding_id": str(f["id"]),
                "severity": f["severity"],
                "due_date": sla_exp,
                "violated_at": sla_exp,
                "resolved_at": (
                    past_range(0, 5)
                    if f.get("current_status") == "fixed" else None
                ),
                "created_at": sla_exp,
            })
    bulk_insert(conn, "sla_violations", rows, conflict="DO NOTHING")


def gen_audit_logs(
    conn, users: list, findings: list, projects: list, fake,
) -> None:
    AI_SYSTEM_USER_ID = "8e4cf47a-1d9b-4f3c-b2e0-7a5d3c8f1e96"
    ai_uid = AI_SYSTEM_USER_ID
    rows = []
    now = now_utc()

    # entity_type MUST be "Finding" (PascalCase, matching the Go struct name —
    # see backend/internal/services/finding_service.go's EntityType: "Finding").
    # The dashboard trend query (dashboard_handler.go GetTrends) and MTTR query
    # (report_mttr.go) both filter with entity_type = 'Finding' exact-case; a
    # lowercase "finding" row here never matches, so the dashboard's sweep-line
    # never learns a finding's real status and defaults every finding to "new"
    # (open) for its entire lifetime — this is why the demo's Closed line was
    # always flat at 0. Every finding whose seeded status isn't "new" needs a
    # real status_changed event so the trend line reflects it, timed somewhere
    # within the finding's own lifetime (not clustered near "now") so Closed
    # counts build up gradually across the trend window instead of in one day.
    for f in findings:
        status = f.get("current_status", "new")
        if status == "new":
            continue
        created = f.get("created_at") or now
        span = max((now - created).total_seconds(), 1.0)
        changed_at = created + timedelta(seconds=random.uniform(span * 0.1, span * 0.95))
        rows.append({
            "id": str(uuid.uuid4()),
            "entity_type": "Finding",
            "entity_id": str(f["id"]),
            "action": "status_changed",
            "changed_by_id": str(random.choice(users)["id"]),
            "old_values": json.dumps({"current_status": "new"}),
            "new_values": json.dumps({"current_status": status}),
            "changed_at": changed_at,
        })
    if ai_uid:
        for f in random.sample(findings, min(5, len(findings))):
            rows.append({
                "id": str(uuid.uuid4()),
                "entity_type": "Finding",
                "entity_id": str(f["id"]),
                "action": "ai_analysis_completed",
                "changed_by_id": ai_uid,
                "old_values": None,
                "new_values": json.dumps({"analysis": "Automated triage completed."}),
                "changed_at": past_range(0.1, 10),
            })
    for p in projects:
        rows.append({
            "id": str(uuid.uuid4()),
            "entity_type": "Project",
            "entity_id": str(p["id"]),
            "action": "sla_config_updated",
            "changed_by_id": str(random.choice(users)["id"]),
            "old_values": json.dumps({"critical": 14}),
            "new_values": json.dumps({"critical": 7}),
            "changed_at": past_range(10, 90),
        })
    bulk_insert(conn, "audit_logs", rows, conflict="DO NOTHING")
