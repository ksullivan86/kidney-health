#!/usr/bin/env bash
# Container smoke test for a locally built image (note 01 §5.4, §7 Phase E; risk R3).
#
#   .github/scripts/smoke-test.sh IMAGE [--allow-shell]
#
# Runs the image the way the shipped profiles do (read-only root, tmpfs /tmp, every capability
# dropped, no-new-privileges, pids and memory limits, SECRET_KEY_FILE as a read-only file) twice:
# as 10001:10001 (the image user) and as 12345:0 (an arbitrary UID with GID 0, OpenShift style).
# Each run must answer /healthz, log a meal (POST /api/log -> 201) and turn "healthy" through the
# image's own HEALTHCHECK, which runs without a shell. Then it checks the image itself: no shell
# (unless --allow-shell, for the Debian fallback), no pip, and nothing under /app or /opt/venv
# writable by the app user.
set -euo pipefail

image="${1:?usage: smoke-test.sh IMAGE [--allow-shell]}"
allow_shell="${2:-}"
here="$(cd "$(dirname "$0")" && pwd)"
work="$(mktemp -d)"
containers=()

cleanup() {
  for c in "${containers[@]}"; do docker rm -f "$c" >/dev/null 2>&1 || true; done
  rm -rf "$work"
}
trap cleanup EXIT

python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > "$work/secret_key"
chmod 0444 "$work/secret_key"   # throw-away key; readable by any UID the test uses

run_as() { # $1 = --user value, $2 = host port
  local user="$1" port="$2" name="kh-smoke-$2"
  containers+=("$name")
  echo "::group::run as $user on 127.0.0.1:$port"
  docker run --detach --name "$name" \
    --user "$user" \
    --read-only --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
    --cap-drop ALL --security-opt no-new-privileges:true \
    --pids-limit 128 --memory 512m \
    --publish "127.0.0.1:${port}:8000" \
    --mount "type=bind,src=$work/secret_key,dst=/run/secrets/secret_key,readonly" \
    --env SECRET_KEY_FILE=/run/secrets/secret_key \
    --env AUTH_MODE=none \
    "$image" >/dev/null
  if ! python3 "$here/smoke_http.py" "http://127.0.0.1:${port}"; then
    docker logs "$name" || true
    echo "::endgroup::"
    return 1
  fi
  # The image HEALTHCHECK (exec form, no shell) must report healthy: start period 15 s,
  # interval 30 s, so allow up to 120 s.
  local health=""
  for _ in $(seq 1 120); do
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$name")"
    [ "$health" = healthy ] && break
    [ "$health" = none ] && break
    sleep 1
  done
  echo "health: $health"
  if [ "$health" != healthy ]; then
    docker inspect --format '{{json .State.Health}}' "$name" || true
    docker logs "$name" || true
    echo "::endgroup::"
    return 1
  fi
  echo "::endgroup::"
}

run_as 10001:10001 18001
run_as 12345:0 18002

echo "::group::image contents"
if [ "$allow_shell" != "--allow-shell" ]; then
  for sh in sh /bin/sh /bin/bash /bin/busybox; do
    if docker run --rm --entrypoint "$sh" "$image" -c true >/dev/null 2>&1; then
      echo "FAIL: $sh exists in the runtime image" >&2
      exit 1
    fi
  done
  echo "ok   no shell"
fi
if docker run --rm --entrypoint python "$image" -m pip --version >/dev/null 2>&1; then
  echo "FAIL: pip is importable in the runtime image" >&2
  exit 1
fi
echo "ok   no pip"
docker run --rm --user 10001:10001 --entrypoint python "$image" -c '
import os, sys
bad = [os.path.join(d, n) for top in ("/app", "/opt/venv") for d, dirs, files in os.walk(top)
       for n in [""] + dirs + files if os.access(os.path.join(d, n), os.W_OK)]
print("\n".join(bad[:20]))
sys.exit(1 if bad else 0)
' || { echo "FAIL: paths above are writable by UID 10001" >&2; exit 1; }
echo "ok   /app and /opt/venv are read-only for UID 10001"
docker run --rm --user 10001:10001 --entrypoint python "$image" -c '
import os, stat, sys
root, data = os.stat("/"), os.stat("/data")
bad = []
if root.st_uid != 0 or os.access("/", os.W_OK):
    bad.append("/ must stay owned by root and not writable by the app user")
got = (data.st_uid, data.st_gid, oct(stat.S_IMODE(data.st_mode)))
if got != (10001, 0, "0o770"):
    bad.append(f"/data is {got}, want (10001, 0, 0o770): group 0 must be able to write it")
print("\n".join(bad))
sys.exit(1 if bad else 0)
' || { echo "FAIL: filesystem ownership above" >&2; exit 1; }
echo "ok   / is root-owned; /data is 10001:0 0770"
echo "::endgroup::"
echo "smoke test passed: $image"
