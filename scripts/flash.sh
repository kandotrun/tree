#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
firmware_dir="${repo_root}/firmware"

if ! command -v pio >/dev/null 2>&1; then
  printf 'PlatformIO (pio) is required. See README.md.\n' >&2
  exit 2
fi
if [[ ! -f "${firmware_dir}/include/config.h" ]]; then
  printf 'Missing firmware/include/config.h; copy config.example.h and edit it locally.\n' >&2
  exit 2
fi

cd "${firmware_dir}"
exec pio run -e m5stack-atom --target upload "$@"
