#!/usr/bin/env bash
# Run kidney-health on ROOTLESS Docker without compose: the same hardening as deploy/compose.yaml,
# spelled out as `docker run` flags. Spec: docs/dev/research/01-rootless-and-security.md §3.2, §5.2.
# Guide (setup tool, linger, source-IP caveat): docs/deployment.md, "Rootless Docker".
#
#   deploy/docker-rootless-run.sh            # first run creates the secret files, then starts
#   IMAGE=ghcr.io/ksullivan86/kidney-health:0.3.0@sha256:... deploy/docker-rootless-run.sh
#
# Settings (environment variables of this script):
#   IMAGE        image reference            [ghcr.io/ksullivan86/kidney-health:0.3]
#   SECRETS_DIR  where the secret files live [~/.config/kidney-health/secrets]
#   HOST_PORT    port on 127.0.0.1           [8000]
#   PUBLIC_URL   the URL people type, e.g. https://food.home.example.net   [unset]
set -euo pipefail

IMAGE="${IMAGE:-ghcr.io/ksullivan86/kidney-health:0.3}"
SECRETS_DIR="${SECRETS_DIR:-$HOME/.config/kidney-health/secrets}"
HOST_PORT="${HOST_PORT:-8000}"
PUBLIC_URL="${PUBLIC_URL:-}"

# Refuse a rootful daemon: there, a container escape is root on the host.
if ! docker info --format '{{json .SecurityOptions}}' | grep -q 'name=rootless'; then
  echo "This Docker daemon is not rootless (docker info shows no name=rootless)." >&2
  echo "Set it up first: dockerd-rootless-setuptool.sh install; docker context use rootless" >&2
  exit 1
fi

# Secret files. Docker bind-mounts them; your UID is container root under rootless Docker, so a
# 0600 file would be unreadable for the app's UID 10001. 0644 files inside a 0700 directory keep
# other host users out while the container can read them.
install -d -m 0700 "$SECRETS_DIR"
if [ ! -s "$SECRETS_DIR/secret_key" ]; then
  python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > "$SECRETS_DIR/secret_key"
  echo "Created $SECRETS_DIR/secret_key: keep a copy in your password manager." >&2
fi
[ -e "$SECRETS_DIR/usda_api_key" ] || : > "$SECRETS_DIR/usda_api_key"   # empty = USDA search off
chmod 0644 "$SECRETS_DIR/secret_key" "$SECRETS_DIR/usda_api_key"

docker volume create kidney-health-data >/dev/null

# --publish 127.0.0.1 only: rootless Docker does not propagate client source addresses by default,
#   so every client would look like the RootlessKit gateway; keep TRUSTED_PROXIES at loopback.
# --read-only needs an explicit /tmp tmpfs on Docker. Memory and pids limits need cgroup v2 + systemd
#   (otherwise Docker ignores them silently: check `docker info | grep -i cgroup`).
# No --health-cmd: Docker would run it through /bin/sh, which the image does not have. The image's
#   own HEALTHCHECK (exec form, python -m app.healthcheck) applies.
docker run --detach --name kidney-health --restart always \
  --user 10001:10001 \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --pids-limit 128 \
  --memory 512m \
  --publish "127.0.0.1:${HOST_PORT}:8000" \
  --mount type=volume,src=kidney-health-data,dst=/data \
  --mount "type=bind,src=${SECRETS_DIR}/secret_key,dst=/run/secrets/secret_key,readonly" \
  --mount "type=bind,src=${SECRETS_DIR}/usda_api_key,dst=/run/secrets/usda_api_key,readonly" \
  --env SECRET_KEY_FILE=/run/secrets/secret_key \
  --env USDA_API_KEY_FILE=/run/secrets/usda_api_key \
  --env TRUSTED_PROXIES=127.0.0.1,::1 \
  --env "PUBLIC_URL=${PUBLIC_URL}" \
  "$IMAGE"

echo "Started. First run: docker logs kidney-health 2>&1 | grep 'FIRST-RUN SETUP'" >&2
