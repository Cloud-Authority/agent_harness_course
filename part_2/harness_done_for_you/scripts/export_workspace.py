#!/usr/bin/env python3
"""Write the practice workspace as files that a coding harness can read.

    python scripts/export_workspace.py
    python scripts/export_workspace.py --out /some/folder --check

A coding harness (pi, Hermes, Claude Code) has file tools and no mail or
calendar tool. This script writes the shared practice world to a folder: one
file per thread with the external text delimited, the governed answers under
``governed/``, a README with the rules, and a manifest with a hash per file.

The export needs no network and no key. It is deterministic: the same world
gives the same bytes, and ``--check`` exports twice and compares the hashes.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

TRACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRACK))

from ppa_dfy import paths, workspace_export, world as world_module  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the practice workspace as files.")
    parser.add_argument("--out", default=str(paths.workspace_dir() / "export"),
                        help="target folder (it is replaced)")
    parser.add_argument("--writable", action="store_true",
                        help="leave the files writable instead of locking them")
    parser.add_argument("--check", action="store_true",
                        help="export a second time and compare the hashes")
    arguments = parser.parse_args()

    world = world_module.load_world()
    manifest = workspace_export.export_workspace(world, arguments.out,
                                                 read_only=not arguments.writable)
    print({"path": paths.display_path(manifest["path"]), "files": len(manifest["files"]),
           "clock": manifest["scenario_now"], "counts": manifest["counts"],
           "tree_sha256": manifest["tree_sha256"][:16]})
    if arguments.check:
        with tempfile.TemporaryDirectory() as folder:
            again = workspace_export.export_workspace(world, Path(folder) / "export",
                                                      read_only=False)
        same = again["tree_sha256"] == manifest["tree_sha256"]
        print({"second export has the same hash": same})
        return 0 if same else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
