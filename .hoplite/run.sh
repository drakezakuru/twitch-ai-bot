#!/usr/bin/env bash
set -euo pipefail
# Sandbox PYTHONPATH may include unreadable dirs (e.g. /root) that break imports.
unset PYTHONPATH

case "${HOPLITE_PREVIEW_PROFILE:-default}" in
  default)
    exec .venv/bin/python run.py
    ;;
  full-qa)
    exec .venv/bin/python scripts/run_qa_panel.py --profile "${QA_PROFILE_NAME:-local}" --host 0.0.0.0
    ;;
  *)
    echo "Unknown HOPLITE_PREVIEW_PROFILE: ${HOPLITE_PREVIEW_PROFILE}" >&2
    exit 2
    ;;
esac
