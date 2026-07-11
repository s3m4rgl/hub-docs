#!/usr/bin/env python3
"""Project, product, and tag-association generators."""
import random
import uuid

from _seed_base import (
    COMPANY_POOL, PRODUCT_ARCHETYPES, Scale,
    bulk_insert, fetchall, now_utc, past_range, upsert_by,
)

DEFAULT_SLA = {"critical": 7, "high": 14, "medium": 30, "low": 90}


def _slug(name: str) -> str:
    return name.lower().replace(" ", "-").replace("(", "").replace(")", "")


def gen_projects(conn, scale: Scale, users: list, fake) -> list:
    non_admin = [u for u in users if "admin" not in u["email"]]
    pool = random.sample(COMPANY_POOL, min(scale.projects, len(COMPANY_POOL)))
    for i, company in enumerate(pool):
        owner = non_admin[i % len(non_admin)] if non_admin else users[0]
        upsert_by(conn, "projects", {
            "id": str(uuid.uuid4()),
            "name": company,
            "description": f"Security scanning scope for {company} infrastructure",
            "owner_id": str(owner["id"]),
            "sla_config": DEFAULT_SLA,
            "jira_config": {
                "base_url": f"https://jira.{_slug(company)}.internal",
                "project_key": company[:3].upper() + "SEC",
                "issue_type": "Bug",
            },
            "mattermost_config": {
                "webhook_url": f"https://mm.{_slug(company)}.internal/hooks/xxx",
                "channel": "security-alerts",
            },
            "created_at": past_range(60, 365),
            "updated_at": now_utc(),
        }, conflict_cols=["name"])
    return fetchall(conn, "SELECT * FROM projects WHERE name = ANY(%s)", (pool,))


def gen_products(conn, projects: list, fake) -> list:
    for project in projects:
        archetypes = random.sample(PRODUCT_ARCHETYPES, random.randint(2, 4))
        for arch in archetypes:
            upsert_by(conn, "products", {
                "id": str(uuid.uuid4()),
                "project_id": str(project["id"]),
                "name": arch["name"],
                "description": f"{arch['name']} for {project['name']}",
                "repository_url": (
                    f"https://gitlab.com/{_slug(project['name'])}/{arch['repo_suffix']}"
                ),
                "default_branch": arch["default_branch"],
                "created_at": past_range(30, 300),
                "updated_at": now_utc(),
            }, conflict_cols=["project_id", "name"])
    return fetchall(
        conn,
        "SELECT * FROM products WHERE project_id::text = ANY(%s)",
        ([str(p["id"]) for p in projects],),
    )


def gen_project_tags(conn, projects: list, tags: list) -> None:
    tag_map = {t["name"]: t["id"] for t in tags}
    rows = []
    for project in projects:
        for tag_name in random.sample(list(tag_map), random.randint(1, 3)):
            rows.append({
                "project_id": str(project["id"]),
                "tag_id": str(tag_map[tag_name]),
            })
    bulk_insert(conn, "project_tags", rows, conflict="DO NOTHING")


def gen_product_tags(conn, products: list, tags: list) -> None:
    tag_map = {t["name"]: t["id"] for t in tags}
    rows = []
    for product in products:
        for tag_name in random.sample(list(tag_map), random.randint(0, 2)):
            rows.append({
                "product_id": str(product["id"]),
                "tag_id": str(tag_map[tag_name]),
            })
    bulk_insert(conn, "product_tags", rows, conflict="DO NOTHING")
