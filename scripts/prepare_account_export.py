#!/usr/bin/env python3
"""Extract only the current account data needed by the public report builder."""

from __future__ import annotations

import argparse
import csv
import io
import shutil
import zipfile
from pathlib import Path

CURRENT_FILES = ("watched.csv", "ratings.csv", "diary.csv", "reviews.csv", "watchlist.csv")


def prepare(zip_path: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        missing = (set(CURRENT_FILES) | {"profile.csv"}) - names
        if missing:
            raise ValueError(f"Missing expected export files: {sorted(missing)}")

        with archive.open("profile.csv") as source:
            profile = next(csv.DictReader(io.TextIOWrapper(source, encoding="utf-8-sig")))
        with (output_dir / "profile.csv").open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=["Username"])
            writer.writeheader()
            writer.writerow({"Username": profile["Username"]})

        for name in CURRENT_FILES:
            with archive.open(name) as source, (output_dir / name).open("wb") as target:
                shutil.copyfileobj(source, target)

        list_dir = output_dir / "lists"
        list_dir.mkdir(exist_ok=True)
        for name in sorted(names):
            if not name.startswith("lists/") or not name.endswith(".csv"):
                continue
            path = Path(name)
            if len(path.parts) != 2 or path.name in {".", ".."}:
                continue
            with archive.open(name) as source, (list_dir / path.name).open("wb") as target:
                shutil.copyfileobj(source, target)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    prepare(args.zip_path, args.output_dir)


if __name__ == "__main__":
    main()
