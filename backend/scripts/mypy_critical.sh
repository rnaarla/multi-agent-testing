#!/usr/bin/env bash
# Type-check security- and contract-sensitive modules only (incremental mypy gate).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec mypy --follow-imports=skip --ignore-missing-imports \
  src/app/simulation/evaluation.py \
  src/app/simulation/validation.py \
  src/app/routers/simulation.py \
  src/app/services/simulation_service.py
