#!/usr/bin/env bash
# Regenerate the hash-pinned lock files (note 01 §5.1):
#   requirements.in           -> requirements.lock            (runtime, what the image installs)
#   requirements-dev.in       -> requirements-dev.lock        (runtime + test tools, what CI installs)
#   handbook/requirements.in  -> handbook/requirements.lock   (handbook build, image's handbook stage)
#
# Usage: scripts/lock.sh [extra pip-compile options, e.g. --upgrade or --upgrade-package cryptography]
#
# Cooldown (C-DEPBOT): set PIP_UPLOADED_PRIOR_TO=P7D to take only releases uploaded at least 7 days
# ago (pip >= 26.0, which this script installs). The weekly .github/workflows/refresh-locks.yml runs
# `PIP_UPLOADED_PRIOR_TO=P7D scripts/lock.sh --upgrade` and opens a pull request; Dependabot cannot,
# because it reads only requirement files ending in .txt or .in and never regenerates *.lock.
#
# pip-tools runs under Python 3.14, the image's Python: inside python:3.14-slim-trixie when podman
# or docker can run containers, otherwise with a local python3.14 (or one `uv` can provide).
# Install the result with:  pip install --require-hashes --no-deps -r requirements.lock
set -euo pipefail

PIP_TOOLS_VERSION="7.6.1"
PIP_VERSION="26.2.1"   # >= 26.0 for --uploaded-prior-to (PIP_UPLOADED_PRIOR_TO)
IMAGE="docker.io/library/python:3.14-slim-trixie@sha256:c3e521df8b2b498a7a682e7e18676771cb80c6b75b8699af886b2d554ce40151"
COMPILE_OPTS=(--quiet --generate-hashes --strip-extras --resolver=backtracking)

cd "$(dirname "$0")/.."

compile_with() { # $1 = pip-compile executable
  "$1" "${COMPILE_OPTS[@]}" ${EXTRA[@]+"${EXTRA[@]}"} --output-file requirements.lock requirements.in
  "$1" "${COMPILE_OPTS[@]}" ${EXTRA[@]+"${EXTRA[@]}"} --output-file requirements-dev.lock requirements-dev.in
  "$1" "${COMPILE_OPTS[@]}" --allow-unsafe ${EXTRA[@]+"${EXTRA[@]}"} --output-file handbook/requirements.lock handbook/requirements.in
}

EXTRA=("$@")
[[ -n "${PIP_UPLOADED_PRIOR_TO:-}" ]] || unset PIP_UPLOADED_PRIOR_TO

engine=""
for candidate in podman docker; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" info >/dev/null 2>&1; then
    engine="$candidate"
    break
  fi
done

if [[ -n "$engine" && "${LOCK_LOCAL:-0}" != "1" ]]; then
  echo "lock.sh: running pip-compile ${PIP_TOOLS_VERSION} in ${IMAGE%@*} via ${engine}" >&2
  "$engine" run --rm \
    -e PIP_DISABLE_PIP_VERSION_CHECK=1 -e PIP_ROOT_USER_ACTION=ignore \
    -e PIP_UPLOADED_PRIOR_TO="${PIP_UPLOADED_PRIOR_TO:-}" \
    -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
    -v "$PWD:/src:Z" -w /src "$IMAGE" \
    sh -euc '
      [ -n "$PIP_UPLOADED_PRIOR_TO" ] || unset PIP_UPLOADED_PRIOR_TO
      env -u PIP_UPLOADED_PRIOR_TO python -m pip install --quiet "pip==$1" "pip-tools==$0"
      shift
      pip-compile '"${COMPILE_OPTS[*]}"' "$@" --output-file requirements.lock requirements.in
      pip-compile '"${COMPILE_OPTS[*]}"' "$@" --output-file requirements-dev.lock requirements-dev.in
      pip-compile '"${COMPILE_OPTS[*]}"' --allow-unsafe "$@" --output-file handbook/requirements.lock handbook/requirements.in
      chown "$HOST_UID:$HOST_GID" requirements.lock requirements-dev.lock handbook/requirements.lock 2>/dev/null || true
    ' "$PIP_TOOLS_VERSION" "$PIP_VERSION" ${EXTRA[@]+"${EXTRA[@]}"}
  exit 0
fi

python314="$(command -v python3.14 || true)"
if [[ -z "$python314" ]] && command -v uv >/dev/null 2>&1; then
  python314="$(uv python find 3.14 2>/dev/null || true)"
fi
if [[ -z "$python314" ]]; then
  echo "lock.sh: needs podman or docker, or a local python3.14 (uv python install 3.14)" >&2
  exit 1
fi

venv="$(mktemp -d)/lock-venv"
trap 'rm -rf "$(dirname "$venv")"' EXIT
echo "lock.sh: running pip-compile ${PIP_TOOLS_VERSION} with ${python314}" >&2
if command -v uv >/dev/null 2>&1; then
  uv venv --quiet --seed --python "$python314" "$venv"
else
  "$python314" -m venv "$venv"
fi
env -u PIP_UPLOADED_PRIOR_TO "$venv/bin/python" -m pip install --quiet --disable-pip-version-check "pip==${PIP_VERSION}" "pip-tools==${PIP_TOOLS_VERSION}"
compile_with "$venv/bin/pip-compile"
