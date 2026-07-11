#!/usr/bin/env python3
"""Service account, API key, and permission generators."""
import random
import uuid

from _seed_base import (
    SA_ARCHETYPES, Scale, bulk_insert, generate_api_key, now_utc, past_range,
)

SCOPE_READ = "read_findings"


def gen_service_accounts(
    conn, users: list, products: list, projects: list, scale: Scale,
) -> list:
    """Returns list of plaintext API key strings — print once to stdout."""
    plaintext_keys: list = []
    for arch in SA_ARCHETYPES[: scale.service_accounts]:
        owner = random.choice(users)
        sa_id = str(uuid.uuid4())
        bulk_insert(conn, "service_accounts", [{
            "id": sa_id,
            "name": arch["name_prefix"],
            "description": arch["description"],
            "owner_id": str(owner["id"]),
            "is_active": True,
            "created_at": past_range(1, 60),
            "updated_at": now_utc(),
        }], conflict="DO NOTHING")

        for i in range(arch["num_keys"]):
            pt, prefix, key_hash = generate_api_key()
            bulk_insert(conn, "api_keys", [{
                "id": str(uuid.uuid4()),
                "service_account_id": sa_id,
                "key_hash": key_hash,
                "key_prefix": prefix,
                "name": "primary" if i == 0 else "backup",
                "expires_at": None,
                "is_active": True,
                "created_at": now_utc(),
            }], conflict="DO NOTHING")
            if i == 0:
                plaintext_keys.append(f"{arch['name_prefix']}: {pt}")

        perms = [
            {
                "id": str(uuid.uuid4()),
                "service_account_id": sa_id,
                "resource_type": "product",
                "resource_id": str(p["id"]),
                "scope": arch["scope"],
                "is_blocked": False,
                "created_at": now_utc(),
            }
            for p in products[: min(3, len(products))]
        ]
        # Global read permission
        perms.append({
            "id": str(uuid.uuid4()),
            "service_account_id": sa_id,
            "resource_type": "project",
            "resource_id": None,
            "scope": SCOPE_READ,
            "is_blocked": False,
            "created_at": now_utc(),
        })
        bulk_insert(conn, "service_account_permissions", perms, conflict="DO NOTHING")

    return plaintext_keys
