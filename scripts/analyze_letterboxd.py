#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
from lxml import etree
from lxml import html as lxml_html


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze a Letterboxd export and produce reusable JSON summaries."
    )
    parser.add_argument("--input-dir", required=True, help="Path to the Letterboxd export folder")
    parser.add_argument("--output-dir", required=True, help="Directory for generated analysis files")
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Concurrent metadata fetches for uncached films",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Ignore cached film metadata and fetch everything again",
    )
    return parser.parse_args()


def load_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig")


def normalize_cell(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def split_tags(value: Any) -> list[str]:
    text = normalize_cell(value)
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def unique_preserve_order(values: list[Any]) -> list[Any]:
    seen: set[Any] = set()
    out: list[Any] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def film_key(name: Any, year: Any) -> str:
    name_text = normalize_cell(name)
    if isinstance(year, (int, np.integer)):
        year_text = str(int(year))
    elif isinstance(year, (float, np.floating)) and not math.isnan(year) and float(year).is_integer():
        year_text = str(int(year))
    else:
        year_text = normalize_cell(year)
    return f"{name_text} ({year_text})" if year_text else name_text


def slugify_identifier(value: str) -> str:
    lowered = value.lower()
    lowered = re.sub(r"[^a-z0-9]+", "_", lowered)
    lowered = re.sub(r"_+", "_", lowered).strip("_")
    return lowered or "table"


def extract_json_ld(tree: Any) -> dict[str, Any]:
    scripts = tree.xpath("//script[@type='application/ld+json']/text()")
    for script_text in scripts:
        cleaned = re.sub(r"/\*.*?\*/", "", script_text, flags=re.S).strip()
        if not cleaned:
            continue
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            if item.get("aggregateRating") or item.get("@type") in {
                "Movie",
                "TVSeries",
                "CreativeWork",
                "Thing",
            }:
                return item
    return {}


def fetch_one_metadata(source_uri: str) -> dict[str, Any]:
    request = Request(
        source_uri,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        },
    )

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=25) as response:
                html_text = response.read().decode("utf-8", errors="ignore")
                final_url = response.geturl()
            tree = lxml_html.fromstring(html_text)
            json_ld = extract_json_ld(tree)

            directors = [
                item.get("name", "").strip()
                for item in ensure_list(json_ld.get("director"))
                if isinstance(item, dict) and normalize_cell(item.get("name"))
            ]
            actors = [
                item.get("name", "").strip()
                for item in ensure_list(json_ld.get("actors"))
                if isinstance(item, dict) and normalize_cell(item.get("name"))
            ]
            genres = [normalize_cell(item) for item in ensure_list(json_ld.get("genre")) if normalize_cell(item)]
            countries = [
                normalize_cell(item.get("name"))
                for item in ensure_list(json_ld.get("countryOfOrigin"))
                if isinstance(item, dict) and normalize_cell(item.get("name"))
            ]
            aggregate = json_ld.get("aggregateRating") if isinstance(json_ld.get("aggregateRating"), dict) else {}
            rating_value = aggregate.get("ratingValue")
            rating_count = aggregate.get("ratingCount")

            runtime_match = re.search(r"(\d+)\s*(?:&nbsp;|\s)?mins", html_text)
            runtime_minutes = int(runtime_match.group(1)) if runtime_match else None

            return {
                "source_uri": source_uri,
                "canonical_url": final_url.rstrip("/"),
                "canonical_slug": final_url.rstrip("/").split("/")[-1] if final_url else "",
                "metadata_title": normalize_cell(json_ld.get("name")),
                "site_average_rating": float(rating_value) if rating_value is not None else None,
                "site_rating_count": int(rating_count) if rating_count is not None else None,
                "runtime_minutes": runtime_minutes,
                "directors": unique_preserve_order(directors),
                "actors": unique_preserve_order(actors),
                "genres": unique_preserve_order(genres),
                "countries": unique_preserve_order(countries),
                "fetched_at": pd.Timestamp.utcnow().isoformat(),
            }
        except (HTTPError, URLError, ValueError, OSError, etree.ParserError) as exc:
            last_error = exc
            time.sleep(1.25 * (attempt + 1))

    return {
        "source_uri": source_uri,
        "canonical_url": "",
        "canonical_slug": "",
        "metadata_title": "",
        "site_average_rating": None,
        "site_rating_count": None,
        "runtime_minutes": None,
        "directors": [],
        "actors": [],
        "genres": [],
        "countries": [],
        "fetched_at": pd.Timestamp.utcnow().isoformat(),
        "error": normalize_cell(last_error),
    }


def load_metadata_cache(cache_path: Path) -> dict[str, Any]:
    if not cache_path.exists():
        return {}
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def fetch_metadata(source_uris: list[str], cache_path: Path, workers: int, refresh_cache: bool) -> pd.DataFrame:
    cache = load_metadata_cache(cache_path)
    missing = [uri for uri in source_uris if refresh_cache or uri not in cache]

    if missing:
        print(f"Fetching metadata for {len(missing)} uncached films...", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fetch_one_metadata, uri): uri for uri in missing}
            for index, future in enumerate(as_completed(futures), start=1):
                result = future.result()
                cache[result["source_uri"]] = result
                if index % 20 == 0 or index == len(futures):
                    print(f"  fetched {index}/{len(futures)}", file=sys.stderr)
                    cache_path.write_text(
                        json.dumps(cache, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    rows = [cache[uri] for uri in source_uris if uri in cache]
    metadata_df = pd.DataFrame(rows)
    if metadata_df.empty:
        metadata_df = pd.DataFrame(
            columns=[
                "source_uri",
                "canonical_url",
                "canonical_slug",
                "metadata_title",
                "site_average_rating",
                "site_rating_count",
                "runtime_minutes",
                "directors",
                "actors",
                "genres",
                "countries",
                "fetched_at",
            ]
        )
    return metadata_df


def make_scalar_preference_table(
    frame: pd.DataFrame,
    feature_col: str,
    label: str,
    global_mean: float,
    min_films: int,
    prior_weight: int,
    top_n: int = 15,
) -> pd.DataFrame:
    scoped = frame[[feature_col, "user_rating", "film_key"]].copy()
    scoped = scoped[scoped[feature_col].notna()]
    scoped = scoped[scoped[feature_col] != ""]
    grouped = (
        scoped.groupby(feature_col)
        .agg(
            films=("film_key", "nunique"),
            avg_rating=("user_rating", "mean"),
            five_star_share=("user_rating", lambda s: float((s >= 4.5).mean())),
        )
        .reset_index()
        .rename(columns={feature_col: label})
    )
    if grouped.empty:
        return grouped
    grouped["weighted_score"] = (
        grouped["avg_rating"] * grouped["films"] + global_mean * prior_weight
    ) / (grouped["films"] + prior_weight)
    grouped = grouped[grouped["films"] >= min_films]
    grouped = grouped.sort_values(
        ["weighted_score", "films", "avg_rating"],
        ascending=[False, False, False],
    ).head(top_n)
    return grouped.reset_index(drop=True)


def make_list_preference_table(
    frame: pd.DataFrame,
    feature_col: str,
    label: str,
    global_mean: float,
    min_films: int,
    prior_weight: int,
    top_n: int = 15,
) -> pd.DataFrame:
    scoped = frame[[feature_col, "user_rating", "film_key"]].copy()
    scoped = scoped.explode(feature_col)
    scoped = scoped[scoped[feature_col].notna()]
    scoped[feature_col] = scoped[feature_col].astype(str).str.strip()
    scoped = scoped[scoped[feature_col] != ""]
    grouped = (
        scoped.groupby(feature_col)
        .agg(
            films=("film_key", "nunique"),
            avg_rating=("user_rating", "mean"),
            five_star_share=("user_rating", lambda s: float((s >= 4.5).mean())),
        )
        .reset_index()
        .rename(columns={feature_col: label})
    )
    if grouped.empty:
        return grouped
    grouped["weighted_score"] = (
        grouped["avg_rating"] * grouped["films"] + global_mean * prior_weight
    ) / (grouped["films"] + prior_weight)
    grouped = grouped[grouped["films"] >= min_films]
    grouped = grouped.sort_values(
        ["weighted_score", "films", "avg_rating"],
        ascending=[False, False, False],
    ).head(top_n)
    return grouped.reset_index(drop=True)


def build_bonus_lookup(
    frame: pd.DataFrame,
    feature_col: str,
    global_mean: float,
    prior_weight: int,
    list_like: bool = False,
) -> dict[str, dict[str, float]]:
    scoped = frame[[feature_col, "user_rating", "film_key"]].copy()
    if list_like:
        scoped = scoped.explode(feature_col)
    scoped = scoped[scoped[feature_col].notna()]
    scoped[feature_col] = scoped[feature_col].astype(str).str.strip()
    scoped = scoped[scoped[feature_col] != ""]
    if scoped.empty:
        return {}
    grouped = (
        scoped.groupby(feature_col)
        .agg(films=("film_key", "nunique"), avg_rating=("user_rating", "mean"))
        .reset_index()
    )
    grouped["bonus"] = (
        grouped["avg_rating"] * grouped["films"] + global_mean * prior_weight
    ) / (grouped["films"] + prior_weight) - global_mean
    return {
        row[feature_col]: {
            "films": int(row["films"]),
            "avg_rating": float(row["avg_rating"]),
            "bonus": float(row["bonus"]),
        }
        for _, row in grouped.iterrows()
    }


def build_watchlist_priority(
    watched_df: pd.DataFrame,
    watchlist_df: pd.DataFrame,
    global_mean: float,
    site_mean: float,
) -> pd.DataFrame:
    director_bonus = build_bonus_lookup(watched_df, "directors", global_mean, 4, list_like=True)
    genre_bonus = build_bonus_lookup(watched_df, "genres", global_mean, 7, list_like=True)
    country_bonus = build_bonus_lookup(watched_df, "countries", global_mean, 5, list_like=True)
    actor_bonus = build_bonus_lookup(watched_df, "actors", global_mean, 9, list_like=True)
    decade_bonus = build_bonus_lookup(watched_df, "decade_label", global_mean, 8)
    runtime_bonus = build_bonus_lookup(watched_df, "runtime_bucket", global_mean, 10)

    def feature_contribution(
        values: list[str],
        lookup: dict[str, dict[str, float]],
        weight: float,
        min_films: int,
        prefix: str,
    ) -> tuple[float, float, list[tuple[str, float, int]]]:
        matched: list[tuple[str, float, int]] = []
        for value in values:
            item = lookup.get(value)
            if not item or item["films"] < min_films:
                continue
            matched.append((value, item["bonus"], int(item["films"])))
        if not matched:
            return 0.0, 0.0, []
        avg_bonus = float(np.mean([item[1] for item in matched]))
        confidence = min(1.0, sum(min(item[2], 8) for item in matched) / 20.0)
        return weight * avg_bonus, confidence, matched

    rows: list[dict[str, Any]] = []
    for _, row in watchlist_df.iterrows():
        reasons: list[tuple[str, float]] = []

        director_part, director_conf, director_hits = feature_contribution(
            ensure_list(row["directors"]),
            director_bonus,
            0.36,
            2,
            "导演",
        )
        genre_part, genre_conf, genre_hits = feature_contribution(
            ensure_list(row["genres"]),
            genre_bonus,
            0.24,
            5,
            "类型",
        )
        country_part, country_conf, country_hits = feature_contribution(
            ensure_list(row["countries"]),
            country_bonus,
            0.10,
            3,
            "国家",
        )
        actor_part, actor_conf, actor_hits = feature_contribution(
            ensure_list(row["actors"])[:5],
            actor_bonus,
            0.10,
            4,
            "演员",
        )

        decade_key = normalize_cell(row["decade_label"])
        decade_item = decade_bonus.get(decade_key)
        decade_part = 0.0
        decade_conf = 0.0
        if decade_item and decade_item["films"] >= 8:
            decade_part = 0.10 * decade_item["bonus"]
            decade_conf = min(1.0, decade_item["films"] / 20.0)
            reasons.append((f"年代 {decade_key}", decade_part))

        runtime_key = normalize_cell(row["runtime_bucket"])
        runtime_item = runtime_bonus.get(runtime_key)
        runtime_part = 0.0
        runtime_conf = 0.0
        if runtime_item and runtime_item["films"] >= 10:
            runtime_part = 0.05 * runtime_item["bonus"]
            runtime_conf = min(1.0, runtime_item["films"] / 25.0)
            reasons.append((f"片长 {runtime_key}", runtime_part))

        for label, bonus, _count in director_hits:
            reasons.append((f"导演 {label}", 0.36 * bonus))
        for label, bonus, _count in genre_hits:
            reasons.append((f"类型 {label}", 0.24 * bonus))
        for label, bonus, _count in country_hits:
            reasons.append((f"国家 {label}", 0.10 * bonus))
        for label, bonus, _count in actor_hits:
            reasons.append((f"演员 {label}", 0.10 * bonus))

        site_part = 0.0
        if pd.notna(row["site_average_rating"]):
            site_part = 0.22 * (float(row["site_average_rating"]) - site_mean)
            reasons.append((f"站内口碑 {float(row['site_average_rating']):.2f}", site_part))

        predicted = global_mean + director_part + genre_part + country_part + actor_part + decade_part + runtime_part + site_part
        predicted = float(np.clip(predicted, 0.5, 5.0))

        confidence = float(
            np.clip(
                np.mean(
                    [
                        director_conf,
                        genre_conf,
                        country_conf,
                        actor_conf,
                        decade_conf,
                        runtime_conf,
                    ]
                )
                + (0.12 if pd.notna(row["site_average_rating"]) else 0.0),
                0.05,
                1.0,
            )
        )

        best_reasons = [
            reason for reason, contribution in sorted(reasons, key=lambda item: item[1], reverse=True) if contribution > 0.02
        ][:3]
        explanation = "；".join(best_reasons) if best_reasons else "主要依赖你整体口味和站内口碑的基础预测"

        rows.append(
            {
                "name": row["Name"],
                "year": int(row["Year"]) if pd.notna(row["Year"]) else None,
                "source_uri": row["Letterboxd URI"],
                "predicted_rating": round(predicted, 3),
                "confidence": round(confidence, 3),
                "site_average_rating": round(float(row["site_average_rating"]), 3)
                if pd.notna(row["site_average_rating"])
                else None,
                "site_rating_count": int(row["site_rating_count"]) if pd.notna(row["site_rating_count"]) else None,
                "directors": row["directors"],
                "genres": row["genres"],
                "countries": row["countries"],
                "reason": explanation,
            }
        )

    priority_df = pd.DataFrame(rows)
    priority_df["priority_score"] = priority_df["predicted_rating"] + priority_df["confidence"] * 0.18
    priority_df = priority_df.sort_values(
        ["priority_score", "predicted_rating", "site_average_rating"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    priority_df.insert(0, "rank", np.arange(1, len(priority_df) + 1))
    return priority_df


def serialize_frame(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    cleaned = frame.replace({np.nan: None})
    return json.loads(cleaned.to_json(orient="records", force_ascii=False))


def build_insights(
    ratings_df: pd.DataFrame,
    diary_df: pd.DataFrame,
    genre_table: pd.DataFrame,
    director_table: pd.DataFrame,
    decade_table: pd.DataFrame,
    tag_table: pd.DataFrame,
    positive_gap: pd.DataFrame,
    rewatch_table: pd.DataFrame,
    watchlist_df: pd.DataFrame,
) -> list[dict[str, str]]:
    insights: list[dict[str, str]] = []

    avg_rating = ratings_df["user_rating"].mean()
    five_star_share = (ratings_df["user_rating"] == 5.0).mean()
    insights.append(
        {
            "headline": "整体打分口味",
            "detail": f"你目前给 {len(ratings_df)} 部片打过分，平均分是 {avg_rating:.2f}，其中 {five_star_share:.1%} 是满分。",
        }
    )

    if not decade_table.empty:
        top = decade_table.iloc[0]
        insights.append(
            {
                "headline": "偏爱年代",
                "detail": f"在样本足够的年代里，你目前最偏爱 {top['decade_label']}，平均分 {top['avg_rating']:.2f}，共看了 {int(top['films'])} 部。",
            }
        )

    if not genre_table.empty:
        top = genre_table.iloc[0]
        insights.append(
            {
                "headline": "偏爱类型",
                "detail": f"你最稳定的高分类型是 {top['genre']}，平均分 {top['avg_rating']:.2f}，5 星或 4.5 星的占比也很高。",
            }
        )

    if not director_table.empty:
        top = director_table.iloc[0]
        insights.append(
            {
                "headline": "导演舒适区",
                "detail": f"导演层面最像舒适区的是 {top['director']}，你已经看过 {int(top['films'])} 部，平均分 {top['avg_rating']:.2f}。",
            }
        )

    if not tag_table.empty:
        top = tag_table.iloc[0]
        insights.append(
            {
                "headline": "观影场景",
                "detail": f"从你最常用且样本足够的标签来看，`{top['tag']}` 这个场景下的平均分最高，说明环境会明显影响你的体验。",
            }
        )

    if not positive_gap.empty:
        top = positive_gap.iloc[0]
        insights.append(
            {
                "headline": "最强个人偏爱",
                "detail": f"和 Letterboxd 总体口碑相比，你最明显高估的是《{top['name']}》，你的评分比站内均分高出 {top['gap_vs_site']:.2f}。",
            }
        )

    if not rewatch_table.empty:
        top = rewatch_table.iloc[0]
        insights.append(
            {
                "headline": "重看最频繁",
                "detail": f"你重看最多的是《{top['name']}》，累计看了 {int(top['watch_count'])} 次，说明它已经接近你的私人“安慰片”了。",
            }
        )

    if not watchlist_df.empty:
        top = watchlist_df.iloc[0]
        insights.append(
            {
                "headline": "下一部优先看",
                "detail": f"按你的历史口味推算，watchlist 里最值得优先补的是《{top['name']}》({int(top['year'])})，预测你会给到 {top['predicted_rating']:.2f} 分。",
            }
        )

    return insights[:8]


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_path = output_dir / "film_metadata_cache.json"

    ratings_df = load_csv(input_dir / "ratings.csv")
    diary_df = load_csv(input_dir / "diary.csv")
    reviews_df = load_csv(input_dir / "reviews.csv")
    watchlist_df = load_csv(input_dir / "watchlist.csv")
    profile_df = load_csv(input_dir / "profile.csv")

    for frame in (ratings_df, diary_df, reviews_df, watchlist_df):
        frame["film_key"] = frame.apply(lambda row: film_key(row.get("Name"), row.get("Year")), axis=1)

    ratings_df["user_rating"] = pd.to_numeric(ratings_df["Rating"], errors="coerce")
    ratings_df["year"] = pd.to_numeric(ratings_df["Year"], errors="coerce")
    ratings_df["logged_date"] = pd.to_datetime(ratings_df["Date"], errors="coerce")

    diary_df["user_rating"] = pd.to_numeric(diary_df["Rating"], errors="coerce")
    diary_df["year"] = pd.to_numeric(diary_df["Year"], errors="coerce")
    diary_df["logged_date"] = pd.to_datetime(diary_df["Date"], errors="coerce")
    diary_df["watched_date"] = pd.to_datetime(diary_df["Watched Date"], errors="coerce")
    diary_df["rewatch"] = diary_df["Rewatch"].fillna("").astype(str).str.strip().ne("")
    diary_df["tags_list"] = diary_df["Tags"].apply(split_tags)

    reviews_df["review_words"] = (
        reviews_df["Review"].fillna("").astype(str).str.replace(r"\s+", " ", regex=True).str.strip().str.split(" ").str.len()
    )
    reviews_df["user_rating"] = pd.to_numeric(reviews_df["Rating"], errors="coerce")

    watchlist_df["year"] = pd.to_numeric(watchlist_df["Year"], errors="coerce")
    watchlist_df["added_date"] = pd.to_datetime(watchlist_df["Date"], errors="coerce")

    source_df = pd.concat(
        [
            ratings_df[["Letterboxd URI", "Name", "Year"]],
            watchlist_df[["Letterboxd URI", "Name", "Year"]],
        ],
        ignore_index=True,
    ).drop_duplicates(subset=["Letterboxd URI"])

    metadata_df = fetch_metadata(
        source_df["Letterboxd URI"].dropna().astype(str).tolist(),
        cache_path=cache_path,
        workers=max(1, args.workers),
        refresh_cache=args.refresh_cache,
    )

    ratings_df = ratings_df.merge(
        metadata_df,
        how="left",
        left_on="Letterboxd URI",
        right_on="source_uri",
    )
    watchlist_df = watchlist_df.merge(
        metadata_df,
        how="left",
        left_on="Letterboxd URI",
        right_on="source_uri",
    )

    film_lookup = ratings_df[
        [
            "film_key",
            "directors",
            "actors",
            "genres",
            "countries",
            "site_average_rating",
            "site_rating_count",
            "runtime_minutes",
            "canonical_url",
        ]
    ].drop_duplicates(subset=["film_key"])

    diary_df = diary_df.merge(film_lookup, how="left", on="film_key")

    ratings_df["decade_label"] = ratings_df["year"].dropna().floordiv(10).mul(10).astype("Int64").astype(str) + "s"
    watchlist_df["decade_label"] = watchlist_df["year"].dropna().floordiv(10).mul(10).astype("Int64").astype(str) + "s"
    ratings_df.loc[ratings_df["year"].isna(), "decade_label"] = None
    watchlist_df.loc[watchlist_df["year"].isna(), "decade_label"] = None

    bins = [0, 90, 110, 130, 150, 1000]
    labels = ["Under 90", "90-109", "110-129", "130-149", "150+"]
    ratings_df["runtime_bucket"] = pd.cut(
        ratings_df["runtime_minutes"], bins=bins, labels=labels, right=False
    ).astype("string")
    watchlist_df["runtime_bucket"] = pd.cut(
        watchlist_df["runtime_minutes"], bins=bins, labels=labels, right=False
    ).astype("string")

    global_mean = float(ratings_df["user_rating"].mean())
    site_mean = float(ratings_df["site_average_rating"].dropna().mean())

    rating_distribution = (
        ratings_df.groupby("user_rating")
        .size()
        .reset_index(name="films")
        .sort_values("user_rating")
        .reset_index(drop=True)
    )

    watch_year = (
        diary_df.assign(watch_year=diary_df["watched_date"].dt.year.fillna(diary_df["logged_date"].dt.year))
        .dropna(subset=["watch_year"])
        .groupby("watch_year")
        .agg(watches=("film_key", "size"), avg_rating=("user_rating", "mean"))
        .reset_index()
        .sort_values("watch_year")
    )

    decade_table = make_scalar_preference_table(
        ratings_df,
        "decade_label",
        "decade_label",
        global_mean,
        min_films=10,
        prior_weight=5,
    )
    genre_table = make_list_preference_table(
        ratings_df,
        "genres",
        "genre",
        global_mean,
        min_films=8,
        prior_weight=6,
    )
    country_table = make_list_preference_table(
        ratings_df,
        "countries",
        "country",
        global_mean,
        min_films=5,
        prior_weight=5,
    )
    director_table = make_list_preference_table(
        ratings_df,
        "directors",
        "director",
        global_mean,
        min_films=3,
        prior_weight=4,
    )
    actor_table = make_list_preference_table(
        ratings_df,
        "actors",
        "actor",
        global_mean,
        min_films=4,
        prior_weight=8,
    )
    runtime_table = make_scalar_preference_table(
        ratings_df,
        "runtime_bucket",
        "runtime_bucket",
        global_mean,
        min_films=10,
        prior_weight=7,
    )

    tag_scoped = diary_df[["tags_list", "user_rating", "film_key", "rewatch"]].explode("tags_list")
    tag_scoped = tag_scoped[tag_scoped["tags_list"].notna()]
    tag_scoped["tags_list"] = tag_scoped["tags_list"].astype(str).str.strip()
    tag_scoped = tag_scoped[tag_scoped["tags_list"] != ""]
    tag_table = (
        tag_scoped.groupby("tags_list")
        .agg(
            watches=("film_key", "size"),
            unique_films=("film_key", "nunique"),
            avg_rating=("user_rating", "mean"),
            rewatch_share=("rewatch", "mean"),
        )
        .reset_index()
        .rename(columns={"tags_list": "tag"})
    )
    tag_table = tag_table[tag_table["watches"] >= 5].sort_values(
        ["avg_rating", "watches"], ascending=[False, False]
    ).head(20)

    film_counts = diary_df.groupby("film_key").size().reset_index(name="watch_count")
    first_info = diary_df.drop_duplicates(subset=["film_key"])[["film_key", "Name", "Year", "user_rating"]]
    rewatch_table = film_counts.merge(first_info, on="film_key", how="left")
    rewatch_table = rewatch_table[rewatch_table["watch_count"] > 1].sort_values(
        ["watch_count", "user_rating"], ascending=[False, False]
    ).head(20)
    rewatch_table = rewatch_table.rename(columns={"user_rating": "latest_rating", "Name": "name", "Year": "year"})

    ratings_df["gap_vs_site"] = ratings_df["user_rating"] - ratings_df["site_average_rating"]
    gap_scoped = ratings_df[ratings_df["gap_vs_site"].notna()].copy()
    positive_gap = gap_scoped.sort_values(
        ["gap_vs_site", "site_rating_count"], ascending=[False, False]
    ).head(20)
    negative_gap = gap_scoped.sort_values(
        ["gap_vs_site", "site_rating_count"], ascending=[True, False]
    ).head(20)

    positive_gap = positive_gap[
        ["Name", "Year", "user_rating", "site_average_rating", "gap_vs_site", "site_rating_count", "directors", "genres"]
    ].rename(columns={"Name": "name", "Year": "year"})
    negative_gap = negative_gap[
        ["Name", "Year", "user_rating", "site_average_rating", "gap_vs_site", "site_rating_count", "directors", "genres"]
    ].rename(columns={"Name": "name", "Year": "year"})

    watchlist_priority = build_watchlist_priority(ratings_df, watchlist_df, global_mean, site_mean)

    review_summary = {
        "reviews_written": int(len(reviews_df)),
        "average_review_words": round(float(reviews_df["review_words"].mean()), 1) if len(reviews_df) else 0,
        "longest_review_words": int(reviews_df["review_words"].max()) if len(reviews_df) else 0,
    }

    insights = build_insights(
        ratings_df=ratings_df,
        diary_df=diary_df,
        genre_table=genre_table,
        director_table=director_table,
        decade_table=decade_table,
        tag_table=tag_table,
        positive_gap=positive_gap,
        rewatch_table=rewatch_table,
        watchlist_df=watchlist_priority,
    )

    profile_row = profile_df.iloc[0].to_dict() if len(profile_df) else {}
    metrics = {
        "username": normalize_cell(profile_row.get("Username")),
        "date_joined": normalize_cell(profile_row.get("Date Joined")),
        "unique_rated_films": int(len(ratings_df)),
        "watch_events": int(len(diary_df)),
        "rewatches": int(diary_df["rewatch"].sum()),
        "watchlist_size": int(len(watchlist_df)),
        "average_rating": round(global_mean, 3),
        "median_rating": round(float(ratings_df["user_rating"].median()), 3),
        "five_star_count": int((ratings_df["user_rating"] == 5.0).sum()),
        "five_star_share": round(float((ratings_df["user_rating"] == 5.0).mean()), 4),
        "reviews_written": review_summary["reviews_written"],
        "average_review_words": review_summary["average_review_words"],
    }

    films_export = ratings_df[
        [
            "Name",
            "Year",
            "user_rating",
            "site_average_rating",
            "gap_vs_site",
            "runtime_minutes",
            "decade_label",
            "directors",
            "genres",
            "countries",
            "actors",
            "canonical_url",
        ]
    ].rename(columns={"Name": "name", "Year": "year"})
    films_export = films_export.sort_values(["user_rating", "year", "name"], ascending=[False, False, True])

    watchlist_export = watchlist_priority[
        [
            "rank",
            "name",
            "year",
            "priority_score",
            "predicted_rating",
            "confidence",
            "site_average_rating",
            "site_rating_count",
            "directors",
            "genres",
            "countries",
            "reason",
            "source_uri",
        ]
    ]

    payload = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "input_dir": str(input_dir),
        "metrics": metrics,
        "profile": {
            "username": normalize_cell(profile_row.get("Username")),
            "given_name": normalize_cell(profile_row.get("Given Name")),
            "family_name": normalize_cell(profile_row.get("Family Name")),
            "location": normalize_cell(profile_row.get("Location")),
            "bio": normalize_cell(profile_row.get("Bio")),
        },
        "insights": insights,
        "tables": {
            "rating_distribution": serialize_frame(rating_distribution),
            "watch_year": serialize_frame(watch_year),
            "genre_preferences": serialize_frame(genre_table),
            "country_preferences": serialize_frame(country_table),
            "director_preferences": serialize_frame(director_table),
            "actor_preferences": serialize_frame(actor_table),
            "decade_preferences": serialize_frame(decade_table),
            "runtime_preferences": serialize_frame(runtime_table),
            "tag_preferences": serialize_frame(tag_table),
            "positive_contrarian": serialize_frame(positive_gap),
            "negative_contrarian": serialize_frame(negative_gap),
            "rewatches": serialize_frame(rewatch_table),
            "watchlist_priority": serialize_frame(watchlist_export),
            "films": serialize_frame(films_export),
        },
    }

    analysis_path = output_dir / "analysis.json"
    analysis_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote analysis to {analysis_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
