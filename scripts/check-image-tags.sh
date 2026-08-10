#!/usr/bin/env bash
# check-image-tags.sh — every image tag this repo pins must exist in the registry.
#
# Why this exists (SecurityScanHub#172): both documented install paths failed on
# `docker pull` because the delivery pins had drifted away from what was actually
# published. docker-compose.yml defaulted to 0.24, which dexionius/sshub-backend
# never had; the Helm values pinned 0.25, missing for backend, worker and
# iac-scanner. Nothing checked, so a first-time install hit ImagePullBackOff and
# the docs looked correct.
#
# A pin is a promise about a remote registry, and it can be broken by someone
# else's action (a tag never published, a tag deleted) without a single commit
# here. That is exactly the kind of claim that needs a mechanical check rather
# than review attention.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FAILED=0
CHECKED=0

# tag_exists <repo> <tag> — repo is the Docker Hub path, e.g. dexionius/sshub-backend
tag_exists() {
  local repo="$1" tag="$2" code
  # Retried: a network blip must not read as "the tag is gone". Distinguishing
  # 404 from an unreachable registry is the whole point of checking the code.
  for attempt in 1 2 3; do
    code=$(curl -sS -o /dev/null -w '%{http_code}' -m 30 \
      "https://hub.docker.com/v2/repositories/${repo}/tags/${tag}/" 2>/dev/null || echo "000")
    case "$code" in
      200) return 0 ;;
      404) return 1 ;;
      *) sleep $((attempt * 3)) ;;
    esac
  done
  echo "  ERROR: could not reach the registry for ${repo}:${tag} (last HTTP code: ${code}) — treating as a failure rather than passing on a guess" >&2
  return 2
}

check_pin() {
  local where="$1" repo="$2" tag="$3"
  CHECKED=$((CHECKED + 1))
  if tag_exists "$repo" "$tag"; then
    echo "  OK   ${repo}:${tag}  (${where})"
  else
    echo "  MISSING ${repo}:${tag}  (${where})" >&2
    FAILED=$((FAILED + 1))
  fi
}

echo "Checking image pins against Docker Hub"

# 1) docker-compose.yml — "image: dexionius/x:${VAR:-TAG}" or a literal tag.
#    The DEFAULT inside ${VAR:-TAG} is what an operator who sets nothing gets,
#    which is precisely the path that was broken.
while IFS= read -r line; do
  repo=$(sed -nE 's|.*image: *(dexionius/[a-z0-9._-]+):.*|\1|p' <<<"$line")
  [ -n "$repo" ] || continue
  tag=$(sed -nE 's|.*image: *dexionius/[a-z0-9._-]+:\$\{[A-Z_]+:-([^}]+)\}.*|\1|p' <<<"$line")
  [ -n "$tag" ] || tag=$(sed -nE 's|.*image: *dexionius/[a-z0-9._-]+:([a-z0-9._-]+).*|\1|p' <<<"$line")
  [ -n "$tag" ] || continue
  check_pin "docker-compose.yml" "$repo" "$tag"
done < <(grep -nE 'image: *dexionius/' docker-compose.yml 2>/dev/null || true)

# 2) .env.example — the values an operator copies verbatim.
for var in HUB_VERSION DS_VERSION; do
  tag=$(sed -nE "s/^${var}=([0-9][^ #]*).*/\\1/p" .env.example 2>/dev/null | head -1)
  [ -n "$tag" ] || continue
  case "$var" in
    HUB_VERSION) for repo in sshub-backend sshub-worker sshub-frontend; do check_pin ".env.example (${var})" "dexionius/${repo}" "$tag"; done ;;
    DS_VERSION)  check_pin ".env.example (${var})" "dexionius/domain-scope" "$tag" ;;
  esac
done

# 3) Helm values — "repository: dexionius/x" followed by "tag: \"N\"".
#    Read through process substitution, NOT a pipe: a pipeline runs the loop in a
#    subshell, where every FAILED increment is discarded when it exits — the
#    check would then always report success no matter what it found.
while IFS=$'\t' read -r repo tag file; do
  [ -n "$repo" ] && [ -n "$tag" ] || continue
  check_pin "$file" "$repo" "$tag"
done < <(
  for values in charts/*/values.yaml; do
    [ -f "$values" ] || continue
    awk -v file="$values" '
      /repository: *dexionius\// { repo=$2; next }
      /^[[:space:]]*tag:/ && repo != "" {
        gsub(/"/, "", $2); print repo "\t" $2 "\t" file; repo=""
      }
    ' "$values"
  done
)

echo
if [ "$FAILED" -gt 0 ]; then
  echo "FAIL: ${FAILED} of ${CHECKED} pinned image tag(s) do not exist in the registry." >&2
  echo "      A pin that cannot be pulled turns every fresh install into ImagePullBackOff." >&2
  echo "      Either publish the missing tag or move the pin to one that exists." >&2
  exit 1
fi

echo "OK: all ${CHECKED} pinned image tag(s) exist in the registry"
