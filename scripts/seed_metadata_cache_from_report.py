#!/usr/bin/env python3
"""Reuse public film metadata from the previous report during an account-export rebuild."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from analyze_letterboxd import film_key
from build_custom_letterboxd_report import load_list_exports


def source_rows(input_dir: Path) -> dict[str, tuple[str, str]]:
    rows = {}
    for name in ("ratings.csv", "watchlist.csv"):
        with (input_dir / name).open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                uri = row.get("Letterboxd URI", "").strip()
                if uri:
                    rows[uri] = (row.get("Name", ""), row.get("Year", ""))
    for _, row in load_list_exports(input_dir / "lists").iterrows():
        uri = str(row["Letterboxd URI"]).strip()
        if uri:
            rows[uri] = (str(row["Name"]), row["Year"])
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    source = source_rows(args.input_dir)
    by_uri = {}
    by_key = {}
    for row in report["streaming"]["rows"]:
        uri = (row.get("source_uri") or "").rstrip("/")
        if uri:
            by_uri[uri] = row
        key = row.get("matched_film_key") or row.get("film_key")
        if key and row.get("genres"):
            by_key[key] = row

    cache = {}
    missing = []
    for uri, (name, year) in source.items():
        row = by_uri.get(uri.rstrip("/")) or by_key.get(film_key(name, year))
        if row is None:
            missing.append((name, year))
            continue
        genres = row.get("genres") or []
        cache[uri] = {
            "source_uri": uri,
            "canonical_url": row.get("letterboxd_url") or uri.rstrip("/"),
            "canonical_slug": uri.rstrip("/").split("/")[-1],
            "metadata_title": row.get("name") or name,
            "site_average_rating": row.get("site_average_rating") or row.get("letterboxd_rating"),
            "site_rating_count": row.get("site_rating_count") or row.get("letterboxd_rating_count"),
            "runtime_minutes": row.get("runtime_minutes"),
            "directors": row.get("directors") or [],
            "actors": row.get("actors") or [],
            "genres": [value.get("label") or value.get("code") if isinstance(value, dict) else value for value in genres],
            "countries": row.get("countries") or [],
            "fetched_at": report["generated_at"],
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Seeded {len(cache)} of {len(source)} films; {len(missing)} still need metadata")
    if missing:
        print("Unmatched sample:", missing[:10])


if __name__ == "__main__":
    main()
