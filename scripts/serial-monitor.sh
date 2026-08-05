#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v pio >/dev/null 2>&1; then
  printf 'PlatformIO (pio) is required. See README.md.\n' >&2
  exit 2
fi

cd "${repo_root}/firmware"
exec pio device monitor "$@"
