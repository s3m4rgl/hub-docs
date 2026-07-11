#!/usr/bin/env python3
"""
SecurityHub Demo Seed Script

Usage:
  python scripts/seed_demo.py --db-url "postgres://user:pass@localhost:5432/db"
  python scripts/seed_demo.py --db-url "..." --scale medium --clean
  python scripts/seed_demo.py --db-url "..." --scale small --seed 42
"""
import argparse
import random
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from faker import Faker

from _seed_base import SCALES, connect, fetchall
from _seed_users import gen_users, gen_tags, gen_casbin_rules
from _seed_projects import gen_projects, gen_products, gen_project_tags, gen_product_tags
from _seed_scope import gen_scope
from _seed_findings import (
    gen_reports,
    gen_finding_groups,
    gen_code_findings,
    gen_network_findings,
    gen_secret_findings,
)
from _seed_social import (
    gen_comments,
    gen_assignments,
    gen_access_requests,
    gen_sla_violations,
    gen_audit_logs,
)
from _seed_sa import gen_service_accounts

CLEAN_TABLES = [
    # Truncated so backend's licensing.EnsureInstance (idempotent, runs on every
    # startup) recreates this row with created_at=NOW() on next restart. Without
    # this, GetInstanceCreatedAt's MIN(created_at) across business tables keeps
    # picking up this table's original provisioning date forever — no amount of
    # reseeding the other tables can extend the license grace period past it.
    "license_instance",
    "audit_logs",
    "assignments",
    "comments",
    "sla_violations",
    "access_requests",
    "report_findings",
    "reports",
    "findings",
    "finding_groups",
    "scan_scope_assets",
    "scan_scope_proposals",
    "scan_scope_sync_jobs",
    "scan_scope_entries",
    "service_account_permissions",
    "api_keys",
    "service_accounts",
    "product_tags",
    "project_tags",
    "tags",
    "products",
    "projects",
    "refresh_tokens",
    "casbin_rule",
    "users",
]


def clean_db(conn) -> None:
    print("Cleaning database...")
    with conn.cursor() as cur:
        for table in CLEAN_TABLES:
            cur.execute(f"TRUNCATE {table} CASCADE")
    conn.commit()
    print("  Done.")


def _count(conn, table: str, where: str = "", params=None) -> int:
    sql = f"SELECT COUNT(*) AS n FROM {table}"
    if where:
        sql += f" WHERE {where}"
    rows = fetchall(conn, sql, params)
    return int(rows[0]["n"]) if rows else 0


def print_summary(stats: dict, api_keys: list) -> None:
    print("\n" + "=" * 60)
    print("  SEED COMPLETE")
    print("=" * 60)
    for label, value in stats.items():
        print(f"  {label:<24} {value}")
    if api_keys:
        print()
        print("  API KEYS (copy now — not shown again):")
        for key_line in api_keys:
            print(f"    {key_line}")
    print("=" * 60)


def upload_full_sarif(api_keys: list, products: list) -> None:
    """Best-effort upload of the rich "full sarif" demo report via the API so the
    demo showcases full SARIF 2.1.0 rendering (code flows, fixes, taxonomies).
    The resulting findings are titled "Full SARIF demo: ..." and are findable by
    searching "full sarif". Uses the gitlab-ci-scanner service-account key
    (scope upload_report) so it works right after a --clean reseed without
    depending on the backend's Casbin cache. Never raises (demo must not break)."""
    import os
    import urllib.request
    backend = os.environ.get("BACKEND_URL", "http://hub-backend:8082").rstrip("/")
    sarif_path = os.environ.get("FULL_SARIF_PATH") or os.path.join(
        os.path.dirname(__file__), "full-sarif.sarif")
    key = next((s.split(": ", 1)[1].strip()
                for s in api_keys if s.startswith("gitlab-ci-scanner")), None)
    if not key or not products or not os.path.exists(sarif_path):
        print("  full-sarif: skipped (missing key/products/file)")
        return
    pid = str(products[0]["id"])
    try:
        with open(sarif_path, "rb") as fh:
            payload = fh.read()
        boundary = "----fullsarif%d" % random.randint(100000, 999999)
        b = boundary.encode()
        body = (
            b"--" + b + b"\r\nContent-Disposition: form-data; name=\"engine\"\r\n\r\nfullsarif-demo\r\n"
            + b"--" + b + b"\r\nContent-Disposition: form-data; name=\"file\"; filename=\"full-sarif.sarif\"\r\n"
            + b"Content-Type: application/json\r\n\r\n" + payload + b"\r\n--" + b + b"--\r\n"
        )
        req = urllib.request.Request(
            backend + "/api/v1/products/%s/reports" % pid, data=body, method="POST",
            headers={"X-API-Key": key,
                     "Content-Type": "multipart/form-data; boundary=%s" % boundary})
        resp = urllib.request.urlopen(req, timeout=30)
        print("  full-sarif: uploaded (HTTP %s) → searchable as 'full sarif'" % resp.status)
    except Exception as e:  # noqa: BLE001 — demo seeding must never hard-fail here
        print("  full-sarif: upload failed (non-fatal): %s" % e)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed SecurityHub with demo data")
    parser.add_argument("--db-url", required=True, help="PostgreSQL DSN")
    parser.add_argument(
        "--scale", choices=["small", "medium", "large"], default="small"
    )
    parser.add_argument(
        "--clean", action="store_true", help="Truncate all tables before seeding"
    )
    parser.add_argument(
        "--seed", type=int, default=None, help="Random seed for reproducibility"
    )
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)
        Faker.seed(args.seed)

    fake = Faker()
    scale = SCALES[args.scale]
    conn = connect(args.db_url)

    try:
        if args.clean:
            clean_db(conn)

        print(f"Seeding ({args.scale} scale)...")

        # Phase 1: Users & tags
        users = gen_users(conn, scale, fake)
        tags = gen_tags(conn, fake)
        conn.commit()

        # Phase 2: Projects & products
        projects = gen_projects(conn, scale, users, fake)
        products = gen_products(conn, projects, fake)
        gen_project_tags(conn, projects, tags)
        gen_product_tags(conn, products, tags)
        conn.commit()

        # Phase 3: Perimeter scope (feeds into network findings)
        scope_data = gen_scope(conn, projects, scale, users)
        conn.commit()

        # Phase 4: Reports & finding groups (must exist before findings)
        product_reports = gen_reports(conn, products, users)
        product_groups = gen_finding_groups(conn, products, users)
        conn.commit()

        # Phase 5: Findings
        code_f, _ = gen_code_findings(
            conn, products, product_reports, product_groups, scale
        )
        net_f, _ = gen_network_findings(
            conn, products, product_reports, scope_data, scale
        )
        secret_f, _ = gen_secret_findings(
            conn, products, product_reports, product_groups
        )
        conn.commit()

        all_findings = code_f + net_f + secret_f

        # Phase 6: Social layer
        gen_comments(conn, all_findings, users, fake)
        gen_assignments(conn, all_findings, users)
        gen_access_requests(conn, users, projects)
        gen_sla_violations(conn, all_findings)
        gen_audit_logs(conn, users, all_findings, projects, fake)
        conn.commit()

        # Phase 7: Service accounts & RBAC
        api_keys = gen_service_accounts(conn, users, products, projects, scale)
        gen_casbin_rules(conn, users, projects)
        conn.commit()

        # Phase 8: rich "full sarif" demo report — uploaded via API so the parser
        # populates code flows / fixes / taxonomies (showcases full SARIF rendering).
        upload_full_sarif(api_keys, products)

        stats = {
            "Users":             _count(conn, "users",
                                        "email != 'ai-analysis@system.local'"),
            "Projects":          _count(conn, "projects"),
            "Products":          _count(conn, "products"),
            "Tags":              _count(conn, "tags"),
            "Scope entries":     _count(conn, "scan_scope_entries"),
            "  active":          _count(conn, "scan_scope_entries",
                                        "disabled_at IS NULL"),
            "  disabled":        _count(conn, "scan_scope_entries",
                                        "disabled_at IS NOT NULL"),
            "Scope proposals":   _count(conn, "scan_scope_proposals"),
            "Reports":           _count(conn, "reports"),
            "Finding groups":    _count(conn, "finding_groups"),
            "Findings":          len(all_findings),
            "Comments":          _count(conn, "comments"),
            "Assignments":       _count(conn, "assignments"),
            "SLA violations":    _count(conn, "sla_violations"),
            "Access requests":   _count(conn, "access_requests"),
            "Service accounts":  _count(conn, "service_accounts"),
        }
        print_summary(stats, api_keys)

    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
