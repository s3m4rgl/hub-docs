#!/usr/bin/env python3
"""Scope entries, proposals, sync jobs, assets generators."""
import json
import random
import uuid

from _seed_base import (
    Scale, bulk_insert, fetchall, future, now_utc, past, past_range,
    random_ip_in_cidr, upsert_by,
)

SCOPE_TAGS = ["security-scan", "external", "internal", "pci", "dmz", "production"]


def _domain(company_name: str) -> str:
    return company_name.lower().replace(" ", "-") + ".com"


def gen_scope_for_project(conn, project: dict, scale: Scale, users: list) -> dict:
    domain = _domain(project["name"])
    base_a = f"185.{random.randint(10, 250)}.{random.randint(1, 250)}"
    cidr_a = f"{base_a}.0/24"
    cidr_b = f"10.{random.randint(1, 99)}.{random.randint(1, 99)}.0/16"

    def _e(entry_type, value, scope_action="include", source="manual",
            disabled=False, tags=None):
        e = {
            "id": str(uuid.uuid4()),
            "project_id": str(project["id"]),
            "entry_type": entry_type,
            "value": value,
            "scope_action": scope_action,
            "source": source,
            "description": "Imported from NetBox" if source == "netbox_import" else "",
            "tags": json.dumps(tags or []),
            "disabled_at": None,
            "disabled_by": "",
            "disabled_reason": "",
            "created_at": past_range(10, 180),
            "updated_at": now_utc(),
        }
        if disabled:
            e.update({
                "disabled_at": past_range(1, 30),
                "disabled_by": "sync",
                "disabled_reason": (
                    "Address removed from NetBox (status changed to deprecated)"
                ),
            })
        return e

    live_ips = [random_ip_in_cidr(cidr_a) for _ in range(random.randint(2, 4))]
    entries = [
        _e("domain", domain, tags=["security-scan", "external"]),
        _e("domain", f"*.api.{domain}", tags=["security-scan"]),
        _e("domain", f"mail.{domain}", scope_action="exclude"),
        _e("cidr", cidr_a, source="netbox_import", tags=["external", "pci"]),
        _e("cidr", cidr_b, source="manual"),
        # Individual IPs as /32 CIDR (entry_type only allows 'domain' or 'cidr')
        *[_e("cidr", f"{ip}/32", source="netbox_import",
              tags=random.sample(SCOPE_TAGS, 2)) for ip in live_ips],
        *[_e("cidr", f"{random_ip_in_cidr(cidr_a)}/32", source="netbox_import", disabled=True)
          for _ in range(random.randint(1, 2))],
    ]
    for e in entries:
        upsert_by(conn, "scan_scope_entries", e,
                  conflict_cols=["project_id", "entry_type", "value"])
    db_entries = fetchall(
        conn,
        "SELECT * FROM scan_scope_entries WHERE project_id = %s",
        (str(project["id"]),),
    )

    def _proposal(value, status, scanner, src_domain=None, src_ip=None):
        p = {
            "id": str(uuid.uuid4()),
            "project_id": str(project["id"]),
            "entry_type": "domain" if not value[0].isdigit() else "cidr",
            "proposed_value": value,
            "status": status,
            "scanner_name": scanner,
            "source_domain": src_domain,
            "source_ip": src_ip,
            # JSONB in Go = map[string]interface{} — must be a JSON object {}, NOT array [{}]
            "trail": json.dumps({
                "type": "dns_lookup",
                "value": src_domain or domain,
                "via": {"type": "scanner", "value": scanner},
            }),
            "created_at": past_range(1, 60),
            "reviewed_by": None,
            "reviewed_at": None,
        }
        if status in ("approved", "rejected") and users:
            reviewer = random.choice(users)
            p.update({
                "reviewed_by": str(reviewer["id"]),
                "reviewed_at": past_range(0, 1),
            })
        return p

    src_ip = live_ips[0] if live_ips else None
    bulk_insert(conn, "scan_scope_proposals", [
        # pending — awaiting review (both source_domain and source_ip populated)
        _proposal(f"dev.{domain}",     "pending",  "domainscope",
                  src_domain=domain,   src_ip=src_ip),
        _proposal(f"staging.{domain}", "pending",  "nuclei",
                  src_domain=domain,   src_ip=src_ip),
        _proposal(f"vpn.{domain}",     "pending",  "domainscope",
                  src_domain=domain,   src_ip=src_ip),
        # approved — already accepted and linked to scope entry
        _proposal(f"app.{domain}",     "approved", "domainscope",
                  src_domain=domain,   src_ip=src_ip),
        # rejected — explicitly declined
        _proposal(f"{domain[:-4]}.net", "rejected", "domainscope",
                  src_domain=domain),
    ], conflict="DO NOTHING")

    slug = project["name"].lower().replace(" ", "-")
    bulk_insert(conn, "scan_scope_sync_jobs", [{
        "id": str(uuid.uuid4()),
        "project_id": str(project["id"]),
        "name": f"NetBox sync — {project['name']}",
        "api_endpoint": f"https://netbox.{slug}.internal/api",
        "api_token": "",
        "tls_skip_verify": False,
        "allow_private_ips": False,
        "scope_action": "include",
        "network_type": "public",
        "schedule_interval_hours": 24,
        "enabled": True,
        "active_statuses": json.dumps(["active", "reserved"]),
        "auto_remove": False,
        "ip_tags": json.dumps(["security-scan", "external"]),
        "ip_tags_mode": "any",
        "exclude_tags": json.dumps([]),
        "exclude_tags_mode": "any",
        "include_tenants": json.dumps([]),
        "exclude_tenants": json.dumps([]),
        "include_tenants_mode": "any",
        "exclude_tenants_mode": "any",
        "import_tags": True,
        "last_run_at": past_range(0.5, 3),
        "last_run_status": random.choice(["success", "success", "partial"]),
        "last_run_result": json.dumps({"appeared": 3, "vanished": 1, "total": 12}),
        "next_run_at": future(random.uniform(1, 24) / 24),
        "created_by": str(users[0]["id"]) if users else None,
        "created_at": past(90),
        "updated_at": now_utc(),
    }], conflict="DO NOTHING")

    bulk_insert(conn, "scan_scope_assets", [{
        "id": str(uuid.uuid4()),
        "project_id": str(project["id"]),
        "domain": f"host-{ip.replace('.', '-')}.{domain}",
        "ip": ip,
        "scanner_name": random.choice(["nessus", "nuclei", "domainscope"]),
        "trail": json.dumps([{
            "type": "config", "value": domain,
            "via": {
                "type": "dns_resolve", "value": ip,
                "via": {
                    "type": "nmap",
                    "value": f"{ip}:{random.choice([80, 443, 22])}/tcp",
                },
            },
        }]),
        "first_seen_at": past_range(5, 60),
        "last_seen_at": now_utc(),
    } for ip in live_ips[:3]], conflict="DO NOTHING")

    return {"entries": db_entries, "live_ips": live_ips, "domain": domain}


def gen_scope(conn, projects: list, scale: Scale, users: list) -> dict:
    return {
        str(p["id"]): gen_scope_for_project(conn, p, scale, users)
        for p in projects
    }
