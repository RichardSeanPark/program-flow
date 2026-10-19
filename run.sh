#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
uv run --with-requirements requirements.txt uvicorn program_flow.app:app --host 127.0.0.1 --port 8765
