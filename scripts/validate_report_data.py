#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate generated Letterboxd report data.")
    parser.add_argument("--input-dir", required=True, help="Letterboxd export/public-sync input directory")
    parser.add_argument("--report-json", required=True, help="Generated custom-report-data.json")
    parser.add_argument("--index-html", required=True, help="Generated index.html")
    parser.add_argument("--output", required=True, help="Path for missing_data_report.md")
    return parser.parse_args()


def normalize(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def valid(value: Any) -> bool:
    return normalize(value) not in {"", "None", "nan", "NaN", "null"}


def film_key(name: Any, year: Any) -> str:
    name_text = normalize(name)
    year_text = normalize(year)
    if year_text.endswith(".0"):
        year_text = year_text[:-2]
    return f"{name_text} ({year_text})" if year_text else name_text


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def count_missing(rows: list[dict[str, Any]], field: str) -> int:
    return sum(1 for row in rows if not valid(row.get(field)))


def first_missing(rows: list[dict[str, Any]], field: str, limit: int = 80) -> list[str]:
    output: list[str] = []
    for row in rows:
        if valid(row.get(field)):
            continue
        name = normalize(row.get("name") or row.get("Name"))
        year = normalize(row.get("year") or row.get("Year"))
        status = normalize(row.get("douban_status") or row.get("imdb_rating_status") or row.get("letterboxd_status"))
        reason = ""
        if field == "douban_rating":
            if not valid(row.get("imdb_id")):
                reason = "no stable IMDb ID was available for the Douban ID map"
            elif status in {"no_rating", "not_found", "error", "missing_imdb"}:
                reason = f"Douban enrichment status `{status}`"
            else:
                reason = "no rated Douban match in the public dataset or cached PtGen detail map"
        elif field == "imdb_score":
            if not valid(row.get("imdb_id")):
                reason = "no IMDb title/year or Letterboxd ID match"
            else:
                reason = "IMDb ID exists but no numeric IMDb rating was available"
        suffix = f"; status `{status}`" if status else ""
        if reason:
            suffix += f"; reason: {reason}"
        output.append(f"- {name} ({year or 'unknown year'}): missing `{field}`{suffix}")
        if len(output) >= limit:
            break
    return output


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir)
    report_json = Path(args.report_json)
    index_html = Path(args.index_html)
    payload = json.loads(report_json.read_text(encoding="utf-8"))
    html = index_html.read_text(encoding="utf-8")

    watched_export = read_csv_rows(input_dir / "watched.csv")
    ratings_export = read_csv_rows(input_dir / "ratings.csv")
    watched_keys = {film_key(row.get("Name"), row.get("Year")) for row in watched_export}
    rating_keys = {film_key(row.get("Name"), row.get("Year")) for row in ratings_export}

    watched_rows = payload.get("watched_douban", {}).get("rows", [])
    streaming_rows = payload.get("streaming", {}).get("rows", [])
    recommendation_rows = payload.get("recommendations", {}).get("rows", [])
    all_movie_rows = streaming_rows

    watched_report_keys = {normalize(row.get("film_key")) for row in watched_rows if normalize(row.get("film_key"))}
    streaming_watched_keys = {
        normalize(row.get("watched_film_key") or row.get("film_key"))
        for row in streaming_rows
        if row.get("watched")
    }

    visible_html = html.split("<script", 1)[0].replace("中文", "")
    year_comma_matches = sorted(set(re.findall(r"\b(?:1|2),\d{3}\b", visible_html)))
    chinese_visible_matches = sorted(set(re.findall(r"[\u4e00-\u9fff]+", visible_html)))

    missing_watched_from_report = sorted(watched_keys - watched_report_keys)
    missing_watched_from_streaming = sorted(watched_keys - streaming_watched_keys)
    missing_user_ratings = sorted(
        key for key in rating_keys if key not in {
            normalize(row.get("film_key"))
            for row in watched_rows
            if valid(row.get("user_rating"))
        }
    )

    stats = {
        "all_movie_records": len(all_movie_rows),
        "watched_export_rows": len(watched_export),
        "ratings_export_rows": len(ratings_export),
        "watched_report_rows": len(watched_rows),
        "streaming_rows": len(streaming_rows),
        "recommendation_rows": len(recommendation_rows),
        "missing_douban_all_movie_rows": count_missing(all_movie_rows, "douban_rating"),
        "missing_imdb_all_movie_rows": count_missing(all_movie_rows, "imdb_score"),
        "missing_year_all_movie_rows": count_missing(all_movie_rows, "year"),
        "missing_watched_status_all_movie_rows": count_missing(all_movie_rows, "watched"),
        "missing_user_rating_watched_rows": count_missing(watched_rows, "user_rating"),
        "watched_export_missing_from_watched_report": len(missing_watched_from_report),
        "watched_export_missing_from_streaming": len(missing_watched_from_streaming),
        "rated_export_missing_user_rating": len(missing_user_ratings),
        "year_comma_display_matches": len(year_comma_matches),
        "english_visible_chinese_fragments": len(chinese_visible_matches),
    }

    lines = [
        "# Missing Data Report",
        "",
        "Generated by `scripts/validate_report_data.py`.",
        "",
        "## Validation Counts",
        "",
    ]
    lines.extend(f"- `{key}`: {value}" for key, value in stats.items())
    lines.extend(
        [
            "",
            "## Remaining Missing Douban Ratings",
            "",
            "These rows stayed blank after deterministic IMDb-ID, title/year, public Douban dataset, and cached PtGen enrichment attempts.",
        ]
    )
    lines.extend(first_missing(all_movie_rows, "douban_rating") or ["- None"])
    lines.extend(["", "## Remaining Missing IMDb Ratings", ""])
    lines.extend(first_missing(all_movie_rows, "imdb_score") or ["- None"])
    lines.extend(["", "## Watched/Rated Coverage Issues", ""])
    if missing_watched_from_report:
        lines.append(f"- Watched export rows missing from watched report: {len(missing_watched_from_report)}")
        lines.extend(f"  - {key}" for key in missing_watched_from_report[:40])
    else:
        lines.append("- All watched export rows are represented in the watched report.")
    if missing_watched_from_streaming:
        lines.append(f"- Watched export rows missing from streaming/all-movies table: {len(missing_watched_from_streaming)}")
        lines.extend(f"  - {key}" for key in missing_watched_from_streaming[:40])
    else:
        lines.append("- All watched export rows are represented in the streaming/all-movies table.")
    if missing_user_ratings:
        lines.append(f"- Rated export rows missing user rating in report: {len(missing_user_ratings)}")
        lines.extend(f"  - {key}" for key in missing_user_ratings[:40])
    else:
        lines.append("- All rated export rows have a user rating in the report.")
    lines.extend(["", "## Display Checks", ""])
    lines.append(f"- Year comma matches: {', '.join(year_comma_matches) if year_comma_matches else 'none'}")
    lines.append(
        "- Visible Chinese UI fragments in default English HTML: "
        + (", ".join(chinese_visible_matches[:40]) if chinese_visible_matches else "none")
    )

    output_path = Path(args.output)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))

    if year_comma_matches:
        raise SystemExit("Year display validation failed: comma-formatted years found.")
    if chinese_visible_matches:
        raise SystemExit("English UI validation failed: Chinese visible UI fragments found.")
    if missing_watched_from_report or missing_watched_from_streaming or missing_user_ratings:
        raise SystemExit("Watched/rated coverage validation failed.")


if __name__ == "__main__":
    main()
