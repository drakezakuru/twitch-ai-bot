#!/usr/bin/env python3
"""Create, reset, inspect, or verify the isolated local QA profile."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated fake-data profile for panel QA")
    parser.add_argument("command", choices=("reset", "seed", "manifest", "verify"))
    parser.add_argument("--profile", default="local", help="safe profile name")
    args = parser.parse_args()

    from app.qa_profile import profile_manifest, reset_profile, seed_profile, verify_profile

    if args.command == "reset":
        result = asyncio.run(reset_profile(args.profile))
    elif args.command == "seed":
        result = asyncio.run(seed_profile(args.profile))
    elif args.command == "verify":
        result = verify_profile(args.profile)
    else:
        result = profile_manifest(args.profile)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
