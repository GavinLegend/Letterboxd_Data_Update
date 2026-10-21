#!/usr/bin/env python3
"""Prevent an incomplete public-page sync from replacing a fuller report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def coverage(report: dict) -> dict[str, int]:
    metrics = report.get("metrics") or {}
    reviews = (report.get("reviews") or {}).get("stats") or {}
    return {
        "watched_films": int(metrics.get("watched_films") or 0),
        "watch_events": int(metrics.get("watch_events") or 0),
        "tagged_watch_events": int(metrics.get("tagged_watch_events") or 0),
        "custom_lists": int(metrics.get("custom_lists") or 0),
        "reviews": int(reviews.get("review_count") or 0),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--existing", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    existing = coverage(json.loads(args.existing.read_text(encoding="utf-8")))
    candidate = coverage(json.loads(args.candidate.read_text(encoding="utf-8")))
    decreased = [key for key, value in existing.items() if candidate[key] < value]
    if decreased:
        print(f"Keeping current report: candidate has fewer {', '.join(decreased)}", file=sys.stderr)
    print("true" if decreased else "false")


if __name__ == "__main__":
    main()
