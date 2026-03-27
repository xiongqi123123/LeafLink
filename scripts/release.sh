#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/release.sh check
  scripts/release.sh testpypi
  scripts/release.sh pypi

Environment:
  TWINE_USERNAME=__token__
  TWINE_PASSWORD=<pypi-token>

Examples:
  scripts/release.sh check
  TWINE_USERNAME=__token__ TWINE_PASSWORD=pypi-*** scripts/release.sh testpypi
  TWINE_USERNAME=__token__ TWINE_PASSWORD=pypi-*** scripts/release.sh pypi
EOF
}

if [[ $# -ne 1 ]]; then
  usage
  exit 1
fi

command -v python >/dev/null 2>&1 || {
  echo "python is required" >&2
  exit 1
}

mode="$1"

python scripts/build_dist.py
python -m twine check dist/*

case "$mode" in
  check)
    echo "Build and metadata checks passed."
    ;;
  testpypi)
    python -m twine upload --repository testpypi dist/*
    ;;
  pypi)
    python -m twine upload dist/*
    ;;
  *)
    usage
    exit 1
    ;;
esac
