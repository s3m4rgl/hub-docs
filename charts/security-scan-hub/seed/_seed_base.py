#!/usr/bin/env python3
"""Base config, DB helpers, hash utils for seed_demo."""

import hashlib
import json
import random
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras


@dataclass
class Scale:
    projects: int
    products_per_project: tuple
    findings_per_product: tuple
    users: int
    service_accounts: int
    scope_entries_per_project: tuple

SCALES = {
    "small":  Scale(2,  (2, 3),  (15, 25), 6,  1, (8, 12)),
    "medium": Scale(5,  (3, 4),  (25, 40), 12, 2, (15, 25)),
    "large":  Scale(10, (4, 5),  (40, 60), 20, 3, (30, 50)),
}

COMPANY_POOL = [
    "Acme Corp", "Nexus Digital", "Vertex Systems", "Orbis Security",
    "Helix Platform", "Stratus Cloud", "Meridian Labs", "Apex Fintech",
    "Quantum Networks", "Nova Retail", "Polaris DevOps", "Zenith Healthcare",
    "Atlas Infrastructure", "Prism Analytics", "Cipher Defense",
]

PRODUCT_ARCHETYPES = [
    {"name": "Backend API",          "repo_suffix": "backend-api",    "default_branch": "main",    "lang": "go"},
    {"name": "Frontend App",         "repo_suffix": "frontend",       "default_branch": "main",    "lang": "typescript"},
    {"name": "Mobile Client",        "repo_suffix": "mobile",         "default_branch": "develop", "lang": "kotlin"},
    {"name": "Auth Service",         "repo_suffix": "auth-service",   "default_branch": "main",    "lang": "go"},
    {"name": "Data Pipeline",        "repo_suffix": "data-pipeline",  "default_branch": "master",  "lang": "python"},
    {"name": "IaC (Terraform)",      "repo_suffix": "infrastructure", "default_branch": "main",    "lang": "hcl"},
    {"name": "Helm Charts",          "repo_suffix": "helm-charts",    "default_branch": "main",    "lang": "yaml"},
    {"name": "Worker Service",       "repo_suffix": "worker",         "default_branch": "main",    "lang": "go"},
    {"name": "Admin Panel",          "repo_suffix": "admin-panel",    "default_branch": "main",    "lang": "typescript"},
    {"name": "Notification Service", "repo_suffix": "notifications",  "default_branch": "main",    "lang": "python"},
]

TAG_POOL = [
    "production", "staging", "critical", "compliance", "external",
    "internal", "security-scan", "pci-dss", "hipaa", "gdpr",
    "k8s", "docker", "legacy", "microservice", "api-gateway",
]

SEMGREP_RULES = [
    {"rule_id": "python.django.security.audit.xss.xss-html-string-concat",
     "title": "Potential XSS via string concatenation in template",
     "cwe": "CWE-79", "severity": "HIGH", "lang": "python",
     "file_pattern": "views.py",
     "snippet": """def user_profile(request, username):
    user = get_object_or_404(User, username=username)
    bio = request.GET.get("bio", "")
    # BUG: user input directly concatenated into HTML
    html = "<div class=\"profile\">" + bio + "</div>"
    return HttpResponse(html)
"""},
    {"rule_id": "go.lang.security.audit.crypto.use_of_weak_crypto.use-of-md5",
     "title": "Use of weak cryptographic algorithm MD5",
     "cwe": "CWE-327", "severity": "MEDIUM", "lang": "go",
     "file_pattern": "crypto.go",
     "snippet": """func HashPassword(password string) string {
	// BUG: MD5 is cryptographically broken — use bcrypt or argon2
	hash := md5.New()
	hash.Write([]byte(password))
	return hex.EncodeToString(hash.Sum(nil))
}
"""},
    {"rule_id": "javascript.browser.security.insecure-dom-write",
     "title": "Dynamic script injection via DOM write API (XSS risk)",
     "cwe": "CWE-79", "severity": "MEDIUM", "lang": "typescript",
     "file_pattern": "utils.ts",
     "snippet": """export function loadWidget(src: string): void {
  const container = document.getElementById("widget");
  // BUG: src is user-controlled — script injection possible
  const tag = "<script src=\"" + src + "\"><\\/script>";
  container?.insertAdjacentHTML("beforeend", tag);
}
"""},
    {"rule_id": "python.requests.security.no-auth-over-http.no-auth-over-http",
     "title": "Credentials sent over unencrypted HTTP",
     "cwe": "CWE-319", "severity": "HIGH", "lang": "python",
     "file_pattern": "client.py",
     "snippet": """def authenticate(username: str, password: str) -> dict:
    creds = {"username": username, "password": password}
    # BUG: HTTP — credentials sent in plaintext
    resp = requests.post(
        "http://api.internal.company.com/v1/auth/login",
        data=creds, timeout=10,
    )
    resp.raise_for_status()
    return resp.json()
"""},
    {"rule_id": "go.gin.security.audit.path-traversal.path-traversal",
     "title": "Potential path traversal in Gin handler",
     "cwe": "CWE-22", "severity": "HIGH", "lang": "go",
     "file_pattern": "handler.go",
     "snippet": """func (h *FileHandler) Download(c *gin.Context) {
	filename := c.Param("filename")
	// BUG: filename not sanitized — ../../etc/passwd traversal possible
	c.File("/var/data/uploads/" + filename)
}
"""},
    {"rule_id": "python.flask.security.unescaped-template",
     "title": "Unescaped variable in Jinja2 template (XSS risk)",
     "cwe": "CWE-116", "severity": "MEDIUM", "lang": "python",
     "file_pattern": "template.html",
     "snippet": """<section class="user-profile">
  <h2>{{ user.full_name }}</h2>
  {# BUG: |safe disables auto-escaping, XSS if bio contains <script> #}
  <div class="bio">{{ user.bio | safe }}</div>
  <p>Member since: {{ user.created_at | date("Y-m-d") }}</p>
</section>
"""},
    {"rule_id": "go.lang.security.audit.sql.sql-injection",
     "title": "Potential SQL injection via string formatting",
     "cwe": "CWE-89", "severity": "CRITICAL", "lang": "go",
     "file_pattern": "repository.go",
     "snippet": """func (r *UserRepo) FindByRole(role string) ([]User, error) {
	var users []User
	// BUG: role injected — send role="admin' OR '1'='1" to bypass auth
	query := fmt.Sprintf(
		"SELECT * FROM users WHERE role = '%s' AND is_active = true", role)
	result := r.db.Raw(query).Scan(&users)
	return users, result.Error
}
"""},
    {"rule_id": "javascript.react.security.audit.unsafe-html-rendering",
     "title": "React component renders user content as raw HTML (XSS risk)",
     "cwe": "CWE-79", "severity": "HIGH", "lang": "typescript",
     "file_pattern": "Component.tsx",
     "snippet": """interface Props { content: string; author: string }

export const Comment: React.FC<Props> = ({ content, author }) => (
  <div className="comment">
    <strong>{author}</strong>
    {/* BUG: content may contain <script> injected by attacker */}
    <div dangerouslySetInnerHTML={{ __html: content }} />
  </div>
);
"""},
    {"rule_id": "python.django.security.audit.raw-query",
     "title": "Raw SQL query with user-controlled data",
     "cwe": "CWE-89", "severity": "CRITICAL", "lang": "python",
     "file_pattern": "models.py",
     "snippet": """class UserManager(models.Manager):
    def search(self, term: str):
        # BUG: term interpolated directly into SQL — injection possible
        return self.raw(
            f"SELECT * FROM auth_user "
            f"WHERE username LIKE '%{term}%' OR email LIKE '%{term}%'"
        )
"""},
    {"rule_id": "go.lang.security.audit.crypto.insecure-random",
     "title": "Use of math/rand for security-sensitive operations",
     "cwe": "CWE-338", "severity": "MEDIUM", "lang": "go",
     "file_pattern": "token.go",
     "snippet": """func GenerateResetToken(userID int) string {
	// BUG: math/rand is seeded from time — predictable by attacker
	rand.Seed(time.Now().UnixNano())
	token := strconv.Itoa(rand.Intn(1_000_000))
	return fmt.Sprintf("%d-%s", userID, token)
}
"""},
]

TRIVY_RULES = [
    {"rule_id": "CVE-2021-44228",
     "title": "Apache Log4j2 Remote Code Execution (Log4Shell)",
     "cve": "CVE-2021-44228", "cwe": "CWE-502", "severity": "CRITICAL",
     "lang": "xml", "file_pattern": "pom.xml",
     "snippet": """<dependencies>
  <!-- BUG: log4j-core 2.14.1 vulnerable to Log4Shell RCE (CVSS 10.0) -->
  <!-- Fix: upgrade to 2.17.1+ or set log4j2.formatMsgNoLookups=true  -->
  <dependency>
    <groupId>org.apache.logging.log4j</groupId>
    <artifactId>log4j-core</artifactId>
    <version>2.14.1</version>
  </dependency>
</dependencies>
"""},
    {"rule_id": "CVE-2023-44487",
     "title": "HTTP/2 Rapid Reset DoS Attack",
     "cve": "CVE-2023-44487", "cwe": "CWE-400", "severity": "HIGH",
     "lang": "go", "file_pattern": "go.sum",
     "snippet": """# go.sum — vulnerable HTTP/2 implementation
golang.org/x/net v0.10.0 h1:X2//aHkHYFSv+ZNPQ7HM5xOrG0tN7V1Gx3rGMHMiJFI=
golang.org/x/net v0.10.0/go.mod h1:0QNgMBjf+bFp7ZSXwLVxhnElTFnCGFKe5EPpAqI8Vmg=
# BUG: golang.org/x/net < 0.17.0 vulnerable to HTTP/2 Rapid Reset DoS
# Fix: upgrade to v0.17.0 or later
"""},
    {"rule_id": "CVE-2022-42889",
     "title": "Apache Commons Text RCE (Text4Shell)",
     "cve": "CVE-2022-42889", "cwe": "CWE-94", "severity": "CRITICAL",
     "lang": "xml", "file_pattern": "pom.xml",
     "snippet": """<dependency>
  <groupId>org.apache.commons</groupId>
  <!-- BUG: commons-text 1.9 allows RCE via StringSubstitutor interpolation -->
  <!-- Payload: ${script:javascript:java.lang.Runtime.getRuntime().exec('id')} -->
  <artifactId>commons-text</artifactId>
  <version>1.9</version>
</dependency>
"""},
    {"rule_id": "CVE-2022-22965",
     "title": "Spring Framework RCE (Spring4Shell)",
     "cve": "CVE-2022-22965", "cwe": "CWE-94", "severity": "CRITICAL",
     "lang": "xml", "file_pattern": "pom.xml",
     "snippet": """<dependency>
  <groupId>org.springframework</groupId>
  <!-- BUG: spring-web 5.3.17 vulnerable to Spring4Shell data-binding RCE -->
  <!-- Requires JDK 9+, Tomcat as WAR deployment                          -->
  <artifactId>spring-web</artifactId>
  <version>5.3.17</version>
</dependency>
"""},
    {"rule_id": "CVE-2024-21626",
     "title": "runc container escape vulnerability",
     "cve": "CVE-2024-21626", "cwe": "CWE-269", "severity": "HIGH",
     "lang": "dockerfile", "file_pattern": "Dockerfile",
     "snippet": """FROM ubuntu:20.04
# BUG: runc < 1.1.12 leaks /proc/self/fd — allows container breakout
RUN apt-get update && apt-get install -y \
    runc=1.0.0~rc93-0ubuntu1 \
    containerd
COPY entrypoint.sh /
ENTRYPOINT ["/entrypoint.sh"]
"""},
    {"rule_id": "CVE-2023-2650",
     "title": "OpenSSL denial of service",
     "cve": "CVE-2023-2650", "cwe": "CWE-400", "severity": "MEDIUM",
     "lang": "python", "file_pattern": "requirements.txt",
     "snippet": """fastapi==0.100.0
uvicorn[standard]==0.22.0
# BUG: pyOpenSSL 23.0.0 uses OpenSSL < 3.0.9 — OOM DoS via crafted ASN.1 obj
pyOpenSSL==23.0.0
cryptography==40.0.2
"""},
    {"rule_id": "CVE-2021-45046",
     "title": "Apache Log4j2 RCE — incomplete fix for Log4Shell",
     "cve": "CVE-2021-45046", "cwe": "CWE-502", "severity": "CRITICAL",
     "lang": "xml", "file_pattern": "pom.xml",
     "snippet": """<dependency>
  <groupId>org.apache.logging.log4j</groupId>
  <!-- BUG: 2.15.0 was rushed patch — still exploitable via Context Lookups -->
  <!-- Upgrade to 2.17.1+ (Java 8) or 2.12.4+ (Java 7)                   -->
  <artifactId>log4j-core</artifactId>
  <version>2.15.0</version>
</dependency>
"""},
]

CHECKOV_RULES = [
    {"rule_id": "CKV_AWS_18",
     "title": "Ensure the S3 bucket has access logging enabled",
     "cwe": "CWE-778", "severity": "MEDIUM", "lang": "hcl",
     "file_pattern": "s3.tf",
     "snippet": """resource "aws_s3_bucket" "data_lake" {
  bucket = "acme-corp-data-lake-prod"
  tags   = { Environment = "production", Team = "data" }
  # BUG: no logging block — S3 access attempts are not recorded
  # Fix: add logging { target_bucket = aws_s3_bucket.logs.id }
}

resource "aws_s3_bucket_versioning" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id
  versioning_configuration { status = "Enabled" }
}
"""},
    {"rule_id": "CKV_AWS_2",
     "title": "Ensure ALB protocol is HTTPS",
     "cwe": "CWE-319", "severity": "HIGH", "lang": "hcl",
     "file_pattern": "alb.tf",
     "snippet": """resource "aws_alb_listener" "frontend_http" {
  load_balancer_arn = aws_lb.main.arn
  port              = "80"
  # BUG: plain HTTP listener — all traffic transmitted unencrypted
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}
"""},
    {"rule_id": "CKV_K8S_30",
     "title": "Do not admit containers with the NET_RAW capability",
     "cwe": "CWE-250", "severity": "HIGH", "lang": "yaml",
     "file_pattern": "deployment.yaml",
     "snippet": """spec:
  containers:
    - name: backend
      image: acme/backend:1.4.2
      securityContext:
        # BUG: NET_RAW allows raw sockets, ARP spoofing, and MITM attacks
        capabilities:
          add: ["NET_RAW", "NET_ADMIN"]
          drop: []
        runAsNonRoot: true
"""},
    {"rule_id": "CKV_K8S_8",
     "title": "Liveness Probe should be configured",
     "cwe": "CWE-1059", "severity": "LOW", "lang": "yaml",
     "file_pattern": "deployment.yaml",
     "snippet": """spec:
  containers:
    - name: api-server
      image: acme/api:2.1.0
      ports:
        - containerPort: 8082
      resources:
        limits: { cpu: 500m, memory: 512Mi }
      # BUG: no livenessProbe — Kubernetes cannot restart hung processes
      # Fix: add livenessProbe: httpGet: path: /health port: 8082
"""},
    {"rule_id": "CKV_DOCKER_2",
     "title": "Ensure that HEALTHCHECK instructions have been added",
     "cwe": "CWE-1059", "severity": "LOW", "lang": "dockerfile",
     "file_pattern": "Dockerfile",
     "snippet": """FROM node:18-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
COPY . .
# BUG: no HEALTHCHECK — Docker/orchestrators cannot detect unhealthy state
# Fix: HEALTHCHECK CMD curl -f http://localhost:3000/health || exit 1
EXPOSE 3000
CMD ["node", "server.js"]
"""},
    {"rule_id": "CKV_AWS_58",
     "title": "Ensure KMS encryption is enabled for EKS",
     "cwe": "CWE-311", "severity": "HIGH", "lang": "hcl",
     "file_pattern": "eks.tf",
     "snippet": """resource "aws_eks_cluster" "production" {
  name     = "prod-cluster"
  role_arn = aws_iam_role.eks.arn
  vpc_config {
    subnet_ids = var.private_subnet_ids
  }
  # BUG: no encryption_config — Kubernetes secrets stored plaintext in etcd
  # Fix: add encryption_config { resources=["secrets"] provider{key_arn=...} }
}
"""},
]

KICS_RULES = [
    {"rule_id": "6b5b5e14-5c2a-4d24-9e29-dc8e44ec34db",
     "title": "Redis Has No Password",
     "cwe": "CWE-521", "severity": "HIGH", "lang": "yaml",
     "file_pattern": "redis.yaml",
     "snippet": """redis:
  image: redis:7-alpine
  ports:
    - "6379:6379"
  # BUG: no requirepass — unauthenticated access to cache/session store
  command: redis-server
  environment:
    - REDIS_REPLICATION_MODE=master
  volumes:
    - redis_data:/data
"""},
    {"rule_id": "a3d394aa-34e4-4e6c-a8a0-0a9dd90e17d4",
     "title": "Nginx SSL Certificate Verification Disabled",
     "cwe": "CWE-295", "severity": "MEDIUM", "lang": "yaml",
     "file_pattern": "nginx-config.yaml",
     "snippet": """server {
    listen 443 ssl;
    server_name api.internal.company.com;

    # BUG: certificate verification disabled — MITM attacks on upstream possible
    ssl_verify_client off;
    proxy_ssl_verify  off;

    location / {
        proxy_pass https://backend-service:8443;
    }
}
"""},
    {"rule_id": "4ef97e1d-b937-4f37-b5e3-04c9d8a68e67",
     "title": "PostgreSQL Allows Unrestricted Ingress",
     "cwe": "CWE-284", "severity": "HIGH", "lang": "yaml",
     "file_pattern": "postgres.yaml",
     "snippet": """postgresql:
  image: postgres:15
  environment:
    POSTGRES_DB: securityhub
    POSTGRES_USER: app
  # BUG: 0.0.0.0/0 allows any host — DB accessible from Internet if exposed
  pg_hba: "host all all 0.0.0.0/0 md5"
  ports:
    - "5432:5432"  # BUG: DB port bound to all interfaces
"""},
]

NESSUS_RULES = [
    {"rule_id": "nessus:10114", "title": "SSL Version 2 and 3 Protocol Detection",
     "cve": "CVE-2014-3566", "cwe": "CWE-326", "severity": "HIGH",
     "port": 443, "protocol": "tcp", "service": "https"},
    {"rule_id": "nessus:57608", "title": "SMB Signing Not Required",
     "cve": None, "cwe": "CWE-347", "severity": "MEDIUM",
     "port": 445, "protocol": "tcp", "service": "smb"},
    {"rule_id": "nessus:71049", "title": "SSH Weak MAC Algorithms Supported",
     "cve": None, "cwe": "CWE-327", "severity": "LOW",
     "port": 22, "protocol": "tcp", "service": "ssh"},
    {"rule_id": "nessus:20007", "title": "OpenSSL Vulnerability — Infinite Loop DoS",
     "cve": "CVE-2022-0778", "cwe": "CWE-835", "severity": "HIGH",
     "port": 443, "protocol": "tcp", "service": "https"},
    {"rule_id": "nessus:104743", "title": "TLS Version 1.0 Protocol Detection",
     "cve": None, "cwe": "CWE-326", "severity": "MEDIUM",
     "port": 443, "protocol": "tcp", "service": "https"},
    {"rule_id": "nessus:22964", "title": "Service Detection on unexpected port",
     "cve": None, "cwe": None, "severity": "INFO",
     "port": None, "protocol": "tcp", "service": "unknown"},
    {"rule_id": "nessus:11213", "title": "HTTP TRACE / TRACK Methods Allowed",
     "cve": "CVE-2004-2320", "cwe": "CWE-16", "severity": "MEDIUM",
     "port": 80, "protocol": "tcp", "service": "http"},
]

NUCLEI_RULES = [
    {"rule_id": "CVE-2021-26855",
     "title": "Microsoft Exchange Server SSRF (ProxyLogon)",
     "cve": "CVE-2021-26855", "cwe": "CWE-918", "severity": "CRITICAL",
     "port": 443, "protocol": "tcp", "service": "https"},
    {"rule_id": "CVE-2021-44228",
     "title": "Apache Log4j RCE via JNDI lookup",
     "cve": "CVE-2021-44228", "cwe": "CWE-502", "severity": "CRITICAL",
     "port": 8080, "protocol": "tcp", "service": "http"},
    {"rule_id": "CVE-2014-0160",
     "title": "OpenSSL Heartbleed",
     "cve": "CVE-2014-0160", "cwe": "CWE-125", "severity": "HIGH",
     "port": 443, "protocol": "tcp", "service": "https"},
    {"rule_id": "nuclei:exposed-panels",
     "title": "Exposed Admin Panel Detected",
     "cve": None, "cwe": "CWE-284", "severity": "MEDIUM",
     "port": 80, "protocol": "tcp", "service": "http"},
    {"rule_id": "nuclei:default-logins",
     "title": "Default Credentials Found",
     "cve": None, "cwe": "CWE-521", "severity": "HIGH",
     "port": 8080, "protocol": "tcp", "service": "http"},
    {"rule_id": "CVE-2023-23397",
     "title": "Microsoft Outlook Privilege Escalation",
     "cve": "CVE-2023-23397", "cwe": "CWE-294", "severity": "CRITICAL",
     "port": 443, "protocol": "tcp", "service": "https"},
]

# DomainScope: domain-based perimeter scanner — discovers hosts via DNS,
# then runs port/service enumeration. Produces network findings with trails.
DOMAINSCOPE_RULES = [
    {"rule_id": "domainscope:open-port",
     "title": "Open port discovered by DomainScope",
     "cve": None, "cwe": None, "severity": "INFO",
     "port": None, "protocol": "tcp", "service": "unknown"},
    {"rule_id": "domainscope:https-expired-cert",
     "title": "Expired TLS certificate detected",
     "cve": None, "cwe": "CWE-295", "severity": "HIGH",
     "port": 443, "protocol": "tcp", "service": "https"},
    {"rule_id": "domainscope:http-no-redirect",
     "title": "HTTP endpoint without HTTPS redirect",
     "cve": None, "cwe": "CWE-319", "severity": "MEDIUM",
     "port": 80, "protocol": "tcp", "service": "http"},
    {"rule_id": "domainscope:ssh-exposed",
     "title": "SSH service exposed on public host",
     "cve": None, "cwe": "CWE-284", "severity": "MEDIUM",
     "port": 22, "protocol": "tcp", "service": "ssh"},
    {"rule_id": "domainscope:subdomain-takeover-risk",
     "title": "Potential subdomain takeover risk",
     "cve": None, "cwe": "CWE-350", "severity": "HIGH",
     "port": 443, "protocol": "tcp", "service": "https"},
    {"rule_id": "domainscope:db-port-exposed",
     "title": "Database port exposed to Internet",
     "cve": None, "cwe": "CWE-284", "severity": "CRITICAL",
     "port": 5432, "protocol": "tcp", "service": "postgresql"},
    {"rule_id": "domainscope:admin-panel-exposed",
     "title": "Admin panel accessible from Internet",
     "cve": None, "cwe": "CWE-284", "severity": "HIGH",
     "port": 8080, "protocol": "tcp", "service": "http"},
    {"rule_id": "CVE-2014-3566",
     "title": "POODLE: SSL 3.0 protocol vulnerability",
     "cve": "CVE-2014-3566", "cwe": "CWE-326", "severity": "HIGH",
     "port": 443, "protocol": "tcp", "service": "https"},
]

KINGFISHER_RULES = [
    {"rule_id": "aws-access-key",
     "title": "AWS Access Key ID detected",
     "severity": "CRITICAL",
     "snippet_mask": """# .env — DO NOT COMMIT
APP_ENV=production
DATABASE_URL=postgres://app:s3cr3t@db:5432/prod
# BUG: real AWS credentials committed to repository
AWS_ACCESS_KEY_ID=AKIA{masked}XXXXXX
AWS_SECRET_ACCESS_KEY=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
AWS_DEFAULT_REGION=eu-west-1
"""},
    {"rule_id": "github-pat",
     "title": "GitHub Personal Access Token",
     "severity": "HIGH",
     "snippet_mask": """#!/usr/bin/env bash
# scripts/ci-deploy.sh
set -euo pipefail
REPO="acme-corp/backend"
# BUG: hardcoded PAT with repo:write scope committed to version control
GH_TOKEN=ghp_{masked}
curl -H "Authorization: token $GH_TOKEN" \
     https://api.github.com/repos/$REPO/releases
"""},
    {"rule_id": "private-key-rsa",
     "title": "RSA Private Key detected",
     "severity": "CRITICAL",
     "snippet_mask": """# config/tls/server.key — accidentally committed to repository
-----BEGIN RSA PRIVATE KEY-----
{masked}
-----END RSA PRIVATE KEY-----
"""},
    {"rule_id": "jwt-long-lived",
     "title": "Long-lived JWT token detected",
     "severity": "MEDIUM",
     "snippet_mask": """// integration-tests/fixtures/auth.json
{
  "description": "test admin user — valid for 10 years, DO NOT use in prod",
  // BUG: hardcoded JWT will allow persistent access if leaked
  "token": "eyJhbGciOiJIUzI1NiJ9.{masked}",
  "user_id": "00000000-0000-0000-0000-000000000001"
}
"""},
    {"rule_id": "google-api-key",
     "title": "Google API Key detected",
     "severity": "HIGH",
     "snippet_mask": """// src/config/maps.ts
export const mapsConfig = {
  // BUG: API key has no HTTP referrer restrictions — usable by anyone
  apiKey: "AIza{masked}",
  region: "RU",
  language: "ru",
};
"""},
    {"rule_id": "stripe-live-key",
     "title": "Stripe Live Secret Key detected",
     "severity": "CRITICAL",
     "snippet_mask": """# app/services/payment.py
import stripe

# BUG: live Stripe key committed — real financial transactions at risk
stripe.api_key = "sk_live_{masked}"
stripe.api_version = "2023-10-16"

def create_charge(amount_cents: int, token: str) -> stripe.Charge:
    return stripe.Charge.create(amount=amount_cents, currency="usd", source=token)
"""},
    {"rule_id": "postgres-conn-string",
     "title": "PostgreSQL connection string with credentials",
     "severity": "HIGH",
     "snippet_mask": """# helm/values-production.yaml
backend:
  env:
    APP_ENV: production
    # BUG: DB password in values file — use sealed-secrets or Vault instead
    DATABASE_URL: "postgres://admin:{masked}@db.prod.company.com:5432/prod"
    REDIS_URL: "redis://:changeme@redis:6379/0"
"""},
]

SECRET_FILE_PATTERNS = [
    ".env", ".env.production", "config/secrets.yaml",
    "config/database.yml", "src/config.py", "internal/config/config.go",
    "helm/values-prod.yaml", "k8s/secrets.yaml", "deploy/.env",
    ".github/workflows/deploy.yml",
]

KNOWN_VULNS_POOL = [
    {"rule_id": "CVE-2021-44228",              "file_path": "pom.xml",                  "line": 42},
    {"rule_id": "python.django.security.audit.xss.xss-html-string-concat",
                                               "file_path": "app/views.py",              "line": 88},
    {"rule_id": "go.lang.security.audit.sql.sql-injection",
                                               "file_path": "internal/repository.go",   "line": 134},
    {"rule_id": "CKV_AWS_18",                 "file_path": "terraform/s3.tf",           "line": 12},
    {"rule_id": "aws-access-key",             "file_path": ".env",                       "line": 3},
]

FINDING_STATUSES = ["new", "confirmed", "false_positive", "fixed", "risk_accepted", "wont_fix", "renewed"]
STATUS_WEIGHTS   = [0.35,  0.25,         0.10,             0.15,    0.08,            0.04,       0.03]
SEVERITIES       = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
SEVERITY_WEIGHTS = [0.10,       0.25,   0.35,     0.20,  0.10]
SLA_DAYS         = {"CRITICAL": 7, "HIGH": 14, "MEDIUM": 30, "LOW": 90, "INFO": 180}

SA_ARCHETYPES = [
    {"name_prefix": "gitlab-ci-scanner",
     "description": "GitLab CI pipeline — uploads SARIF reports",
     "scope": "upload_report", "num_keys": 2},
    {"name_prefix": "jira-integration",
     "description": "Jira webhook — reads findings, updates statuses",
     "scope": "read_findings", "num_keys": 1},
    {"name_prefix": "sonar-uploader",
     "description": "SonarQube export bridge — uploads SARIF from CI",
     "scope": "upload_report", "num_keys": 1},
]


def connect(db_url: str):
    conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    return conn

def execute(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)

def fetchall(conn, sql, params=None) -> list:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

def _pg_val(v):
    """Auto-serialize Python dicts/lists to JSON strings for psycopg2."""
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return v


def bulk_insert(conn, table: str, rows: list, conflict: str = "DO NOTHING") -> int:
    if not rows:
        return 0
    cols = list(rows[0].keys())
    placeholders = ", ".join(["%s"] * len(cols))
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) ON CONFLICT {conflict}"
    inserted = 0
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(sql, [_pg_val(row[c]) for c in cols])
            inserted += cur.rowcount
    return inserted

def upsert_by(conn, table: str, row: dict, conflict_cols: list) -> dict:
    """
    Insert row if it doesn't exist (checked by conflict_cols).
    Uses SELECT-first to avoid issues with partial unique indexes (soft-delete tables).
    """
    where = " AND ".join([f"{c} = %s" for c in conflict_cols])
    existing = fetchall(conn, f"SELECT * FROM {table} WHERE {where}",
                        [_pg_val(row[c]) for c in conflict_cols])
    if existing:
        return existing[0]
    bulk_insert(conn, table, [row])
    existing = fetchall(conn, f"SELECT * FROM {table} WHERE {where}",
                        [_pg_val(row[c]) for c in conflict_cols])
    return existing[0] if existing else row

def sha256hex(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()

def calculate_location_hash(file_path: str, line_start: int,
                             line_end: int, snippet: str = "") -> str:
    return sha256hex(f"{file_path}:{line_start}:{line_end}:{snippet[:100]}")

def calculate_dedup_hash(product_id: str, rule_id: str, location_hash: str) -> str:
    return sha256hex(f"{product_id}:{rule_id}:{location_hash}")

def calculate_network_dedup_hash(product_id: str, cve: str, location_hash: str) -> str:
    if cve:
        return sha256hex(f"{product_id}:{cve}:{location_hash}")
    return sha256hex(f"{product_id}:{location_hash}")

def network_location_hash(ip: str, port: int, protocol: str) -> str:
    return sha256hex(f"{ip}:{port}:{protocol}")

def random_git_sha(length: int = 40) -> str:
    return "".join(random.choices("0123456789abcdef", k=length))

# Backend license grace period = 30 days from MIN(created_at) across all tables.
# All seed timestamps must stay within 25 days so the demo stays in grace period.
_DEMO_MAX_HISTORY_DAYS = 25

def now_utc():
    return datetime.now(timezone.utc)

def past(days: float):
    """Return a datetime in the past, capped at _DEMO_MAX_HISTORY_DAYS.
    Keeps demo data within the license grace period."""
    return now_utc() - timedelta(days=min(days, _DEMO_MAX_HISTORY_DAYS))

def past_range(min_days: float, max_days: float):
    """Uniform random past datetime, with the (min_days, max_days) range itself
    rescaled to fit inside _DEMO_MAX_HISTORY_DAYS instead of relying on past()'s
    per-call clamp. A plain past(random.uniform(1, 90)) with a 25-day cap makes
    every sample above 25 collapse onto the exact same clamped timestamp — most
    of a 1-90 day range piles onto one day. Rescaling first keeps relative
    ordering between callers (e.g. projects older than their findings) while
    spreading dates smoothly across the whole grace window."""
    capped_max = min(max_days, _DEMO_MAX_HISTORY_DAYS)
    capped_min = min(min_days, capped_max)
    return past(random.uniform(capped_min, capped_max))

def future(days: float):
    return now_utc() + timedelta(days=days)

def random_ip_in_cidr(cidr: str) -> str:
    base = cidr.rsplit(".", 1)[0]
    return f"{base}.{random.randint(2, 254)}"

def generate_api_key() -> tuple:
    """
    Generate API key in format sa_{8hexchars}_{base64url}.
    Matches backend's GenerateAPIKey() in internal/auth/api_key.go:
      prefix = APIKeyPrefix("sa") + "_" + hex(rand[:4]) + "_" + base64url(rand)
    The secret part must not contain underscores (backend regenerates if it does).
    key_prefix in DB = first 8 hex chars (not the 'sa_' prefix).
    """
    import base64
    while True:
        raw_bytes = secrets.token_bytes(32)
        key_prefix = raw_bytes[:4].hex()          # 8 lowercase hex chars
        secret_part = base64.urlsafe_b64encode(raw_bytes).decode()  # with = padding
        if "_" not in secret_part:
            break
    plaintext = f"sa_{key_prefix}_{secret_part}"
    key_hash  = sha256hex(plaintext)
    return plaintext, key_prefix, key_hash
