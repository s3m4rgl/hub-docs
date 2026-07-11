#!/usr/bin/env python3
"""User, tag, and casbin rule generators."""
import random
import uuid

import bcrypt

from _seed_base import TAG_POOL, Scale, bulk_insert, fetchall, now_utc, past_range

AI_SYSTEM_USER_ID = "8e4cf47a-1d9b-4f3c-b2e0-7a5d3c8f1e96"
ADMIN_EMAIL       = "admin@demo.local"
ADMIN_PASSWORD    = "Demo1234!"


def _hash_password(plaintext: str) -> str:
    return bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=10)).decode()


def gen_users(conn, scale: Scale, fake) -> list:
    rows = [
        {
            "id": AI_SYSTEM_USER_ID,
            "keycloak_id": "system:ai-analysis",
            "email": "ai-analysis@system.local",
            "username": "ai-analysis",
            "full_name": "AI Analysis",
            "is_active": True,
            "password_hash": None,
            "created_at": now_utc(),
            "updated_at": now_utc(),
        },
        {
            "id": str(uuid.uuid4()),
            "keycloak_id": "local:admin",
            "email": ADMIN_EMAIL,
            "username": "admin",
            "full_name": "Demo Administrator",
            "is_active": True,
            "password_hash": _hash_password(ADMIN_PASSWORD),
            "created_at": now_utc(),
            "updated_at": now_utc(),
        },
    ]
    for _ in range(scale.users - 1):
        first, last = fake.first_name(), fake.last_name()
        uname = f"{first.lower()}.{last.lower()}"
        rows.append({
            "id": str(uuid.uuid4()),
            "keycloak_id": f"local:{uname}",
            "email": f"{uname}@demo.local",
            "username": uname,
            "full_name": f"{first} {last}",
            "is_active": True,
            "password_hash": _hash_password(ADMIN_PASSWORD),
            "created_at": past_range(30, 365),
            "updated_at": now_utc(),
        })
    for row in rows:
        bulk_insert(conn, "users", [row],
                    conflict="(email) DO UPDATE SET updated_at = EXCLUDED.updated_at")
    return fetchall(conn, "SELECT * FROM users WHERE email != 'ai-analysis@system.local'")


def gen_tags(conn, fake) -> list:
    rows = [
        {"id": str(uuid.uuid4()), "name": t,
         "created_at": now_utc(), "updated_at": now_utc()}
        for t in TAG_POOL
    ]
    bulk_insert(conn, "tags", rows, conflict="(name) DO NOTHING")
    return fetchall(conn, "SELECT * FROM tags")


def gen_casbin_rules(conn, users: list, projects: list) -> None:
    admin = next((u for u in users if u["email"] == ADMIN_EMAIL), None)
    rules = []
    if admin:
        rules.append({
            "ptype": "g", "v0": str(admin["id"]), "v1": "admin",
            "v2": None, "v3": None, "v4": None, "v5": None,
        })
    for project in projects:
        if not project.get("owner_id"):
            continue
        role = f"project_owner_{project['id']}"
        rules.append({
            "ptype": "p", "v0": role,
            "v1": f"project:{project['id']}", "v2": ".*", "v3": "allow",
            "v4": None, "v5": None,
        })
        rules.append({
            "ptype": "g2", "v0": str(project["owner_id"]), "v1": role,
            "v2": None, "v3": None, "v4": None, "v5": None,
        })
    if rules:
        bulk_insert(conn, "casbin_rule", rules, conflict="DO NOTHING")
