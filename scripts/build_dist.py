#!/usr/bin/env python3

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    cleaned_path: list[str] = []
    for entry in sys.path:
        resolved = Path(entry or ".").resolve()
        if resolved == PROJECT_ROOT:
            continue
        cleaned_path.append(entry)
    sys.path[:] = cleaned_path

    from build import ProjectBuilder

    os.chdir(PROJECT_ROOT)
    shutil.rmtree(PROJECT_ROOT / "build", ignore_errors=True)
    shutil.rmtree(PROJECT_ROOT / "dist", ignore_errors=True)
    dist_dir = PROJECT_ROOT / "dist"
    builder = ProjectBuilder(".")
    builder.build("sdist", str(dist_dir))
    builder.build("wheel", str(dist_dir))
    print(f"Built distributions into {dist_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
