#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )"/../.. && pwd )"

docker build \
  -f "${ROOT_DIR}/.devcontainer/Dockerfile" \
  -t multi-agent-testing-dev \
  "${ROOT_DIR}"

echo "Dev container image built: multi-agent-testing-dev"

