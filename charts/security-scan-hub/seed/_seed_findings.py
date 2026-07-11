#!/usr/bin/env python3
"""Report, FindingGroup, and all finding-type generators."""
import json
import random
import uuid
from datetime import timedelta

from _seed_base import (
    CHECKOV_RULES, DOMAINSCOPE_RULES, FINDING_STATUSES, KICS_RULES, KINGFISHER_RULES,
    KNOWN_VULNS_POOL, NESSUS_RULES, NUCLEI_RULES, SECRET_FILE_PATTERNS,
    SEMGREP_RULES, SEVERITIES, SEVERITY_WEIGHTS, SLA_DAYS, STATUS_WEIGHTS,
    TRIVY_RULES, Scale,
    bulk_insert, calculate_dedup_hash, calculate_location_hash,
    calculate_network_dedup_hash, network_location_hash,
    now_utc, past_range, random_git_sha,
)

ENGINE_VERSIONS = {
    "semgrep":     "1.45.0",
    "trivy":       "0.49.1",
    "checkov":     "3.1.52",
    "kics":        "1.7.13",
    "nessus":      "10.6.0",
    "nuclei":      "3.1.4",
    "kingfisher":  "2.3.1",
    "domainscope": "2.5.0",
}

SCANNER_RULE_MAP = {
    "semgrep": SEMGREP_RULES,
    "trivy": TRIVY_RULES,
    "checkov": CHECKOV_RULES,
    "kics": KICS_RULES,
}


def gen_reports(conn, products: list, users: list) -> dict:
    result: dict = {}
    for product in products:
        pid = str(product["id"])
        reports = []
        for engine in random.sample(list(ENGINE_VERSIONS), random.randint(2, 4)):
            commit = random_git_sha()
            row = {
                "id": str(uuid.uuid4()),
                "product_id": pid,
                "uploaded_by_id": str(random.choice(users)["id"]),
                "original_name": f"{engine}-report-{commit[:8]}.sarif",
                "file_path": f"storage/reports/{pid}/{commit[:8]}.sarif",
                "engine": engine,
                "engine_version": ENGINE_VERSIONS[engine],
                "status": "processed",
                "processed_at": past_range(0.1, 30),
                "findings_count": 0,
                "commit_id": commit,
                "created_at": past_range(1, 60),
            }
            bulk_insert(conn, "reports", [row], conflict="DO NOTHING")
            reports.append(row)
        result[pid] = reports
    return result


def gen_finding_groups(conn, products: list, users: list) -> dict:
    group_names = [
        "Log4Shell cluster", "SSL/TLS misconfigs", "SQL Injection family",
        "Secrets in code", "K8s RBAC issues", "Dependency vulns (critical)",
        "XSS vulnerabilities", "Auth bypass findings",
    ]
    result: dict = {}
    for product in products:
        pid = str(product["id"])
        groups = []
        for name in random.sample(group_names, random.randint(1, 3)):
            row = {
                "id": str(uuid.uuid4()),
                "product_id": pid,
                "name": name,
                "group_rule": "manual",
                "leader_finding_id": None,
                "created_by": str(random.choice(users)["id"]),
                "created_at": past_range(1, 60),
                "updated_at": now_utc(),
            }
            bulk_insert(conn, "finding_groups", [row], conflict="DO NOTHING")
            groups.append(row)
        result[pid] = groups
    return result


def _random_path(rule: dict) -> str:
    pat = rule.get("file_pattern", "")
    if pat:
        dirs = ["src", "internal", "app", "pkg"]
        subs = ["auth", "api", "db", "config"]
        return f"{random.choice(dirs)}/{random.choice(subs)}/{pat}"
    exts = {"go": ".go", "python": ".py", "typescript": ".ts",
            "hcl": ".tf", "yaml": ".yaml"}
    return f"src/main{exts.get(rule.get('lang', 'go'), '.go')}"


def _make_code_row(product_id: str, rule: dict, scanner: str, group_id=None) -> dict:
    fp = _random_path(rule)
    ls = random.randint(1, 200)
    le = ls + random.randint(0, 15)
    sn = rule.get("snippet", "")
    loc = calculate_location_hash(fp, ls, le, sn)
    dedup = calculate_dedup_hash(product_id, rule["rule_id"], loc)
    sev = rule.get("severity") or random.choices(SEVERITIES, SEVERITY_WEIGHTS)[0]
    status = random.choices(FINDING_STATUSES, STATUS_WEIGHTS)[0]
    first = past_range(1, 90)
    sla_s = first if status in ("confirmed", "risk_accepted") else None
    sla_e = (sla_s + timedelta(days=SLA_DAYS[sev])) if sla_s else None
    return {
        "id": str(uuid.uuid4()),
        "deduplication_hash": dedup,
        "product_id": product_id,
        "title": rule["title"],
        "description": (
            f"Detected by {scanner}: {rule['title']}. Review {fp}:{ls}."
        ),
        "severity": sev,
        "current_status": status,
        "cwe_id": rule.get("cwe", "") or "",
        "cve": rule.get("cve", "") or "",
        "rule_id": rule["rule_id"],
        "file_path": fp,
        "line_start": ls,
        "line_end": le,
        "snippet_text": sn,
        "snippet_start_line": ls,
        "snippet_end_line": le,
        "snippet_language": rule.get("lang", "go"),
        "properties": json.dumps({
            "commit_id": random_git_sha(),
            "scanner_name": scanner,
        }),
        "tags": json.dumps([]),
        "group_id": str(group_id) if group_id else None,
        "first_seen_at": first,
        "last_seen_at": past_range(0, 1),
        "sla_started_at": sla_s,
        "sla_expires_at": sla_e,
        "created_at": first,
        "updated_at": now_utc(),
    }


def gen_code_findings(
    conn, products: list, product_reports: dict,
    product_groups: dict, scale: Scale,
) -> tuple:
    all_f: list = []
    rfs: list = []

    for product in products:
        pid = str(product["id"])
        rpts = [r for r in product_reports.get(pid, [])
                if r["engine"] in SCANNER_RULE_MAP]
        groups = product_groups.get(pid, [])
        if not rpts:
            continue

        min_f, max_f = scale.findings_per_product
        total = random.randint(min_f, max_f)
        known_n = max(1, int(total * 0.12))
        seen: set = set()

        def _ins(row, rpt):
            h = row["deduplication_hash"]
            if h in seen:
                return
            n = bulk_insert(conn, "findings", [row],
                            conflict="(deduplication_hash) WHERE deleted_at IS NULL DO NOTHING")
            seen.add(h)
            if n > 0:
                all_f.append(row)
                rfs.append({
                    "report_id":          str(rpt["id"]),
                    "finding_id":         str(row["id"]),
                    "raw_details":        json.dumps({
                        "scanner": rpt["engine"],
                        "rule_id": row.get("rule_id", ""),
                    }),
                    # Populate snippet in report_findings so the backend
                    # ReportSnippetResponse.Snippet is non-null and the UI
                    # shows the Code Snippet panel instead of "Нет данных"
                    "snippet_text":         row.get("snippet_text") or None,
                    "snippet_start_line":   row.get("snippet_start_line") or None,
                    "snippet_end_line":     row.get("snippet_end_line") or None,
                    "snippet_start_column": None,
                    "snippet_end_column":   None,
                    "snippet_language":     row.get("snippet_language") or None,
                    "created_at":           now_utc(),
                })

        for kv in random.sample(KNOWN_VULNS_POOL,
                                min(known_n, len(KNOWN_VULNS_POOL))):
            sc = random.choice(list(SCANNER_RULE_MAP))
            rl = next(
                (r for r in SCANNER_RULE_MAP[sc] if r["rule_id"] == kv["rule_id"]),
                random.choice(SCANNER_RULE_MAP[sc]),
            )
            rpt = random.choice(rpts)
            loc = calculate_location_hash(kv["file_path"], kv["line"],
                                          kv["line"] + 5, "")
            row = _make_code_row(pid, rl, sc,
                                  group_id=random.choice(groups)["id"] if groups else None)
            row.update({
                "file_path": kv["file_path"],
                "line_start": kv["line"],
                "line_end": kv["line"] + 5,
                "deduplication_hash": calculate_dedup_hash(pid, rl["rule_id"], loc),
            })
            _ins(row, rpt)

        for _ in range(total - known_n):
            sc = random.choice(list(SCANNER_RULE_MAP))
            rl = random.choice(SCANNER_RULE_MAP[sc])
            rpt = random.choice(rpts)
            g = random.choice(groups) if groups and random.random() < 0.15 else None
            _ins(_make_code_row(pid, rl, sc, group_id=g["id"] if g else None), rpt)

    if rfs:
        bulk_insert(conn, "report_findings", rfs, conflict="DO NOTHING")
    return all_f, rfs


def _build_trail(domain: str, ip: str, port: int, proto: str) -> list:
    svc = {80: "http", 443: "https", 22: "ssh",
           5432: "postgresql", 8080: "http"}.get(port, "unknown")
    return [{
        "type": "config", "value": domain,
        "via": {
            "type": "dns_resolve", "value": ip,
            "via": {
                "type": "nmap",
                "value": f"{ip}:{port}/{proto} ({svc})",
            },
        },
    }]


def _net_row(pid: str, scope: dict, rule: dict, scanner: str) -> dict:
    live_ips = scope.get("live_ips", ["10.0.0.1"])
    domain = scope.get("domain", "example.com")
    ip = random.choice(live_ips)
    port = rule.get("port") or random.choice([80, 443, 22, 8080, 5432, 3306])
    proto = "tcp"
    loc = network_location_hash(ip, port, proto)
    dedup = calculate_network_dedup_hash(pid, rule.get("cve") or "", loc)
    trail = _build_trail(domain, ip, port, proto)
    sev = rule["severity"]
    status = random.choices(FINDING_STATUSES, STATUS_WEIGHTS)[0]
    first = past_range(1, 60)
    sla_s = first if status == "confirmed" else None
    sla_e = (sla_s + timedelta(days=SLA_DAYS[sev])) if sla_s else None
    return {
        "id": str(uuid.uuid4()),
        "deduplication_hash": dedup,
        "product_id": pid,
        "title": rule["title"],
        "description": f"Network vulnerability detected by {scanner}: {rule['title']}",
        "severity": sev,
        "current_status": status,
        "cwe_id": rule.get("cwe") or "",
        "cve": rule.get("cve") or "",
        "rule_id": rule["rule_id"],
        "host": f"host-{ip.replace('.', '-')}.{domain}",
        "ip": ip,
        "port": port,
        "protocol": proto,
        "service": rule.get("service") or "",
        "properties": json.dumps({"trails": trail, "scanner_name": scanner}),
        "tags": json.dumps(["external", "security-scan"]),
        "group_id": None,
        "first_seen_at": first,
        "last_seen_at": now_utc(),
        "sla_started_at": sla_s,
        "sla_expires_at": sla_e,
        "created_at": first,
        "updated_at": now_utc(),
    }


def gen_network_findings(
    conn, products: list, product_reports: dict,
    scope_data: dict, scale: Scale,
) -> tuple:
    all_f: list = []
    rfs: list = []
    min_f, max_f = scale.findings_per_product

    for product in products:
        pid = str(product["id"])
        prj_id = str(product["project_id"])
        rpts = product_reports.get(pid, [])
        scope = scope_data.get(prj_id, {})
        nessus      = [r for r in rpts if r["engine"] == "nessus"]
        nuclei      = [r for r in rpts if r["engine"] == "nuclei"]
        domainscope = [r for r in rpts if r["engine"] == "domainscope"]

        # Every product should have network findings — use whichever scanners are available
        net_pool = nessus + nuclei + domainscope
        if not net_pool:
            continue

        target  = random.randint(max(3, min_f // 3), max(4, max_f // 2))
        n_dedup = max(1, int(target * 0.20))
        seen: set = set()

        def _ins(row, rpt):
            h = row["deduplication_hash"]
            if h in seen:
                return
            seen.add(h)
            n = bulk_insert(conn, "findings", [row],
                            conflict="(deduplication_hash) WHERE deleted_at IS NULL DO NOTHING")
            if n > 0:
                all_f.append(row)
            rfs.append({
                "report_id": str(rpt["id"]),
                "finding_id": str(row["id"]),
                "raw_details": json.dumps({"scanner": rpt["engine"]}),
                "created_at": now_utc(),
            })

        # Cross-scanner dedup pairs: same CVE+IP found by nessus AND nuclei
        if nessus and nuclei:
            cve_rules = [r for r in NESSUS_RULES if r.get("cve")][:n_dedup]
            for rule in cve_rules:
                f1 = _net_row(pid, scope, rule, "nessus")
                _ins(f1, random.choice(nessus))
                rfs.append({
                    "report_id": str(random.choice(nuclei)["id"]),
                    "finding_id": str(f1["id"]),
                    "raw_details": json.dumps({"scanner": "nuclei"}),
                    "created_at": now_utc(),
                })

        # Guaranteed DomainScope findings (domain-based perimeter scan results)
        if domainscope:
            ds_count = max(3, target // 4)
            for _ in range(ds_count):
                rule = random.choice(DOMAINSCOPE_RULES)
                row  = _net_row(pid, scope, rule, "domainscope")
                _ins(row, random.choice(domainscope))

        # Remaining budget: random from nessus/nuclei/domainscope
        remaining = max(0, target - n_dedup - (max(3, target // 4) if domainscope else 0))
        all_net_rules = NESSUS_RULES + NUCLEI_RULES + DOMAINSCOPE_RULES
        for _ in range(remaining):
            rule = random.choice(all_net_rules)
            if rule in NESSUS_RULES:
                sc, pool_r = "nessus", nessus or net_pool
            elif rule in NUCLEI_RULES:
                sc, pool_r = "nuclei", nuclei or net_pool
            else:
                sc, pool_r = "domainscope", domainscope or net_pool
            _ins(_net_row(pid, scope, rule, sc), random.choice(pool_r))

    if rfs:
        bulk_insert(conn, "report_findings", rfs, conflict="DO NOTHING")
    return all_f, rfs


def gen_secret_findings(
    conn, products: list, product_reports: dict, product_groups: dict,
) -> tuple:
    all_f: list = []
    rfs: list = []

    for product in products:
        pid = str(product["id"])
        rpts = product_reports.get(pid, [])
        groups = product_groups.get(pid, [])
        kf_r = [r for r in rpts if r["engine"] == "kingfisher"]
        if not kf_r:
            continue

        for _ in range(random.randint(2, 5)):
            rule = random.choice(KINGFISHER_RULES)
            fp = random.choice(SECRET_FILE_PATTERNS)
            line = random.randint(1, 50)
            fingerprint = str(random.getrandbits(64))
            dedup = calculate_dedup_hash(pid, rule["rule_id"], fingerprint)
            entropy = round(random.uniform(4.0, 7.5), 2)
            val_status = random.choice([
                "Active Credential", "Inactive Credential", "Not Attempted",
            ])
            masked = rule["snippet_mask"].replace(
                "{masked}", "X" * random.randint(8, 16)
            )
            sev = rule["severity"]
            status = random.choices(FINDING_STATUSES, STATUS_WEIGHTS)[0]
            first = past_range(1, 60)
            sla_s = first if status in ("confirmed", "risk_accepted") else None
            sla_e = (sla_s + timedelta(days=SLA_DAYS[sev])) if sla_s else None
            g = random.choice(groups) if groups and random.random() < 0.3 else None
            row = {
                "id": str(uuid.uuid4()),
                "deduplication_hash": dedup,
                "product_id": pid,
                "title": rule["title"],
                "description": (
                    f"Secret detected by Kingfisher. Entropy: {entropy}. "
                    f"Status: {val_status}. Rotate immediately if active."
                ),
                "severity": sev,
                "current_status": status,
                "cwe_id": "CWE-798",
                "cve": "",
                "rule_id": rule["rule_id"],
                "file_path": fp,
                "line_start": line,
                "line_end": line,
                "snippet_text": masked,
                "snippet_start_line": line,
                "snippet_end_line": line,
                "snippet_language": "text",
                "properties": json.dumps({
                    "entropy": str(entropy),
                    "validation_status": val_status,
                    "commit_id": random_git_sha(),
                    "scanner_name": "kingfisher",
                }),
                "tags": json.dumps([]),
                "group_id": str(g["id"]) if g else None,
                "first_seen_at": first,
                "last_seen_at": now_utc(),
                "sla_started_at": sla_s,
                "sla_expires_at": sla_e,
                "created_at": first,
                "updated_at": now_utc(),
            }
            n = bulk_insert(conn, "findings", [row],
                            conflict="(deduplication_hash) WHERE deleted_at IS NULL DO NOTHING")
            if n > 0:
                all_f.append(row)
                rfs.append({
                    "report_id":          str(random.choice(kf_r)["id"]),
                    "finding_id":         str(row["id"]),
                    "raw_details":        json.dumps({
                        "scanner":           "kingfisher",
                        "entropy":           entropy,
                        "validation_status": val_status,
                    }),
                    "snippet_text":         row.get("snippet_text") or None,
                    "snippet_start_line":   row.get("snippet_start_line") or None,
                    "snippet_end_line":     row.get("snippet_end_line") or None,
                    "snippet_start_column": None,
                    "snippet_end_column":   None,
                    "snippet_language":     row.get("snippet_language") or None,
                    "created_at":           now_utc(),
                })

    if rfs:
        bulk_insert(conn, "report_findings", rfs, conflict="DO NOTHING")
    return all_f, rfs
