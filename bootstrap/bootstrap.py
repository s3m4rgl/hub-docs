#!/usr/bin/env python3
"""
Bootstrap для локального запуска Security Hub через Docker Compose.

Создаёт минимальный рабочий набор и связывает DomainScope с Hub автоматически:
  - администратор с паролем (вход по логину/паролю);
  - один проект и один продукт;
  - сервисный аккаунт сканера с API-ключом (право upload_report на продукт);
  - файл /shared/scanner.env с product_id и токеном — его читает DomainScope.

Скрипт идемпотентен: повторный запуск ничего не ломает. Сущности создаются с
фиксированными идентификаторами, ключ сканера выдаётся один раз и сохраняется в
общий том.

Зависимости (ставятся в compose-команде): psycopg2-binary, bcrypt.
"""
import base64
import hashlib
import os
import secrets
import sys
import time
import uuid
from datetime import datetime, timezone

import bcrypt
import psycopg2
import psycopg2.extras

# Фиксированные идентификаторы — обеспечивают идемпотентность.
PROJECT_ID = "11111111-1111-1111-1111-111111111111"
PRODUCT_ID = "22222222-2222-2222-2222-222222222222"
SA_ID = "33333333-3333-3333-3333-333333333333"

# admin@localhost.local — тот же email, что backend создаёт сам при старте
# (createLocalTestUser, без пароля). bootstrap навешивает на эту запись пароль
# и роль admin через ON CONFLICT DO UPDATE. Единый логин с helm-инсталляцией.
ADMIN_EMAIL = os.getenv("LOCAL_ADMIN_EMAIL", "admin@localhost.local")
ADMIN_PASSWORD = os.getenv("LOCAL_ADMIN_PASSWORD", "Admin1234!")
PRODUCT_NAME = os.getenv("SCANNER_PRODUCT_NAME", "Local Scan")
PROJECT_NAME = os.getenv("SCANNER_PROJECT_NAME", "Local Evaluation")
SHARED_ENV = os.getenv("SCANNER_ENV_FILE", "/shared/scanner.env")


def now():
    return datetime.now(timezone.utc)


def hash_password(plaintext: str) -> str:
    return bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=10)).decode()


def generate_api_key():
    """Формат backend: sa_{8hex}_{base64url}; в БД хранится sha256(plaintext)."""
    while True:
        raw = secrets.token_bytes(32)
        prefix = raw[:4].hex()
        secret_part = base64.urlsafe_b64encode(raw).decode()
        if "_" not in secret_part:
            break
    plaintext = f"sa_{prefix}_{secret_part}"
    return plaintext, prefix, hashlib.sha256(plaintext.encode()).hexdigest()


def connect():
    dsn = dict(
        host=os.getenv("DB_HOST", "postgres"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "securityhub"),
        user=os.getenv("DB_USER", "securityhub"),
        password=os.getenv("DB_PASSWORD", "securityhub123"),
    )
    last = None
    for attempt in range(60):
        try:
            conn = psycopg2.connect(**dsn)
            conn.autocommit = False
            return conn
        except psycopg2.OperationalError as exc:
            last = exc
            time.sleep(2)
    print(f"bootstrap: не удалось подключиться к БД: {last}", file=sys.stderr)
    sys.exit(1)


def wait_for_schema(conn):
    """Дожидаемся, пока backend применит миграции (создаст нужные таблицы)."""
    needed = ["users", "projects", "products", "service_accounts",
              "api_keys", "service_account_permissions", "casbin_rule"]
    for attempt in range(120):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name = ANY(%s)", (needed,))
            if cur.fetchone()[0] == len(needed):
                return
        conn.rollback()
        time.sleep(2)
    print("bootstrap: миграции не применились вовремя", file=sys.stderr)
    sys.exit(1)


def seed(conn):
    ts = now()
    with conn.cursor() as cur:
        # Администратор с паролем (вход по логину/паролю).
        admin_id = str(uuid.uuid4())
        cur.execute(
            """INSERT INTO users (id, keycloak_id, email, username, full_name,
                                  is_active, password_hash, created_at, updated_at)
               VALUES (%s,%s,%s,'admin','Administrator',true,%s,%s,%s)
               ON CONFLICT (email) DO UPDATE
                 SET password_hash = EXCLUDED.password_hash, updated_at = EXCLUDED.updated_at
               RETURNING id""",
            (admin_id, "local:admin", ADMIN_EMAIL, hash_password(ADMIN_PASSWORD), ts, ts))
        admin_id = str(cur.fetchone()[0])

        # Роль администратора (casbin grouping policy).
        cur.execute(
            "INSERT INTO casbin_rule (ptype, v0, v1) VALUES ('g',%s,'admin') "
            "ON CONFLICT DO NOTHING", (admin_id,))

        # Проект и продукт.
        cur.execute(
            """INSERT INTO projects (id, name, description, owner_id, created_at, updated_at)
               VALUES (%s,%s,'Локальный стенд для ознакомления',%s,%s,%s)
               ON CONFLICT (id) DO NOTHING""",
            (PROJECT_ID, PROJECT_NAME, admin_id, ts, ts))
        cur.execute(
            """INSERT INTO products (id, project_id, name, description, default_branch,
                                     created_at, updated_at)
               VALUES (%s,%s,%s,'Продукт для загрузки результатов сканера','main',%s,%s)
               ON CONFLICT (id) DO NOTHING""",
            (PRODUCT_ID, PROJECT_ID, PRODUCT_NAME, ts, ts))

        # Сервисный аккаунт сканера.
        cur.execute(
            """INSERT INTO service_accounts (id, name, description, owner_id, is_active,
                                             created_at, updated_at)
               VALUES (%s,'local-scanner','DomainScope local scanner',%s,true,%s,%s)
               ON CONFLICT (id) DO NOTHING""",
            (SA_ID, admin_id, ts, ts))

        # Право на загрузку отчётов в продукт + глобальное чтение находок.
        for rtype, rid, scope in (("product", PRODUCT_ID, "upload_report"),
                                  ("project", None, "read_findings")):
            cur.execute(
                """INSERT INTO service_account_permissions
                       (id, service_account_id, resource_type, resource_id, scope,
                        is_blocked, created_at)
                   VALUES (%s,%s,%s,%s,%s,false,%s) ON CONFLICT DO NOTHING""",
                (str(uuid.uuid4()), SA_ID, rtype, rid, scope, ts))

        # Цели сканирования (домены) — DomainScope заберёт их из scope проекта.
        targets = [t.strip() for t in os.getenv("DOMAINSCOPE_TARGETS", "").split(",") if t.strip()]
        for host in targets:
            entry_type = "cidr" if host[0].isdigit() else "domain"
            # У scan_scope_entries нет уникального индекса на (project,type,value),
            # поэтому проверяем наличие вручную (идемпотентность).
            cur.execute(
                "SELECT 1 FROM scan_scope_entries "
                "WHERE project_id=%s AND entry_type=%s AND value=%s",
                (PROJECT_ID, entry_type, host))
            if cur.fetchone():
                continue
            cur.execute(
                """INSERT INTO scan_scope_entries
                       (id, project_id, entry_type, value, scope_action, source,
                        description, tags, disabled_by, disabled_reason,
                        created_at, updated_at)
                   VALUES (%s,%s,%s,%s,'include','manual','Локальная цель сканирования',
                           '[]','','',%s,%s)""",
                (str(uuid.uuid4()), PROJECT_ID, entry_type, host, ts, ts))

        # API-ключ сканера выдаём один раз и сохраняем в общий том.
        if os.path.exists(SHARED_ENV):
            print(f"bootstrap: {SHARED_ENV} уже существует — ключ сканера сохранён ранее")
        else:
            plaintext, prefix, key_hash = generate_api_key()
            cur.execute(
                """INSERT INTO api_keys (id, service_account_id, key_hash, key_prefix,
                                         name, expires_at, is_active, created_at)
                   VALUES (%s,%s,%s,%s,'primary',NULL,true,%s)""",
                (str(uuid.uuid4()), SA_ID, key_hash, prefix, ts))
            os.makedirs(os.path.dirname(SHARED_ENV), exist_ok=True)
            with open(SHARED_ENV, "w", encoding="utf-8") as fh:
                fh.write(f"DOMAINSCOPE_SARIF_PRODUCT_ID={PRODUCT_ID}\n")
                fh.write(f"DOMAINSCOPE_SARIF_API_TOKEN={plaintext}\n")
                fh.write(f"DOMAINSCOPE_HUB_PROJECT_IDS={PROJECT_ID}\n")
            os.chmod(SHARED_ENV, 0o644)
            print(f"bootstrap: ключ сканера сохранён в {SHARED_ENV}")

    conn.commit()


def main():
    conn = connect()
    wait_for_schema(conn)
    seed(conn)
    print("bootstrap: готово")
    print(f"  Вход в Hub:  {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    print(f"  Продукт:     {PRODUCT_NAME} ({PRODUCT_ID})")
    print("  ВАЖНО: перезапустите backend, чтобы роль администратора применилась:")
    print("         docker compose restart backend")


if __name__ == "__main__":
    main()
