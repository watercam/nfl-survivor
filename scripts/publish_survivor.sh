#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python -m src.survivor.run --web
npx --yes netlify-cli deploy --dir=web --prod
