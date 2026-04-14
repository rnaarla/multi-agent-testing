#!/usr/bin/env bash
# Lint security- and contract-sensitive modules (incremental Ruff gate).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec ruff check src/app/simulation/ src/app/services/simulation_service.py src/app/routers/simulation.py
