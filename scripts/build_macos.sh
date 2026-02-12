#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

python scripts/release_gate.py --skip-slow
python scripts/package_app.py --target macos --clean
python scripts/init_app_env.py --profile local-dev

echo "macOS artifact ready under dist/"
