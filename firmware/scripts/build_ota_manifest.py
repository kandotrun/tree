"""Build a deterministic public manifest for a generic ATOM Lite OTA image."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import NoReturn

MAX_OTA_PARTITION_BYTES = 0x140000
SEMVER = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
SHA1 = re.compile(r"[0-9a-f]{40}\Z")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def fail(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    raise SystemExit(2)


def main() -> None:
    args = parse_args()
    if SEMVER.fullmatch(args.version) is None:
        fail("firmware version must use canonical x.y.z syntax")
    if SHA1.fullmatch(args.source_sha) is None:
        fail("source SHA must be 40 lowercase hexadecimal characters")
    try:
        binary = args.binary.read_bytes()
    except OSError as error:
        fail(f"cannot read firmware binary: {error}")
    if not binary:
        fail("firmware binary must not be empty")
    if len(binary) > MAX_OTA_PARTITION_BYTES:
        fail("firmware binary is larger than the ATOM Lite OTA partition")

    asset_name = f"TreeWatering-m5stack-atom-{args.version}.bin"
    manifest = {
        "schema_version": 1,
        "device_type": "tree-watering",
        "target": "m5stack-atom",
        "firmware_version": args.version,
        "firmware_asset": asset_name,
        "sha256": hashlib.sha256(binary).hexdigest(),
        "size": len(binary),
        "source_sha": args.source_sha,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)


if __name__ == "__main__":
    main()
