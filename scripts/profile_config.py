#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from EZ_App.profiles import get_profile_template_path, list_profiles, write_profile_template


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a profile template config for EZchain")
    parser.add_argument("--profile", required=True, choices=list_profiles())
    parser.add_argument("--out", default="ezchain.yaml")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    target = Path(args.out)
    existed_before = target.exists()
    result = {
        "status": "ok",
        "profile": args.profile,
        "template": str(get_profile_template_path(args.profile)),
        "output": str(write_profile_template(target, args.profile, force=args.force)),
        "overwritten": existed_before and args.force,
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
