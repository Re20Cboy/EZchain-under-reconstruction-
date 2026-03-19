from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from EZ_Test.v2_acceptance import run_stage4_acceptance


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the EZchain V2 stage-4 acceptance scenario")
    parser.add_argument("--root-dir", default="", help="Directory for acceptance data")
    args = parser.parse_args()

    if args.root_dir:
        root_dir = args.root_dir
        Path(root_dir).mkdir(parents=True, exist_ok=True)
        summary = run_stage4_acceptance(root_dir=root_dir, project_root=str(Path(__file__).resolve().parent))
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    with tempfile.TemporaryDirectory(prefix="ez_v2_acceptance_") as tmpdir:
        summary = run_stage4_acceptance(root_dir=tmpdir, project_root=str(Path(__file__).resolve().parent))
        print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
