#!/usr/bin/env bash
# Regenerate the company_site dependency lock from its input.
#
#   company_site/requirements.docker.in -> requirements.docker.txt   (installed by company_site/Dockerfile)
#
# Edit only the .in file, run this script, and commit .in and .txt together.
# Every package, direct and indirect, is locked to an exact version with sha256
# hashes, so a build on any day installs the same thing. Same approach as
# scripts/lock_backend_deps.sh.
#
# pip-compile runs inside python:3.12-slim, the same base image as
# company_site/Dockerfile. It keeps the versions already in the lock unless
# asked to change them, so re-running with an unchanged input changes nothing
# (CI relies on this).
#
# Usage:
#   scripts/lock_company_site_deps.sh                          # regenerate after editing the .in
#   scripts/lock_company_site_deps.sh --upgrade-package django # deliberately upgrade one package
#
# Any extra arguments are passed to pip-compile. Needs Docker.
set -euo pipefail

cd "$(dirname "$0")/.."
REQ="$PWD/company_site"
# Git Bash on Windows: Docker needs a Windows path for the bind mount.
if command -v cygpath >/dev/null 2>&1; then REQ="$(cygpath -w "$REQ")"; fi

IMAGE="python:3.12-slim"   # keep in step with the FROM line in company_site/Dockerfile
PIP_TOOLS="pip-tools==7.4.1"

MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$REQ:/req" -w /req \
  -e PIP_DISABLE_PIP_VERSION_CHECK=1 \
  -e PIP_ROOT_USER_ACTION=ignore \
  -e CUSTOM_COMPILE_COMMAND="scripts/lock_company_site_deps.sh" \
  "$IMAGE" sh -c '
    set -e
    pip install -q "'"$PIP_TOOLS"'"
    pip-compile --quiet --generate-hashes --strip-extras --allow-unsafe \
      --output-file requirements.docker.txt requirements.docker.in "$@"
  ' sh "$@"

echo "Lock regenerated: company_site/requirements.docker.txt. Commit it with requirements.docker.in."
