#!/usr/bin/env bash
# Regenerate the backend dependency lock files from their inputs.
#
#   backend/requirements/base.in -> base.txt   (installed by backend/Dockerfile)
#   backend/requirements/test.in -> test.txt
#   backend/requirements/dev.in  -> dev.txt    (installed by CI and for local tests)
#
# Edit only the .in files, run this script, and commit .in and .txt together.
# Every package, direct and indirect, is locked to an exact version with sha256
# hashes, so a build on any day installs the same thing.
#
# pip-compile runs inside python:3.12-slim, the same base image as
# backend/Dockerfile, so versions and platform markers match production.
# It keeps the versions already in a .txt lock unless asked to change them, so
# re-running with unchanged inputs changes nothing (CI relies on this).
#
# Usage:
#   scripts/lock_backend_deps.sh                          # regenerate after editing a .in
#   scripts/lock_backend_deps.sh --upgrade-package kombu  # deliberately upgrade one package
#
# Any extra arguments are passed to every pip-compile call. Needs Docker.
set -euo pipefail

cd "$(dirname "$0")/.."
REQ="$PWD/backend/requirements"
# Git Bash on Windows: Docker needs a Windows path for the bind mount.
if command -v cygpath >/dev/null 2>&1; then REQ="$(cygpath -w "$REQ")"; fi

IMAGE="python:3.12-slim"   # keep in step with the FROM line in backend/Dockerfile
PIP_TOOLS="pip-tools==7.4.1"

MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$REQ:/req" -w /req \
  -e PIP_DISABLE_PIP_VERSION_CHECK=1 \
  -e PIP_ROOT_USER_ACTION=ignore \
  -e CUSTOM_COMPILE_COMMAND="scripts/lock_backend_deps.sh" \
  "$IMAGE" sh -c '
    set -e
    pip install -q "'"$PIP_TOOLS"'"
    for name in base test dev; do
      pip-compile --quiet --generate-hashes --strip-extras --allow-unsafe \
        --output-file "$name.txt" "$name.in" "$@"
    done
  ' sh "$@"

echo "Locks regenerated in backend/requirements/. Commit the .in and .txt files together."
