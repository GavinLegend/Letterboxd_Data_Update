#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import os
import re
import signal
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from http.cookiejar import CookieJar
from pathlib import Path
from statistics import mean
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode, urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd

VENDOR_DIR = Path(__file__).resolve().parent.parent / ".vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None

from analyze_letterboxd import (
    ensure_list,
    fetch_metadata,
    film_key,
    load_csv,
    normalize_cell,
    serialize_frame,
    slugify_identifier,
    split_tags,
)


STOPWORDS = {
    "a",
    "about",
    "actually",
    "again",
    "all",
    "almost",
    "also",
    "am",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "back",
    "be",
    "because",
    "been",
    "before",
    "being",
    "best",
    "better",
    "bit",
    "but",
    "by",
    "can",
    "could",
    "did",
    "didn",
    "do",
    "does",
    "don",
    "down",
    "even",
    "ever",
    "every",
    "feel",
    "felt",
    "few",
    "film",
    "films",
    "first",
    "for",
    "from",
    "get",
    "go",
    "good",
    "great",
    "had",
    "has",
    "have",
    "he",
    "her",
    "here",
    "him",
    "his",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "itself",
    "just",
    "kind",
    "kinda",
    "know",
    "like",
    "lot",
    "made",
    "make",
    "many",
    "me",
    "might",
    "more",
    "most",
    "movie",
    "movies",
    "much",
    "my",
    "never",
    "no",
    "not",
    "now",
    "of",
    "off",
    "on",
    "one",
    "only",
    "or",
    "other",
    "our",
    "out",
    "over",
    "part",
    "people",
    "probably",
    "really",
    "right",
    "same",
    "say",
    "see",
    "seems",
    "she",
    "so",
    "some",
    "something",
    "still",
    "such",
    "tbh",
    "than",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "thing",
    "think",
    "this",
    "those",
    "though",
    "through",
    "to",
    "too",
    "very",
    "was",
    "watch",
    "watched",
    "watching",
    "way",
    "we",
    "well",
    "were",
    "what",
    "when",
    "which",
    "while",
    "who",
    "will",
    "with",
    "without",
    "would",
    "yeah",
    "you",
    "your",
    "it's",
    "don't",
    "maybe",
    "admit",
    "give",
    "years",
    "life",
    "tell",
    "young",
    "simple",
    "thearter",
    "theater",
    "watchparty",
    "withppl",
    "withseb",
    "withwayne",
    "myself",
    "ipad",
    "monitor",
    "tv",
    "phone",
    "projector",
    "downloaded",
    "bilibili",
    "netflix",
    "aiyifan",
    "criterion",
    "youtube",
    "crave",
    "disc",
}

THEME_KEYWORDS = {
    "Story & logic": [
        "story",
        "plot",
        "script",
        "writing",
        "ending",
        "pace",
        "pacing",
        "logic",
        "structure",
        "narrative",
    ],
    "Characters & relationships": [
        "character",
        "characters",
        "relationship",
        "marriage",
        "chemistry",
        "dynamic",
        "villain",
        "protagonist",
    ],
    "Acting & casting": [
        "acting",
        "actor",
        "actors",
        "actress",
        "actresses",
        "performance",
        "performances",
        "cast",
        "stunning",
        "starred",
        "fits",
    ],
    "Visual craft": [
        "cinematography",
        "visual",
        "visuals",
        "camera",
        "shot",
        "shots",
        "style",
        "animation",
        "design",
        "looks",
    ],
    "Emotion & impact": [
        "emotional",
        "emotion",
        "moving",
        "touching",
        "heartbreaking",
        "impact",
        "relatable",
        "moved",
        "absorbed",
    ],
    "Realism & authenticity": [
        "real",
        "realistic",
        "reality",
        "believable",
        "authentic",
        "historical",
        "genuine",
    ],
    "Music & sound": [
        "music",
        "score",
        "sound",
        "soundtrack",
        "song",
        "songs",
        "voice",
    ],
    "Fun vs boredom": [
        "fun",
        "entertaining",
        "enjoy",
        "enjoyed",
        "enjoyable",
        "boring",
        "dull",
        "cute",
        "handsome",
    ],
}

DEVICE_PRIORITY = ["projector", "tv", "monitor", "ipad", "phone"]
VENUE_MAP = {
    "thearter": "Theater",
    "theater": "Theater",
    "friendsplace": "Friend's place",
    "onplane": "On plane",
}
PLATFORM_LABEL_OVERRIDES = {
    "amazonprime": "Amazon Prime",
    "aiyifan": "Aiyifan",
    "bilibili": "Bilibili",
    "criterion": "Criterion",
    "downloaded": "Downloaded",
    "hollywood suite": "Hollywood Suite",
    "netflix": "Netflix",
    "youtube": "YouTube",
    "youku": "Youku",
}
PLATFORM_TAGS = [
    "downloaded",
    "disc",
    "bilibili",
    "aiyifan",
    "netflix",
    "crave",
    "youku",
    "criterion",
    "youtube",
    "amazonprime",
    "hollywood suite",
]
FUTURE_LIST_WEIGHTS = {
    "Official Watchlist": 1.00,
    "Want to watch soon": 1.20,
    "2026 Films Watchlist (to be updated)": 1.05,
    "I need these to make up my films by year.": 0.95,
    "They've been in my playlist for too long.": 0.85,
    "ChatGPT Recommended": 0.90,
}
JUSTWATCH_GRAPHQL_URL = "https://apis.justwatch.com/graphql"
JUSTWATCH_BASE_URL = "https://www.justwatch.com"
LETTERBOXD_BASE_URL = "https://letterboxd.com"
LETTERBOXD_IMPERSONATE = "chrome136"
DOUBAN_API_BASE_URL = "https://m.douban.com/rexxar/api/v2"
DOUBAN_SUGGEST_URL = "https://movie.douban.com/j/subject_suggest"
DOUBAN_SUBJECT_SEARCH_URL = "https://movie.douban.com/subject_search"
DOUBAN_PUBLIC_DATASET_URL = "https://raw.githubusercontent.com/jlshix/movielens-douban-dataset/master/spider.json"
PTGEN_DOUBAN_IMDB_MAP_URL = "https://ourbits.github.io/PtGen/internal_map/douban_imdb_map.json"
PTGEN_DOUBAN_DETAIL_URL = "https://ourbits.github.io/PtGen/douban/{subject_id}.json"
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
RATING_BUCKET_VALUES = [0.5 + 0.5 * index for index in range(10)]
STREAMING_CACHE_VERSION = 2
DOUBAN_CACHE_VERSION = 4
WATCHED_DOUBAN_CACHE_VERSION = 9
WATCHED_DOUBAN_SUBJECT_OVERRIDES = {
    # Letterboxd exports some TV episodes as standalone film rows. Douban usually
    # keeps ratings on the season page, so these are intentionally parent matches.
    "Sherlock: A Study in Pink (2010)": ("3986493", "parent_series"),
    "Sherlock: The Blind Banker (2010)": ("3986493", "parent_series"),
    "Sherlock: The Great Game (2010)": ("3986493", "parent_series"),
    "Sherlock: The Hounds of Baskerville (2012)": ("6522269", "parent_series"),
    "Sherlock: The Reichenbach Fall (2012)": ("6522269", "parent_series"),
    "Sherlock: The Sign of Three (2014)": ("10455629", "parent_series"),
    "Sherlock: The Lying Detective (2017)": ("25750923", "parent_series"),
    "Sherlock: The Final Problem (2017)": ("25750923", "parent_series"),
    "Love, Death & Robots: Beyond the Aquila Rift (2019)": ("30424374", "parent_series"),
    "Love, Death & Robots: Fish Night (2019)": ("30424374", "parent_series"),
    "Love, Death & Robots: Good Hunting (2019)": ("30424374", "parent_series"),
    "Love, Death & Robots: Shape-Shifters (2019)": ("30424374", "parent_series"),
    "Love, Death & Robots: Sonnie's Edge (2019)": ("30424374", "parent_series"),
    "Love, Death & Robots: Sucker of Souls (2019)": ("30424374", "parent_series"),
    "Love, Death & Robots: Suits (2019)": ("30424374", "parent_series"),
    "Love, Death & Robots: The Dump (2019)": ("30424374", "parent_series"),
    "Love, Death & Robots: The Witness (2019)": ("30424374", "parent_series"),
    "Love, Death & Robots: Three Robots (2019)": ("30424374", "parent_series"),
    # Public Letterboxd metadata misses IMDb IDs for a few Chinese animation/TV rows.
    "Inspector Black Cat (1984)": ("1860377", "manual_subject"),
    "Genghis Khan (2004)": ("2993072", "manual_subject"),
    "Tokyo 2020 Olympic Opening Ceremony: United by Emotion (2021)": ("36883921", "manual_subject"),
}
WATCHED_DOUBAN_HISTORICAL_RATING_OVERRIDES = {
    # These Douban subjects are now unavailable or expose no numeric score, but
    # multiple public archives still preserve the former Douban score.
    "Chernobyl (2019)": {
        "douban_id": "27098632",
        "douban_title": "切尔诺贝利 Chernobyl",
        "douban_rating": 9.6,
        "douban_rating_count": 319287,
        "douban_year": "2019",
        "source_url": "https://www.pdoro.com/930.html",
    },
    "A Taxi Driver (2017)": {
        "douban_id": "26705541",
        "douban_title": "出租车司机 A Taxi Driver",
        "douban_rating": 9.1,
        "douban_rating_count": 30000,
        "douban_year": "2017",
        "source_url": "https://zh.wikipedia.org/wiki/%E6%88%91%E5%8F%AA%E6%98%AF%E5%80%8B%E8%A8%88%E7%A8%8B%E8%BB%8A%E5%8F%B8%E6%A9%9F",
    },
}
LIST_CATEGORY_LABELS = {
    "watch_plan": "待看计划",
    "preference": "偏好声明",
    "theme": "主题整理",
}
LIST_CATEGORY_ORDER = {
    "watch_plan": 0,
    "preference": 1,
    "theme": 2,
}
LIST_CATEGORY_WEIGHTS = {
    "watch_plan": 0.90,
    "preference": 0.72,
    "theme": 0.55,
}
ORIGIN_LABEL_OVERRIDES = {
    "Hong Kong": "Hong Kong",
    "Taiwan": "Taiwan",
    "Macau": "Macau SAR",
}
ZH_ORIGIN_LABEL_OVERRIDES = {
    "中国香港": "Hong Kong",
    "香港": "Hong Kong",
    "中國香港": "Hong Kong",
    "台湾": "Taiwan",
    "台灣": "Taiwan",
    "中国台湾": "Taiwan",
    "中國台灣": "Taiwan",
    "澳门": "Macau SAR",
    "澳門": "Macau SAR",
    "中国澳门": "Macau SAR",
    "中國澳門": "Macau SAR",
}
NEWS_FEEDS = [
    {
        "label": "Variety",
        "url": "https://variety.com/v/film/feed/",
    },
    {
        "label": "Deadline",
        "url": "https://deadline.com/category/film/feed/",
    },
    {
        "label": "IndieWire",
        "url": "https://www.indiewire.com/c/film/feed/",
    },
    {
        "label": "The Hollywood Reporter",
        "url": "https://www.hollywoodreporter.com/c/movies/movie-news/feed/",
    },
]
STREAMING_PROVIDERS = [
    {
        "provider_id": "netflix_ca",
        "label": "Netflix",
        "source": "justwatch",
        "scope_label": "加拿大订阅目录",
        "package_code": "nfx",
        "provider_url": "https://www.justwatch.com/ca/provider/netflix/movies",
    },
    {
        "provider_id": "crave_ca",
        "label": "Crave",
        "source": "justwatch",
        "scope_label": "加拿大订阅目录",
        "package_code": "crv",
        "provider_url": "https://www.justwatch.com/ca/provider/crave/movies",
    },
    {
        "provider_id": "prime_ca",
        "label": "Amazon Prime",
        "source": "justwatch",
        "scope_label": "加拿大订阅目录",
        "package_code": "prv",
        "provider_url": "https://www.justwatch.com/ca/provider/amazon-prime-video/movies",
    },
    {
        "provider_id": "criterion_ca",
        "label": "Criterion",
        "source": "justwatch",
        "scope_label": "加拿大订阅目录",
        "package_code": "crc",
        "provider_url": "https://www.justwatch.com/ca/provider/criterion-channel/movies",
    },
    {
        "provider_id": "apple_tv_ca",
        "label": "Apple TV+",
        "source": "justwatch",
        "scope_label": "加拿大订阅目录",
        "package_code": "atp",
        "provider_url": "https://www.justwatch.com/ca/provider/apple-tv-plus/movies",
    },
    {
        "provider_id": "disney_plus_ca",
        "label": "Disney+",
        "source": "justwatch",
        "scope_label": "加拿大订阅目录",
        "package_code": "dnp",
        "provider_url": "https://www.justwatch.com/ca/provider/disney-plus/movies",
    },
    {
        "provider_id": "crunchyroll_ca",
        "label": "Crunchyroll",
        "source": "justwatch",
        "scope_label": "加拿大订阅目录",
        "package_code": "cru",
        "provider_url": "https://www.justwatch.com/ca/provider/crunchyroll/movies",
    },
]
_LETTERBOXD_THREAD_LOCAL = threading.local()
_DOUBAN_THREAD_LOCAL = threading.local()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a highly custom Letterboxd report")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument(
        "--streaming-lookups",
        type=int,
        default=300,
        help="Max number of uncached streaming titles to match against Letterboxd in this run",
    )
    parser.add_argument(
        "--streaming-workers",
        type=int,
        default=4,
        help="Concurrent Letterboxd lookups for the streaming section",
    )
    parser.add_argument(
        "--douban-lookups",
        type=int,
        default=40,
        help="Max number of uncached streaming titles to match against Douban in this run",
    )
    parser.add_argument(
        "--watched-douban-lookups",
        type=int,
        default=700,
        help="Max number of watched films to enrich with Douban ratings in this run",
    )
    parser.add_argument(
        "--streaming-catalog-timeout",
        type=int,
        default=120,
        help="Seconds to spend on live streaming catalog refresh before falling back to cached data",
    )
    parser.add_argument("--refresh-cache", action="store_true")
    return parser.parse_args()


def load_json_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_json_cache(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_match_title(value: Any) -> str:
    text = html.unescape(normalize_cell(value)).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def unique_preserve_order(values: list[Any]) -> list[Any]:
    seen: set[Any] = set()
    out: list[Any] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def normalize_string_list(values: Any) -> list[str]:
    cleaned: list[str] = []
    for value in ensure_list(values):
        if isinstance(value, dict):
            text = normalize_cell(
                value.get("label")
                or value.get("name")
                or value.get("translation")
                or value.get("code")
            )
        else:
            text = normalize_cell(value)
        if text:
            cleaned.append(text)
    return unique_preserve_order(cleaned)


def relabel_origin(value: Any) -> str:
    text = normalize_cell(value)
    if not text:
        return ""
    return ORIGIN_LABEL_OVERRIDES.get(text) or ZH_ORIGIN_LABEL_OVERRIDES.get(text) or text


def relabel_origin_list(values: Any) -> list[str]:
    return unique_preserve_order([label for label in (relabel_origin(value) for value in ensure_list(values)) if label])


def normalize_loose_title(value: Any) -> str:
    text = html.unescape(normalize_cell(value)).lower()
    text = re.sub(r"[‘’´`]", "'", text)
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_source_uri(value: Any) -> str:
    text = normalize_cell(value).strip()
    return text.rstrip("/")


def extract_letterboxd_json_ld(html_text: str) -> dict[str, Any]:
    scripts = re.findall(
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
        html_text,
        flags=re.I | re.S,
    )
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
            if item.get("aggregateRating") or item.get("@type") in {"Movie", "TVSeries", "CreativeWork", "Thing"}:
                return item
    return {}


def parse_iso_duration_minutes(value: Any) -> int | None:
    text = normalize_cell(value).upper()
    if not text:
        return None
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", text)
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    total = hours * 60 + minutes
    return total or None


def parse_letterboxd_page_metadata(html_text: str) -> dict[str, Any]:
    json_ld = extract_letterboxd_json_ld(html_text)
    aggregate = json_ld.get("aggregateRating") if isinstance(json_ld.get("aggregateRating"), dict) else {}
    rating_value = pd.to_numeric(aggregate.get("ratingValue"), errors="coerce")
    rating_count = pd.to_numeric(aggregate.get("ratingCount"), errors="coerce")
    directors = [
        normalize_cell(item.get("name"))
        for item in ensure_list(json_ld.get("director"))
        if isinstance(item, dict) and normalize_cell(item.get("name"))
    ]
    actors = [
        normalize_cell(item.get("name"))
        for item in ensure_list(json_ld.get("actors"))
        if isinstance(item, dict) and normalize_cell(item.get("name"))
    ]
    genres = [normalize_cell(item) for item in ensure_list(json_ld.get("genre")) if normalize_cell(item)]
    countries = [
        relabel_origin(item.get("name"))
        for item in ensure_list(json_ld.get("countryOfOrigin"))
        if isinstance(item, dict) and relabel_origin(item.get("name"))
    ]
    runtime_minutes = parse_iso_duration_minutes(json_ld.get("duration"))
    if runtime_minutes is None:
        runtime_match = re.search(r"(\d+)\s*(?:&nbsp;|\s)?mins", html_text)
        runtime_minutes = int(runtime_match.group(1)) if runtime_match else None
    imdb_match = re.search(r"imdb\.com/title/(tt\d+)", html_text)

    return {
        "metadata_title": normalize_cell(json_ld.get("name")),
        "letterboxd_rating": round(float(rating_value), 3) if pd.notna(rating_value) else None,
        "letterboxd_rating_count": int(rating_count) if pd.notna(rating_count) else None,
        "site_average_rating": round(float(rating_value), 3) if pd.notna(rating_value) else None,
        "site_rating_count": int(rating_count) if pd.notna(rating_count) else None,
        "runtime_minutes": runtime_minutes,
        "directors": unique_preserve_order(directors),
        "actors": unique_preserve_order(actors),
        "genres": unique_preserve_order(genres),
        "countries": unique_preserve_order(countries),
        "imdb_id": imdb_match.group(1) if imdb_match else None,
    }


def list_category_label(category: str) -> str:
    return LIST_CATEGORY_LABELS.get(category, category)


def justwatch_graphql(query: str) -> dict[str, Any]:
    request = Request(
        JUSTWATCH_GRAPHQL_URL,
        data=json.dumps({"query": query}).encode("utf-8"),
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )

    last_error: Exception | None = None
    for _attempt in range(3):
        try:
            with urlopen(request, timeout=40) as response:
                payload = json.loads(response.read().decode("utf-8", errors="ignore"))
            if payload.get("errors"):
                raise RuntimeError(str(payload["errors"]))
            return payload.get("data", {})
        except (HTTPError, URLError, TimeoutError, ValueError, RuntimeError) as exc:
            last_error = exc
            if _attempt < 2:
                sleep_seconds = 4.0 if isinstance(exc, HTTPError) and exc.code == 429 else 1.25 * (_attempt + 1)
                time.sleep(sleep_seconds)

    raise RuntimeError(f"Unable to fetch JustWatch catalog: {normalize_cell(last_error)}")


def fetch_justwatch_provider_catalog(provider: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    offset = 0
    page_size = 100
    total_count: int | None = None

    while total_count is None or offset < total_count:
        query = f"""
        {{
          popularTitles(
            country: CA,
            first: {page_size},
            offset: {offset},
            after: "",
            sortBy: IMDB_SCORE,
            sortRandomSeed: 0,
            filter: {{
              packages: ["{provider["package_code"]}"],
              objectTypes: [MOVIE],
              ageCertifications: [],
              excludeGenres: [],
              excludeIrrelevantTitles: false,
              excludeProductionCountries: [],
              genres: [],
              monetizationTypes: [],
              presentationTypes: [],
              productionCountries: [],
              searchQuery: "",
              subgenres: []
            }}
          ) {{
            totalCount
            pageInfo {{
              hasNextPage
            }}
            edges {{
              node {{
                objectType
                content(country: CA, language: "en") {{
                  title
                  fullPath
                  originalReleaseYear
                  runtime
                  genres {{
                    shortName
                    technicalName
                    translation(language: "en")
                  }}
                  scoring {{
                    imdbScore
                    imdbVotes
                    jwRating
                    tmdbScore
                  }}
                }}
              }}
            }}
          }}
        }}
        """
        payload = justwatch_graphql(query)
        connection = payload.get("popularTitles") or {}
        total_count = int(connection.get("totalCount") or 0)
        edges = ensure_list(connection.get("edges"))
        if not edges:
            break

        for edge in edges:
            node = edge.get("node") if isinstance(edge, dict) else None
            if not isinstance(node, dict) or node.get("objectType") != "MOVIE":
                continue
            content = node.get("content") if isinstance(node.get("content"), dict) else {}
            title = normalize_cell(content.get("title"))
            year = pd.to_numeric(content.get("originalReleaseYear"), errors="coerce")
            runtime_minutes = pd.to_numeric(content.get("runtime"), errors="coerce")
            if not title:
                continue
            if pd.notna(runtime_minutes) and float(runtime_minutes) < 45:
                continue
            item_key = film_key(title, year)
            if item_key in seen_keys:
                continue
            seen_keys.add(item_key)
            scoring = content.get("scoring") if isinstance(content.get("scoring"), dict) else {}
            genres = [
                {
                    "code": normalize_cell(genre.get("shortName")),
                    "slug": normalize_cell(genre.get("technicalName")),
                    "label": normalize_cell(genre.get("translation")),
                }
                for genre in ensure_list(content.get("genres"))
                if isinstance(genre, dict) and normalize_cell(genre.get("translation"))
            ]
            full_path = normalize_cell(content.get("fullPath"))
            rows.append(
                {
                    "film_key": item_key,
                    "name": title,
                    "year": int(year) if pd.notna(year) else None,
                    "runtime_minutes": pd.to_numeric(content.get("runtime"), errors="coerce"),
                    "genres": genres,
                    "provider_id": provider["provider_id"],
                    "provider_label": provider["label"],
                    "provider_url": provider["provider_url"],
                    "justwatch_path": full_path,
                    "justwatch_url": f"{JUSTWATCH_BASE_URL}{full_path}" if full_path else provider["provider_url"],
                    "imdb_score": pd.to_numeric(scoring.get("imdbScore"), errors="coerce"),
                    "imdb_votes": pd.to_numeric(scoring.get("imdbVotes"), errors="coerce"),
                    "jw_score": pd.to_numeric(scoring.get("jwRating"), errors="coerce"),
                    "tmdb_score": pd.to_numeric(scoring.get("tmdbScore"), errors="coerce"),
                }
            )

        if not connection.get("pageInfo", {}).get("hasNextPage"):
            break
        offset += page_size
        time.sleep(0.35)

    return rows


def fetch_json_resource(url: str, headers: dict[str, str] | None = None, timeout: int = 40) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
            ),
            **(headers or {}),
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="ignore"))


def build_streaming_catalog(output_dir: Path) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    provider_rows: list[dict[str, Any]] = []
    provider_warnings: list[dict[str, str]] = []
    for provider in STREAMING_PROVIDERS:
        source = normalize_cell(provider.get("source"))
        if source == "justwatch":
            provider_rows.extend(fetch_justwatch_provider_catalog(provider))
            continue

    catalog = pd.DataFrame(provider_rows)
    if catalog.empty:
        return catalog, provider_warnings
    catalog["year"] = pd.to_numeric(catalog["year"], errors="coerce")
    catalog["runtime_minutes"] = pd.to_numeric(catalog["runtime_minutes"], errors="coerce")
    catalog["imdb_score"] = pd.to_numeric(catalog["imdb_score"], errors="coerce")
    catalog["imdb_votes"] = pd.to_numeric(catalog["imdb_votes"], errors="coerce")
    catalog["jw_score"] = pd.to_numeric(catalog["jw_score"], errors="coerce")
    catalog["tmdb_score"] = pd.to_numeric(catalog["tmdb_score"], errors="coerce")
    return catalog, provider_warnings


def empty_streaming_section() -> dict[str, Any]:
    return {
        "summary": [],
        "rows": [],
        "genre_options": [],
        "provider_warnings": [],
        "stats": {
            "provider_titles": 0,
            "indexed_titles": 0,
            "scored_titles": 0,
            "watched_titles": 0,
            "unwatched_titles": 0,
            "exclusive_titles": 0,
            "new_lookups_requested": 0,
        },
        "top_unwatched": [],
    }


def run_with_timeout(seconds: int, callback: Any) -> Any:
    if seconds <= 0 or not hasattr(signal, "SIGALRM"):
        return callback()

    def handle_timeout(_signum: int, _frame: Any) -> None:
        raise TimeoutError(f"Timed out after {seconds} seconds")

    previous_handler = signal.signal(signal.SIGALRM, handle_timeout)
    signal.alarm(seconds)
    try:
        return callback()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)


def sanitize_cached_streaming_section(streaming: dict[str, Any]) -> dict[str, Any]:
    allowed_providers = {provider["label"] for provider in STREAMING_PROVIDERS}
    sanitized = json.loads(json.dumps(streaming))
    clean_rows: list[dict[str, Any]] = []
    for row in ensure_list(sanitized.get("rows")):
        if not isinstance(row, dict):
            continue
        providers = [provider for provider in ensure_list(row.get("providers")) if provider in allowed_providers]
        available_on_tracked = bool(row.get("available_on_tracked_platforms", True))
        if not providers and available_on_tracked:
            continue
        provider_links = [
            link
            for link in ensure_list(row.get("provider_links"))
            if isinstance(link, dict) and normalize_cell(link.get("provider")) in allowed_providers
        ]
        clean_row = {**row}
        for deprecated_key in ("bilibili_score", "bilibili_rating_count", "douban_rating_count"):
            clean_row.pop(deprecated_key, None)
        clean_row["providers"] = providers
        clean_row["provider_links"] = provider_links
        clean_row["provider_count"] = len(providers)
        clean_row["exclusive"] = len(providers) == 1
        clean_row["available_on_tracked_platforms"] = bool(providers) if available_on_tracked else False
        clean_row["availability_status"] = "available" if clean_row["available_on_tracked_platforms"] else "not_available"
        clean_rows.append(clean_row)

    summary_rows: list[dict[str, Any]] = []
    for provider in STREAMING_PROVIDERS:
        scoped = [row for row in clean_rows if provider["label"] in ensure_list(row.get("providers"))]
        scored = [row for row in scoped if pd.notna(pd.to_numeric(row.get("letterboxd_rating"), errors="coerce"))]
        douban = [row for row in scoped if pd.notna(pd.to_numeric(row.get("douban_rating"), errors="coerce"))]
        watched = [
            row
            for row in scoped
            if bool(row.get("watched")) and pd.notna(pd.to_numeric(row.get("user_rating"), errors="coerce"))
        ]
        summary_rows.append(
            {
                "provider": provider["label"],
                "scope_label": provider.get("scope_label"),
                "catalog_note": None,
                "available_titles": len(scoped),
                "indexed_titles": len(scored),
                "watched_titles": sum(1 for row in scoped if bool(row.get("watched"))),
                "unwatched_titles": sum(1 for row in scoped if not bool(row.get("watched"))),
                "exclusive_titles": sum(1 for row in scoped if bool(row.get("exclusive"))),
                "avg_letterboxd_rating": round(
                    float(np.mean([float(row["letterboxd_rating"]) for row in scored])),
                    3,
                )
                if scored
                else None,
                "avg_douban_rating": round(
                    float(np.mean([float(row["douban_rating"]) for row in douban])),
                    3,
                )
                if douban
                else None,
                "avg_user_rating": round(
                    float(np.mean([float(row["user_rating"]) for row in watched])),
                    3,
                )
                if watched
                else None,
            }
        )

    genre_counter: dict[str, dict[str, Any]] = {}
    for row in clean_rows:
        for genre in ensure_list(row.get("genres")):
            if not isinstance(genre, dict):
                continue
            label = normalize_cell(genre.get("label")) or normalize_cell(genre.get("code"))
            if not label:
                continue
            entry = genre_counter.setdefault(
                label,
                {
                    "code": normalize_cell(genre.get("code")) or label,
                    "slug": normalize_cell(genre.get("slug")) or slugify_identifier(label),
                    "label": label,
                    "titles": 0,
                    "watched_titles": 0,
                    "_keys": set(),
                    "_watched_keys": set(),
                },
            )
            key = normalize_cell(row.get("film_key")) or f"{row.get('name')}|{row.get('year')}"
            entry["_keys"].add(key)
            if bool(row.get("watched")):
                entry["_watched_keys"].add(key)

    genre_options = []
    for entry in genre_counter.values():
        entry["titles"] = len(entry.pop("_keys"))
        entry["watched_titles"] = len(entry.pop("_watched_keys"))
        genre_options.append(entry)

    scored_unwatched = [
        row
        for row in clean_rows
        if not bool(row.get("watched")) and pd.notna(pd.to_numeric(row.get("letterboxd_rating"), errors="coerce"))
    ]
    scored_unwatched = sorted(
        scored_unwatched,
        key=lambda row: (
            float(pd.to_numeric(row.get("letterboxd_rating"), errors="coerce")),
            float(pd.to_numeric(row.get("letterboxd_rating_count"), errors="coerce"))
            if pd.notna(pd.to_numeric(row.get("letterboxd_rating_count"), errors="coerce"))
            else 0.0,
        ),
        reverse=True,
    )

    sanitized["rows"] = clean_rows
    sanitized["summary"] = summary_rows
    sanitized["genre_options"] = sorted(genre_options, key=lambda row: (-row["titles"], row["label"]))
    sanitized["provider_warnings"] = []
    sanitized["top_unwatched"] = [
        {
            "rank": row.get("rank"),
            "name": row.get("name"),
            "year": row.get("year"),
            "providers": row.get("providers"),
            "letterboxd_rating": row.get("letterboxd_rating"),
        }
        for row in scored_unwatched[:20]
    ]
    available_rows = [row for row in clean_rows if bool(row.get("available_on_tracked_platforms", True))]
    scored_available_rows = [
        row
        for row in available_rows
        if pd.notna(pd.to_numeric(row.get("letterboxd_rating"), errors="coerce"))
    ]
    sanitized["stats"] = {
        **(sanitized.get("stats") if isinstance(sanitized.get("stats"), dict) else {}),
        "provider_titles": len(available_rows),
        "indexed_titles": len(scored_available_rows),
        "scored_titles": sum(
            1 for row in clean_rows if pd.notna(pd.to_numeric(row.get("letterboxd_rating"), errors="coerce"))
        ),
        "total_rows": len(clean_rows),
        "watched_titles": sum(1 for row in clean_rows if bool(row.get("watched"))),
        "unwatched_titles": sum(1 for row in clean_rows if not bool(row.get("watched"))),
        "exclusive_titles": sum(1 for row in clean_rows if bool(row.get("exclusive"))),
        "watched_not_available_titles": sum(
            1
            for row in clean_rows
            if bool(row.get("watched")) and not bool(row.get("available_on_tracked_platforms", True))
        ),
        "warning_count": 0,
    }
    return sanitized


def refresh_cached_streaming_douban_section(
    streaming: dict[str, Any],
    output_dir: Path,
    max_douban_lookups: int,
    workers: int,
    refresh_cache: bool,
) -> dict[str, Any]:
    sanitized = sanitize_cached_streaming_section(streaming)
    rows = [row for row in ensure_list(sanitized.get("rows")) if isinstance(row, dict)]
    if not rows or max_douban_lookups == 0:
        return sanitized

    targets = pd.DataFrame(
        [
            {
                "film_key": row.get("film_key"),
                "name": row.get("name"),
                "year": row.get("year"),
                "runtime_minutes": row.get("runtime_minutes"),
            }
            for row in rows
            if normalize_cell(row.get("film_key")) and normalize_cell(row.get("name"))
        ]
    )
    if targets.empty:
        return sanitized

    cache = update_streaming_douban_cache(
        targets,
        cache_path=output_dir / "streaming_letterboxd_cache.json",
        max_new_lookups=max_douban_lookups,
        workers=max(1, workers),
        refresh_cache=refresh_cache,
    )
    refreshed = json.loads(json.dumps(sanitized))
    for row in refreshed.get("rows", []):
        entry = cache.get(row.get("film_key"), {}) if isinstance(cache, dict) else {}
        if not isinstance(entry, dict):
            continue
        row["douban_rating"] = entry.get("douban_rating")
        row["douban_url"] = entry.get("douban_url")
    refreshed = sanitize_cached_streaming_section(refreshed)
    refreshed.setdefault("stats", {})["douban_fallback_enriched"] = True
    refreshed.setdefault("stats", {})["douban_lookups_requested"] = int(max_douban_lookups)
    return refreshed


def streaming_genre_objects_from_labels(values: Any) -> list[dict[str, str]]:
    return [
        {
            "code": label,
            "slug": slugify_identifier(label),
            "label": label,
        }
        for label in normalize_string_list(values)
    ]


def build_watched_only_streaming_rows(
    ratings_df: pd.DataFrame,
    represented_watched_keys: set[str],
    user_rating_lookup: dict[str, Any],
) -> list[dict[str, Any]]:
    watched_only_rows: list[dict[str, Any]] = []
    if ratings_df.empty:
        return watched_only_rows
    missing_watched_df = ratings_df[~ratings_df["film_key"].isin(represented_watched_keys)].copy()
    for _, watched_row in missing_watched_df.iterrows():
        watched_key = normalize_cell(watched_row.get("film_key"))
        if not watched_key:
            continue
        watched_year = pd.to_numeric(watched_row.get("Year"), errors="coerce")
        watched_genres = streaming_genre_objects_from_labels(watched_row.get("genres"))
        source_uri = normalize_source_uri(watched_row.get("canonical_url")) or normalize_source_uri(watched_row.get("Letterboxd URI"))
        watched_only_rows.append(
            {
                "film_key": watched_key,
                "matched_film_key": watched_key,
                "watched_film_key": watched_key,
                "name": normalize_cell(watched_row.get("Name")),
                "year": int(watched_year) if pd.notna(watched_year) else None,
                "runtime_minutes": pd.to_numeric(watched_row.get("runtime_minutes"), errors="coerce"),
                "genres": watched_genres,
                "genre_labels": [genre["label"] for genre in watched_genres],
                "genre_codes": [genre["code"] for genre in watched_genres],
                "providers": [],
                "provider_links": [],
                "provider_count": 0,
                "exclusive": False,
                "watched": True,
                "user_rating": user_rating_lookup.get(watched_key),
                "imdb_score": None,
                "imdb_votes": None,
                "jw_score": None,
                "tmdb_score": None,
                "lookup_priority": 0,
                "letterboxd_rating": pd.to_numeric(watched_row.get("site_average_rating"), errors="coerce"),
                "letterboxd_rating_count": pd.to_numeric(watched_row.get("site_rating_count"), errors="coerce"),
                "letterboxd_url": source_uri,
                "letterboxd_status": "watched_library",
                "match_name": normalize_cell(watched_row.get("Name")),
                "match_year": int(watched_year) if pd.notna(watched_year) else None,
                "site_average_rating": pd.to_numeric(watched_row.get("site_average_rating"), errors="coerce"),
                "site_rating_count": pd.to_numeric(watched_row.get("site_rating_count"), errors="coerce"),
                "directors": normalize_string_list(watched_row.get("directors")),
                "actors": normalize_string_list(watched_row.get("actors")),
                "countries": normalize_string_list(watched_row.get("countries")),
                "metadata_title": normalize_cell(watched_row.get("Name")),
                "douban_rating": pd.to_numeric(watched_row.get("douban_rating"), errors="coerce"),
                "douban_rating_count": None,
                "douban_url": normalize_source_uri(watched_row.get("douban_url")),
                "source_uri": source_uri,
                "decade_label": normalize_cell(watched_row.get("decade_label")),
                "runtime_bucket": normalize_cell(watched_row.get("runtime_bucket")),
                "available_on_tracked_platforms": False,
                "availability_status": "not_available",
            }
        )
    return watched_only_rows


def refresh_cached_streaming_watch_state(
    streaming: dict[str, Any],
    ratings_df: pd.DataFrame,
    output_dir: Path,
) -> dict[str, Any]:
    sanitized = sanitize_cached_streaming_section(streaming)
    rows = [row for row in ensure_list(sanitized.get("rows")) if isinstance(row, dict)]
    if not rows or ratings_df.empty:
        return sanitized

    watched_keys = set(ratings_df["film_key"])
    user_rating_lookup = (
        ratings_df[["film_key", "user_rating"]]
        .drop_duplicates(subset=["film_key"])
        .set_index("film_key")["user_rating"]
        .to_dict()
    )
    lookup_cache = load_json_cache(output_dir / "streaming_letterboxd_cache.json")

    refreshed = json.loads(json.dumps(sanitized))
    for row in refreshed.get("rows", []):
        original_key = normalize_cell(row.get("film_key"))
        cache_entry = lookup_cache.get(original_key, {}) if isinstance(lookup_cache, dict) else {}
        cached_match_name = normalize_cell(cache_entry.get("match_name")) if isinstance(cache_entry, dict) else ""
        match_name = normalize_cell(row.get("match_name")) or cached_match_name
        match_year = row.get("match_year")
        if (pd.isna(pd.to_numeric(match_year, errors="coerce")) and isinstance(cache_entry, dict)):
            match_year = cache_entry.get("match_year")
        matched_key = normalize_cell(row.get("matched_film_key"))
        if not matched_key and match_name:
            matched_key = film_key(match_name, match_year if pd.notna(pd.to_numeric(match_year, errors="coerce")) else row.get("year"))

        watched_key = original_key if original_key in watched_keys else None
        if watched_key is None and matched_key in watched_keys:
            watched_key = matched_key
        row["matched_film_key"] = matched_key or original_key
        row["watched_film_key"] = watched_key
        row["watched"] = watched_key is not None
        row["user_rating"] = user_rating_lookup.get(watched_key) if watched_key else None

    represented_watched_keys = {
        normalize_cell(row.get("watched_film_key"))
        for row in refreshed.get("rows", [])
        if isinstance(row, dict) and normalize_cell(row.get("watched_film_key"))
    }
    watched_only_rows = build_watched_only_streaming_rows(
        ratings_df,
        represented_watched_keys,
        user_rating_lookup,
    )
    if watched_only_rows:
        refreshed.setdefault("rows", []).extend(watched_only_rows)
    refreshed = sanitize_cached_streaming_section(refreshed)
    refreshed.setdefault("stats", {})["watched_library_titles"] = int(len(ratings_df))
    return refreshed


def load_cached_streaming_section(output_dir: Path) -> dict[str, Any] | None:
    candidate_paths = [
        output_dir / "custom-report-data.json",
        output_dir / "share-site" / "custom-report-data.json",
        Path.cwd() / "custom-report-data.json",
        Path.cwd() / "share-site" / "custom-report-data.json",
    ]
    seen_paths: set[Path] = set()
    for candidate in candidate_paths:
        path = candidate.resolve()
        if path in seen_paths or not path.exists():
            continue
        seen_paths.add(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        streaming = payload.get("streaming")
        if not isinstance(streaming, dict):
            continue
        if "rows" not in streaming or "stats" not in streaming:
            continue
        return sanitize_cached_streaming_section(streaming)
    return None


def should_fallback_to_cached_streaming(exc: Exception) -> bool:
    message = normalize_cell(exc).lower()
    return any(
        needle in message
        for needle in (
            "unable to fetch justwatch catalog",
            "http error 429",
            "too many requests",
            "timed out",
            "justwatch",
        )
    )


def get_letterboxd_session() -> Any:
    if curl_requests is None:
        raise RuntimeError(
            "Missing dependency: curl_cffi. Run scripts/generate_custom_letterboxd_report.sh "
            "so the local dependency can be installed automatically."
        )
    session = getattr(_LETTERBOXD_THREAD_LOCAL, "session", None)
    if session is None:
        session = curl_requests.Session(impersonate=LETTERBOXD_IMPERSONATE)
        _LETTERBOXD_THREAD_LOCAL.session = session
    return session


def fetch_letterboxd_json(url: str) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = get_letterboxd_session().get(url, timeout=30)
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            raise ValueError("Unexpected non-dict JSON payload")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(0.75 * (attempt + 1))
    raise RuntimeError(f"Letterboxd JSON request failed for {url}: {normalize_cell(last_error)}")


def fetch_letterboxd_text(url: str) -> str:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = get_letterboxd_session().get(url, timeout=30)
            text = response.text
            if text:
                return text
            raise ValueError("Empty text response")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(0.75 * (attempt + 1))
    raise RuntimeError(f"Letterboxd text request failed for {url}: {normalize_cell(last_error)}")


def parse_rating_histogram(html_text: str) -> tuple[float | None, int | None]:
    counts = [
        int(value.replace(",", ""))
        for value in re.findall(r'title="([0-9,]+)[^"]*?ratings', html_text)
    ]
    if len(counts) < len(RATING_BUCKET_VALUES):
        return None, None
    counts = counts[: len(RATING_BUCKET_VALUES)]
    rating_count = int(sum(counts))
    if rating_count == 0:
        return None, 0
    average = sum(bucket * count for bucket, count in zip(RATING_BUCKET_VALUES, counts)) / rating_count
    return round(float(average), 3), rating_count


def choose_letterboxd_match(
    candidates: list[dict[str, Any]],
    title: str,
    year: Any,
    runtime_minutes: Any,
) -> dict[str, Any] | None:
    target_title = normalize_match_title(title)
    target_year = pd.to_numeric(year, errors="coerce")
    target_runtime = pd.to_numeric(runtime_minutes, errors="coerce")
    best_candidate: dict[str, Any] | None = None
    best_score = -999.0

    for candidate in candidates:
        candidate_title = normalize_match_title(candidate.get("name"))
        candidate_original = normalize_match_title(candidate.get("originalName"))
        candidate_year = pd.to_numeric(candidate.get("releaseYear"), errors="coerce")
        candidate_runtime = pd.to_numeric(candidate.get("runTime"), errors="coerce")

        similarity = max(
            SequenceMatcher(None, target_title, candidate_title).ratio(),
            SequenceMatcher(None, target_title, candidate_original).ratio() if candidate_original else 0.0,
        )
        score = similarity * 100
        if target_title == candidate_title or (candidate_original and target_title == candidate_original):
            score += 35
        if pd.notna(target_year) and pd.notna(candidate_year) and int(target_year) == int(candidate_year):
            score += 55
        elif pd.notna(target_year) and pd.notna(candidate_year) and abs(int(target_year) - int(candidate_year)) == 1:
            score += 12
        if pd.notna(target_runtime) and pd.notna(candidate_runtime):
            runtime_gap = abs(float(target_runtime) - float(candidate_runtime))
            if runtime_gap <= 5:
                score += 8
            elif runtime_gap >= 25:
                score -= 10

        if score > best_score:
            best_score = score
            best_candidate = candidate

    if not best_candidate or best_score < 90:
        return None
    return best_candidate


def is_valid_streaming_cache_entry(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    version = pd.to_numeric(entry.get("cache_version"), errors="coerce")
    return int(version) >= STREAMING_CACHE_VERSION if pd.notna(version) else False


def has_streaming_douban_entry(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    status = normalize_cell(entry.get("douban_status"))
    rating = pd.to_numeric(entry.get("douban_rating"), errors="coerce")
    if status in {"matched", "historical_removed"}:
        return pd.notna(rating) and float(rating) > 0
    version = pd.to_numeric(entry.get("douban_cache_version"), errors="coerce")
    if pd.isna(version) or int(version) < DOUBAN_CACHE_VERSION:
        return False
    return status in {"matched", "not_found"}


def fetch_douban_suggestions(query: str) -> list[dict[str, Any]]:
    text = normalize_cell(query)
    if not text:
        return []
    payload = fetch_json_resource(
        f"{DOUBAN_SUGGEST_URL}?q={quote_plus(text)}",
        headers={"Referer": "https://movie.douban.com/"},
        timeout=10,
    )
    return ensure_list(payload)


def fetch_douban_subject_search(query: str) -> list[dict[str, Any]]:
    text = normalize_cell(query)
    if not text:
        return []
    url = f"{DOUBAN_SUBJECT_SEARCH_URL}?search_text={quote_plus(text)}&cat=1002"
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
            ),
            "Referer": "https://movie.douban.com/",
        },
    )
    with urlopen(request, timeout=10) as response:
        html_text = response.read().decode("utf-8", errors="replace")
    if (
        "sec.douban.com" in html_text
        or "访问太频繁" in html_text
        or "异常请求" in html_text
        or "检测到有异常" in html_text
    ):
        raise RuntimeError("Douban search appears rate-limited")
    match = re.search(r"window\.__DATA__\s*=\s*(\{.*?\});", html_text, flags=re.S)
    if not match:
        raise RuntimeError("Douban search did not return structured data")
    payload = json.loads(match.group(1))
    error_info = normalize_cell(payload.get("error_info")) if isinstance(payload, dict) else ""
    if error_info:
        raise RuntimeError(f"Douban search error: {error_info}")
    return ensure_list(payload.get("items"))


def parse_douban_search_year(item: dict[str, Any]) -> int | None:
    for value in [item.get("year"), item.get("title"), item.get("abstract")]:
        match = re.search(r"(19|20)\d{2}", normalize_cell(value))
        if match:
            return int(match.group(0))
    return None


def normalize_douban_search_item(item: dict[str, Any]) -> dict[str, Any]:
    subject_id = normalize_cell(item.get("id"))
    title = normalize_cell(item.get("title"))
    title_without_year = re.sub(r"\s*[\(（](19|20)\d{2}[\)）]\s*$", "", title).strip()
    abstract = normalize_cell(item.get("abstract"))
    aliases = [title_without_year, title]
    if abstract:
        aliases.extend(part.strip() for part in abstract.split("/") if part.strip())
    rating = item.get("rating") if isinstance(item.get("rating"), dict) else {}
    return {
        "id": subject_id,
        "title": title_without_year or title,
        "sub_title": abstract,
        "aliases": unique_preserve_order([normalize_cell(value) for value in aliases if normalize_cell(value)]),
        "year": parse_douban_search_year(item),
        "url": normalize_source_uri(item.get("url")) or f"https://movie.douban.com/subject/{subject_id}/",
        "rating_value": pd.to_numeric(rating.get("value"), errors="coerce"),
        "rating_count": pd.to_numeric(rating.get("count"), errors="coerce"),
    }


def choose_douban_match(
    candidates: list[dict[str, Any]],
    title_candidates: list[str],
    year: Any,
) -> dict[str, Any] | None:
    target_year = pd.to_numeric(year, errors="coerce")
    normalized_targets = [normalize_loose_title(value) for value in title_candidates if normalize_loose_title(value)]
    if not normalized_targets:
        return None

    best_candidate: dict[str, Any] | None = None
    best_score = -999.0
    for raw_candidate in candidates:
        candidate = normalize_douban_search_item(raw_candidate) if "aliases" not in raw_candidate else raw_candidate
        candidate_titles = [normalize_loose_title(value) for value in ensure_list(candidate.get("aliases"))]
        if not candidate_titles:
            candidate_titles = [
                normalize_loose_title(candidate.get("title")),
                normalize_loose_title(candidate.get("sub_title")),
            ]
        candidate_titles = [value for value in candidate_titles if value]
        if not candidate_titles:
            continue
        candidate_year = pd.to_numeric(candidate.get("year"), errors="coerce")
        similarity = max(
            SequenceMatcher(None, target, candidate_title).ratio()
            for target in normalized_targets
            for candidate_title in candidate_titles
        )
        score = similarity * 100
        if any(target == candidate_title for target in normalized_targets for candidate_title in candidate_titles):
            score += 30
        if pd.notna(target_year) and pd.notna(candidate_year) and int(target_year) == int(candidate_year):
            score += 35
        elif pd.notna(target_year) and pd.notna(candidate_year) and abs(int(target_year) - int(candidate_year)) == 1:
            score += 8
        elif pd.notna(target_year) and pd.notna(candidate_year):
            score -= 80

        if score > best_score:
            best_score = score
            best_candidate = candidate

    if not best_candidate or best_score < 82:
        return None
    return best_candidate


def fetch_douban_detail(subject_id: str) -> dict[str, Any]:
    payload = fetch_json_resource(
        f"{DOUBAN_API_BASE_URL}/movie/{subject_id}?ck=&for_mobile=1",
        headers={"Referer": "https://m.douban.com/"},
        timeout=10,
    )
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected Douban payload for {subject_id}")
    return payload


def douban_web_headers(referer: str = "https://movie.douban.com/") -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "Referer": referer,
    }


def get_douban_opener() -> Any:
    opener = getattr(_DOUBAN_THREAD_LOCAL, "opener", None)
    if opener is None:
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        _DOUBAN_THREAD_LOCAL.opener = opener
    return opener


def extract_html_input_value(html_text: str, name: str) -> str:
    input_match = re.search(
        rf"<input\b[^>]*(?:name|id)=[\"']{re.escape(name)}[\"'][^>]*>",
        html_text,
        flags=re.IGNORECASE,
    )
    if not input_match:
        input_match = re.search(
            rf"<input\b[^>]*value=[\"'][^\"']*[\"'][^>]*(?:name|id)=[\"']{re.escape(name)}[\"'][^>]*>",
            html_text,
            flags=re.IGNORECASE,
        )
    if not input_match:
        return ""
    value_match = re.search(r"value=[\"']([^\"']*)[\"']", input_match.group(0), flags=re.IGNORECASE)
    return html.unescape(value_match.group(1)) if value_match else ""


def solve_douban_challenge(html_text: str) -> dict[str, str]:
    token = extract_html_input_value(html_text, "tok")
    challenge = extract_html_input_value(html_text, "cha")
    redirect = extract_html_input_value(html_text, "red")
    if not token or not challenge or not redirect:
        raise RuntimeError("Douban challenge page did not include expected fields")

    difficulty_match = re.search(r"process\(\s*cha\s*,\s*(\d+)\s*\)", html_text)
    difficulty = int(difficulty_match.group(1)) if difficulty_match else 4
    prefix = "0" * difficulty
    nonce = 0
    while nonce < 2_000_000:
        nonce += 1
        digest = hashlib.sha512(f"{challenge}{nonce}".encode("utf-8")).hexdigest()
        if digest.startswith(prefix):
            return {"tok": token, "cha": challenge, "sol": str(nonce), "red": redirect}
    raise RuntimeError("Douban challenge solver exceeded nonce limit")


def fetch_douban_subject_html(subject_id: str) -> str:
    opener = get_douban_opener()
    subject_url = f"https://movie.douban.com/subject/{subject_id}/"
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = Request(subject_url, headers=douban_web_headers())
            with opener.open(request, timeout=20) as response:
                html_text = response.read().decode("utf-8", errors="replace")
                response_url = normalize_cell(response.geturl())
            if "sec.douban.com" in response_url or "id=\"sec\"" in html_text or "name=\"cha\"" in html_text:
                challenge_payload = solve_douban_challenge(html_text)
                challenge_request = Request(
                    urljoin(response_url or "https://sec.douban.com/", "/c"),
                    data=urlencode(challenge_payload).encode("utf-8"),
                    headers={
                        **douban_web_headers(response_url or subject_url),
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    method="POST",
                )
                with opener.open(challenge_request, timeout=25) as challenge_response:
                    html_text = challenge_response.read().decode("utf-8", errors="replace")
            if "rating_num" in html_text or "v:average" in html_text:
                return html_text
            last_error = RuntimeError("Douban subject page did not expose rating markup")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(0.7 * (attempt + 1))
    raise RuntimeError(f"Douban web detail unavailable for {subject_id}: {last_error}")


def fetch_douban_web_detail(subject_id: str) -> dict[str, Any]:
    html_text = fetch_douban_subject_html(subject_id)
    title_match = (
        re.search(r"<span[^>]+property=[\"']v:itemreviewed[\"'][^>]*>(.*?)</span>", html_text, re.DOTALL)
        or re.search(r"<meta[^>]+property=[\"']og:title[\"'][^>]+content=[\"']([^\"']+)[\"']", html_text, re.DOTALL)
    )
    year_match = re.search(r"<span[^>]+class=[\"']year[\"'][^>]*>\((\d{4})\)</span>", html_text)
    average_match = (
        re.search(r"property=[\"']v:average[\"'][^>]*>\s*([0-9.]+)\s*<", html_text)
        or re.search(r"class=[\"'][^\"']*rating_num[^\"']*[\"'][^>]*>\s*([0-9.]+)\s*<", html_text)
    )
    votes_match = (
        re.search(r"property=[\"']v:votes[\"'][^>]*>\s*([0-9,]+)\s*<", html_text)
        or re.search(r"([0-9,]+)\s*人评价", html_text)
    )
    rating_value = coerce_douban_rating(average_match.group(1) if average_match else None)
    if rating_value is None:
        raise RuntimeError(f"Douban web page did not expose a numeric rating for {subject_id}")
    rating_count = pd.to_numeric(votes_match.group(1).replace(",", ""), errors="coerce") if votes_match else None
    title = clean_html_excerpt(title_match.group(1)) if title_match else ""
    return {
        "title": title,
        "year": year_match.group(1) if year_match else "",
        "rating": {
            "value": rating_value,
            "count": int(rating_count) if rating_count is not None and pd.notna(rating_count) else None,
        },
        "_source": "douban_web",
    }


def fetch_douban_detail_resilient(subject_id: str) -> dict[str, Any]:
    try:
        detail = fetch_douban_detail(subject_id)
        detail["_source"] = "douban_api"
        return detail
    except Exception:
        return fetch_douban_web_detail(subject_id)


def fetch_wikidata_douban_id(imdb_id: str) -> str | None:
    imdb = normalize_cell(imdb_id)
    if not re.fullmatch(r"tt\d+", imdb):
        return None
    query = (
        "SELECT ?douban WHERE { "
        f'?item wdt:P345 "{imdb}". '
        "OPTIONAL { ?item wdt:P4529 ?douban. } "
        "} LIMIT 1"
    )
    request = Request(
        f"{WIKIDATA_SPARQL_URL}?{urlencode({'query': query, 'format': 'json'})}",
        headers={
            "Accept": "application/sparql-results+json",
            "User-Agent": "Letterboxd_Data_Update/1.0 (https://github.com/GavinLegend/Letterboxd_Data_Update)",
        },
    )
    with urlopen(request, timeout=12) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    for binding in ensure_list(payload.get("results", {}).get("bindings")):
        douban = binding.get("douban") if isinstance(binding, dict) else None
        value = normalize_cell(douban.get("value")) if isinstance(douban, dict) else ""
        if value:
            return value
    return None


def fetch_wikidata_douban_id_map(imdb_ids: list[str], chunk_size: int = 50) -> dict[str, str]:
    normalized = [
        imdb
        for imdb in unique_preserve_order([normalize_cell(value) for value in imdb_ids])
        if re.fullmatch(r"tt\d+", imdb)
    ]
    mapping: dict[str, str] = {}
    for start in range(0, len(normalized), chunk_size):
        chunk = normalized[start : start + chunk_size]
        values = " ".join(f'"{imdb}"' for imdb in chunk)
        query = (
            "SELECT ?imdb ?douban WHERE { "
            f"VALUES ?imdb {{ {values} }} "
            "?item wdt:P345 ?imdb; wdt:P4529 ?douban. "
            "}"
        )
        request = Request(
            f"{WIKIDATA_SPARQL_URL}?{urlencode({'query': query, 'format': 'json'})}",
            headers={
                "Accept": "application/sparql-results+json",
                "User-Agent": "Letterboxd_Data_Update/1.0 (https://github.com/GavinLegend/Letterboxd_Data_Update)",
            },
        )
        payload: dict[str, Any] = {}
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urlopen(request, timeout=25) as response:
                    payload = json.loads(response.read().decode("utf-8", errors="replace"))
                break
            except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                last_error = exc
                time.sleep(1.5 * (attempt + 1))
        if not payload:
            print(f"Warning: Wikidata Douban ID batch skipped: {last_error}", file=sys.stderr)
            continue
        for binding in ensure_list(payload.get("results", {}).get("bindings")):
            imdb = binding.get("imdb") if isinstance(binding, dict) else None
            douban = binding.get("douban") if isinstance(binding, dict) else None
            imdb_value = normalize_cell(imdb.get("value")) if isinstance(imdb, dict) else ""
            douban_value = normalize_cell(douban.get("value")) if isinstance(douban, dict) else ""
            if imdb_value and douban_value:
                mapping[imdb_value] = douban_value
    return mapping


def coerce_douban_rating(value: Any) -> float | None:
    rating = pd.to_numeric(value, errors="coerce")
    if pd.isna(rating) or float(rating) <= 0:
        return None
    return float(rating)


def normalize_douban_dataset_item(item: dict[str, Any]) -> dict[str, Any] | None:
    subject_id = normalize_cell(item.get("_id") or item.get("id"))
    rating = item.get("rating") if isinstance(item.get("rating"), dict) else {}
    rating_value = coerce_douban_rating(rating.get("average") or rating.get("value"))
    if not subject_id or rating_value is None:
        return None
    rating_count = pd.to_numeric(rating.get("rating_people") or rating.get("count"), errors="coerce")
    title = normalize_cell(item.get("title"))
    year = normalize_cell(item.get("year"))
    return {
        "douban_id": subject_id,
        "douban_title": title,
        "douban_url": f"https://movie.douban.com/subject/{subject_id}/",
        "douban_rating": rating_value,
        "douban_rating_count": int(rating_count) if pd.notna(rating_count) else None,
        "douban_year": year,
        "imdb_id": normalize_cell(item.get("imdb")),
        "source": "public_dataset",
    }


def load_public_douban_dataset_index(output_dir: Path) -> dict[str, dict[str, dict[str, Any]]]:
    cache_path = output_dir / "douban_public_dataset_index.json"
    cached = load_json_cache(cache_path)
    if cached.get("cache_version") == 1 and isinstance(cached.get("by_imdb"), dict) and isinstance(cached.get("by_douban_id"), dict):
        return {
            "by_imdb": cached.get("by_imdb", {}),
            "by_douban_id": cached.get("by_douban_id", {}),
        }

    by_imdb: dict[str, dict[str, Any]] = {}
    by_douban_id: dict[str, dict[str, Any]] = {}
    request = Request(
        DOUBAN_PUBLIC_DATASET_URL,
        headers={
            "User-Agent": "Letterboxd_Data_Update/1.0 (https://github.com/GavinLegend/Letterboxd_Data_Update)",
            "Accept": "text/plain, application/json",
        },
    )
    with urlopen(request, timeout=90) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            entry = normalize_douban_dataset_item(item)
            if not entry:
                continue
            by_douban_id[entry["douban_id"]] = entry
            imdb_id = normalize_cell(entry.get("imdb_id"))
            if re.fullmatch(r"tt\d+", imdb_id):
                by_imdb[imdb_id] = entry

    write_json_cache(
        cache_path,
        {
            "cache_version": 1,
            "source_url": DOUBAN_PUBLIC_DATASET_URL,
            "indexed_at": pd.Timestamp.now("UTC").isoformat(),
            "by_imdb": by_imdb,
            "by_douban_id": by_douban_id,
        },
    )
    return {"by_imdb": by_imdb, "by_douban_id": by_douban_id}


def normalize_ptgen_map_item(item: dict[str, Any]) -> dict[str, Any] | None:
    subject_id = normalize_cell(item.get("dbid"))
    imdb_id = normalize_cell(item.get("imdbid"))
    if not subject_id or not imdb_id:
        return None
    return {
        "douban_id": subject_id,
        "douban_title": normalize_cell(item.get("name")),
        "douban_url": f"https://movie.douban.com/subject/{subject_id}/",
        "douban_year": normalize_cell(item.get("year")),
        "imdb_id": imdb_id,
        "source": "ptgen_imdb_map",
    }


def load_ptgen_douban_imdb_index(output_dir: Path) -> dict[str, dict[str, dict[str, Any]]]:
    cache_path = output_dir / "ptgen_douban_imdb_index.json"
    cached = load_json_cache(cache_path)
    if cached.get("cache_version") == 1 and isinstance(cached.get("by_imdb"), dict) and isinstance(cached.get("by_douban_id"), dict):
        return {
            "by_imdb": cached.get("by_imdb", {}),
            "by_douban_id": cached.get("by_douban_id", {}),
        }

    by_imdb: dict[str, dict[str, Any]] = {}
    by_douban_id: dict[str, dict[str, Any]] = {}
    payload = fetch_json_resource(
        PTGEN_DOUBAN_IMDB_MAP_URL,
        headers={
            "User-Agent": "Letterboxd_Data_Update/1.0 (https://github.com/GavinLegend/Letterboxd_Data_Update)",
            "Accept": "application/json",
        },
        timeout=90,
    )
    for raw_item in ensure_list(payload):
        if not isinstance(raw_item, dict):
            continue
        entry = normalize_ptgen_map_item(raw_item)
        if not entry:
            continue
        by_douban_id[entry["douban_id"]] = entry
        if re.fullmatch(r"tt\d+", entry["imdb_id"]):
            by_imdb[entry["imdb_id"]] = entry

    write_json_cache(
        cache_path,
        {
            "cache_version": 1,
            "source_url": PTGEN_DOUBAN_IMDB_MAP_URL,
            "indexed_at": pd.Timestamp.now("UTC").isoformat(),
            "by_imdb": by_imdb,
            "by_douban_id": by_douban_id,
        },
    )
    return {"by_imdb": by_imdb, "by_douban_id": by_douban_id}


def fetch_ptgen_douban_detail(output_dir: Path, subject_id: str) -> dict[str, Any]:
    detail_cache_path = output_dir / "ptgen_douban_detail_cache.json"
    detail_cache = load_json_cache(detail_cache_path)
    cached = detail_cache.get(subject_id) if isinstance(detail_cache.get(subject_id), dict) else None
    if cached and cached.get("cache_version") == 1:
        return cached.get("payload") if isinstance(cached.get("payload"), dict) else {}

    payload = fetch_json_resource(
        PTGEN_DOUBAN_DETAIL_URL.format(subject_id=quote_plus(subject_id)),
        headers={
            "User-Agent": "Letterboxd_Data_Update/1.0 (https://github.com/GavinLegend/Letterboxd_Data_Update)",
            "Accept": "application/json",
        },
        timeout=30,
    )
    if not isinstance(payload, dict):
        payload = {}
    detail_cache[subject_id] = {
        "cache_version": 1,
        "source_url": PTGEN_DOUBAN_DETAIL_URL.format(subject_id=subject_id),
        "updated_at": pd.Timestamp.now("UTC").isoformat(),
        "payload": payload,
    }
    write_json_cache(detail_cache_path, detail_cache)
    return payload


def build_douban_result_from_ptgen_entry(
    existing: dict[str, Any],
    film_key_value: str,
    entry: dict[str, Any],
    output_dir: Path,
    match_key: str,
) -> dict[str, Any]:
    subject_id = normalize_cell(entry.get("douban_id"))
    if not subject_id:
        raise RuntimeError("PtGen entry did not include a Douban subject ID")
    detail = fetch_ptgen_douban_detail(output_dir, subject_id)
    rating_value = coerce_douban_rating(detail.get("douban_rating_average"))
    rating_count = pd.to_numeric(detail.get("douban_votes"), errors="coerce")
    title = (
        normalize_cell(detail.get("chinese_title"))
        or normalize_cell(detail.get("this_title"))
        or normalize_cell(entry.get("douban_title"))
    )
    foreign_title = normalize_cell(detail.get("foreign_title"))
    if foreign_title and foreign_title != title:
        title = f"{title} {foreign_title}".strip()
    if rating_value is None:
        return {
            **existing,
            "film_key": film_key_value,
            "douban_status": "no_rating",
            "douban_cache_version": WATCHED_DOUBAN_CACHE_VERSION,
            "douban_id": subject_id,
            "douban_title": title,
            "douban_url": normalize_source_uri(detail.get("douban_link")) or f"https://movie.douban.com/subject/{subject_id}/",
            "douban_rating": None,
            "douban_rating_count": None,
            "douban_year": normalize_cell(detail.get("year")) or normalize_cell(entry.get("douban_year")),
            "douban_match_key": match_key,
            "douban_source": "ptgen_static",
            "douban_error": "PtGen/Douban detail exists but has no current numeric rating",
            "douban_updated_at": pd.Timestamp.now("UTC").isoformat(),
        }
    return {
        **existing,
        "film_key": film_key_value,
        "douban_status": "matched",
        "douban_cache_version": WATCHED_DOUBAN_CACHE_VERSION,
        "douban_id": subject_id,
        "douban_title": title,
        "douban_url": normalize_source_uri(detail.get("douban_link")) or f"https://movie.douban.com/subject/{subject_id}/",
        "douban_rating": rating_value,
        "douban_rating_count": int(rating_count) if pd.notna(rating_count) else None,
        "douban_year": normalize_cell(detail.get("year")) or normalize_cell(entry.get("douban_year")),
        "douban_match_key": match_key,
        "douban_source": "ptgen_static",
        "douban_updated_at": pd.Timestamp.now("UTC").isoformat(),
    }


def build_douban_result_from_historical_override(
    existing: dict[str, Any],
    film_key_value: str,
    entry: dict[str, Any],
) -> dict[str, Any]:
    subject_id = normalize_cell(entry.get("douban_id"))
    return {
        **existing,
        "film_key": film_key_value,
        "douban_status": "historical_removed",
        "douban_cache_version": WATCHED_DOUBAN_CACHE_VERSION,
        "douban_id": subject_id,
        "douban_title": normalize_cell(entry.get("douban_title")),
        "douban_url": f"https://movie.douban.com/subject/{subject_id}/" if subject_id else None,
        "douban_rating": coerce_douban_rating(entry.get("douban_rating")),
        "douban_rating_count": int(entry["douban_rating_count"]) if pd.notna(pd.to_numeric(entry.get("douban_rating_count"), errors="coerce")) else None,
        "douban_year": normalize_cell(entry.get("douban_year")),
        "douban_match_key": f"{film_key_value}:historical_removed",
        "douban_source": "historical_public_reference",
        "douban_source_url": normalize_source_uri(entry.get("source_url")),
        "douban_updated_at": pd.Timestamp.now("UTC").isoformat(),
    }


def build_douban_result_from_public_entry(
    existing: dict[str, Any],
    film_key_value: str,
    entry: dict[str, Any],
    match_key: str,
) -> dict[str, Any]:
    return {
        **existing,
        "film_key": film_key_value,
        "douban_status": "matched",
        "douban_cache_version": WATCHED_DOUBAN_CACHE_VERSION,
        "douban_id": normalize_cell(entry.get("douban_id")),
        "douban_title": normalize_cell(entry.get("douban_title")),
        "douban_url": normalize_source_uri(entry.get("douban_url")),
        "douban_rating": coerce_douban_rating(entry.get("douban_rating")),
        "douban_rating_count": entry.get("douban_rating_count"),
        "douban_year": normalize_cell(entry.get("douban_year")),
        "douban_match_key": match_key,
        "douban_source": normalize_cell(entry.get("source")) or "public_dataset",
        "douban_updated_at": pd.Timestamp.now("UTC").isoformat(),
    }


def seed_watched_douban_cache_from_published_report(
    output_dir: Path,
    cache: dict[str, Any],
) -> dict[str, Any]:
    candidate_paths = [
        output_dir / "custom-report-data.json",
        output_dir / "share-site" / "custom-report-data.json",
        Path.cwd() / "custom-report-data.json",
    ]
    seeded = dict(cache)
    for candidate in candidate_paths:
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = ensure_list((payload.get("watched_douban") or {}).get("rows"))
        for row in rows:
            if not isinstance(row, dict):
                continue
            film_key_value = normalize_cell(row.get("film_key"))
            rating_value = coerce_douban_rating(row.get("douban_rating"))
            if not film_key_value or rating_value is None:
                continue
            existing = seeded.get(film_key_value) if isinstance(seeded.get(film_key_value), dict) else {}
            if has_watched_douban_entry(existing):
                continue
            seeded[film_key_value] = {
                **existing,
                "film_key": film_key_value,
                "douban_status": "matched",
                "douban_cache_version": WATCHED_DOUBAN_CACHE_VERSION,
                "douban_title": normalize_cell(row.get("douban_title")),
                "douban_url": normalize_source_uri(row.get("douban_url")),
                "douban_rating": rating_value,
                "douban_year": normalize_cell(row.get("year")),
                "douban_match_key": "published_report_seed",
                "douban_source": "published_report_seed",
                "douban_updated_at": pd.Timestamp.now("UTC").isoformat(),
            }
    return seeded


def fetch_douban_streaming_entry(
    row: dict[str, Any],
    cached_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing = dict(cached_entry) if isinstance(cached_entry, dict) else {}
    search_had_response = False
    search_errors: list[str] = []
    title_candidates = unique_preserve_order(
        [
            normalize_cell(existing.get("metadata_title")),
            normalize_cell(existing.get("match_name")),
            normalize_cell(row.get("name")),
        ]
    )
    year = row.get("year") or existing.get("match_year")
    imdb_id = normalize_cell(existing.get("imdb_id"))
    letterboxd_url = normalize_source_uri(existing.get("letterboxd_url"))
    if not imdb_id and letterboxd_url:
        try:
            page_html = fetch_letterboxd_text(letterboxd_url)
            imdb_match = re.search(r"imdb\.com/title/(tt\d+)", page_html)
            if imdb_match:
                imdb_id = imdb_match.group(1)
                existing["imdb_id"] = imdb_id
        except Exception:
            pass

    if imdb_id:
        try:
            wikidata_douban_id = fetch_wikidata_douban_id(imdb_id)
            search_had_response = True
        except Exception as exc:  # noqa: BLE001
            search_errors.append(normalize_cell(exc))
            wikidata_douban_id = None
        if wikidata_douban_id:
            try:
                detail = fetch_douban_detail(wikidata_douban_id)
            except Exception as exc:  # noqa: BLE001
                search_errors.append(f"Wikidata Douban ID {wikidata_douban_id} detail failed: {normalize_cell(exc)}")
            else:
                rating = detail.get("rating") if isinstance(detail.get("rating"), dict) else {}
                rating_value = coerce_douban_rating(rating.get("value"))
                rating_count = pd.to_numeric(rating.get("count"), errors="coerce")
                if rating_value is not None:
                    return {
                        **existing,
                        "film_key": row["film_key"],
                        "douban_status": "matched",
                        "douban_cache_version": DOUBAN_CACHE_VERSION,
                        "douban_id": wikidata_douban_id,
                        "douban_title": normalize_cell(detail.get("title")),
                        "douban_url": f"https://movie.douban.com/subject/{wikidata_douban_id}/",
                        "douban_rating": rating_value,
                        "douban_rating_count": int(rating_count) if rating_value is not None and pd.notna(rating_count) else None,
                        "douban_year": normalize_cell(detail.get("year")),
                        "douban_match_key": f"{imdb_id}:wikidata",
                        "douban_updated_at": pd.Timestamp.now("UTC").isoformat(),
                    }
                search_errors.append(f"Wikidata Douban ID {wikidata_douban_id} has no numeric rating")

        try:
            raw_imdb_candidates = fetch_douban_subject_search(imdb_id)
            search_had_response = True
            imdb_candidates = [
                normalize_douban_search_item(item)
                for item in raw_imdb_candidates
            ]
        except Exception as exc:  # noqa: BLE001
            search_errors.append(normalize_cell(exc))
            imdb_candidates = []
        if imdb_candidates:
            match = choose_douban_match(imdb_candidates, title_candidates, year) or imdb_candidates[0]
            candidate_year = pd.to_numeric(match.get("year"), errors="coerce")
            target_year = pd.to_numeric(year, errors="coerce")
            if pd.isna(target_year) or pd.isna(candidate_year) or abs(int(target_year) - int(candidate_year)) <= 1:
                subject_id = normalize_cell(match.get("id"))
                detail: dict[str, Any] = {}
                try:
                    detail = fetch_douban_detail(subject_id)
                except Exception:
                    detail = {}
                rating = detail.get("rating") if isinstance(detail.get("rating"), dict) else {}
                rating_value = pd.to_numeric(rating.get("value"), errors="coerce")
                if pd.isna(rating_value):
                    rating_value = pd.to_numeric(match.get("rating_value"), errors="coerce")
                rating_value = coerce_douban_rating(rating_value)
                rating_count = pd.to_numeric(rating.get("count"), errors="coerce")
                if pd.isna(rating_count):
                    rating_count = pd.to_numeric(match.get("rating_count"), errors="coerce")
                if rating_value is not None:
                    return {
                        **existing,
                        "film_key": row["film_key"],
                        "douban_status": "matched",
                        "douban_cache_version": DOUBAN_CACHE_VERSION,
                        "douban_id": subject_id,
                        "douban_title": normalize_cell(detail.get("title")) or normalize_cell(match.get("title")),
                        "douban_url": normalize_source_uri(match.get("url")) or normalize_source_uri(f"https://movie.douban.com/subject/{subject_id}/"),
                        "douban_rating": rating_value,
                        "douban_rating_count": int(rating_count) if rating_value is not None and pd.notna(rating_count) else None,
                        "douban_year": normalize_cell(detail.get("year")) or normalize_cell(match.get("year")),
                        "douban_match_key": imdb_id,
                        "douban_updated_at": pd.Timestamp.now("UTC").isoformat(),
                    }

    for query in title_candidates:
        search_candidates: list[dict[str, Any]] = []
        try:
            raw_search_candidates = fetch_douban_subject_search(
                f"{query} {int(year)}" if pd.notna(pd.to_numeric(year, errors="coerce")) else query
            )
            search_had_response = True
            search_candidates.extend(
                normalize_douban_search_item(item)
                for item in raw_search_candidates
            )
        except Exception as exc:  # noqa: BLE001
            search_errors.append(normalize_cell(exc))
        try:
            suggestion_candidates = fetch_douban_suggestions(query)
            search_had_response = True
            search_candidates.extend(suggestion_candidates)
        except Exception as exc:  # noqa: BLE001
            search_errors.append(normalize_cell(exc))
        match = choose_douban_match(search_candidates, title_candidates, year)
        if match is None:
            continue
        subject_id = normalize_cell(match.get("id"))
        if not subject_id:
            continue
        detail: dict[str, Any] = {}
        try:
            detail = fetch_douban_detail(subject_id)
        except Exception:
            detail = {}
        rating = detail.get("rating") if isinstance(detail.get("rating"), dict) else {}
        rating_value = pd.to_numeric(rating.get("value"), errors="coerce")
        if pd.isna(rating_value):
            rating_value = pd.to_numeric(match.get("rating_value"), errors="coerce")
        rating_value = coerce_douban_rating(rating_value)
        rating_count = pd.to_numeric(rating.get("count"), errors="coerce")
        if pd.isna(rating_count):
            rating_count = pd.to_numeric(match.get("rating_count"), errors="coerce")
        if rating_value is None:
            continue
        return {
            **existing,
            "film_key": row["film_key"],
            "douban_status": "matched",
            "douban_cache_version": DOUBAN_CACHE_VERSION,
            "douban_id": subject_id,
            "douban_title": normalize_cell(detail.get("title")) or normalize_cell(match.get("title")),
            "douban_url": normalize_source_uri(match.get("url")) or normalize_source_uri(f"https://movie.douban.com/subject/{subject_id}/"),
            "douban_rating": rating_value,
            "douban_rating_count": int(rating_count) if rating_value is not None and pd.notna(rating_count) else None,
            "douban_year": normalize_cell(detail.get("year")) or normalize_cell(match.get("year")),
            "douban_updated_at": pd.Timestamp.now("UTC").isoformat(),
        }

    if not search_had_response:
        return {
            **existing,
            "film_key": row["film_key"],
            "douban_status": "error",
            "douban_cache_version": DOUBAN_CACHE_VERSION,
            "douban_error": "; ".join(unique_preserve_order(search_errors))[:500],
            "douban_updated_at": pd.Timestamp.now("UTC").isoformat(),
        }

    return {
        **existing,
        "film_key": row["film_key"],
        "douban_status": "not_found",
        "douban_cache_version": DOUBAN_CACHE_VERSION,
        "douban_updated_at": pd.Timestamp.now("UTC").isoformat(),
    }


def fetch_letterboxd_streaming_entry(
    row: dict[str, Any],
    cached_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    title = normalize_cell(row.get("name"))
    year = row.get("year")
    runtime_minutes = row.get("runtime_minutes")
    query = f"{title} {int(year)}" if pd.notna(year) else title
    match_name = normalize_cell(cached_entry.get("match_name")) if isinstance(cached_entry, dict) else ""
    match_year = pd.to_numeric(cached_entry.get("match_year"), errors="coerce") if isinstance(cached_entry, dict) else None
    slug = normalize_cell(cached_entry.get("slug")) if isinstance(cached_entry, dict) else ""
    letterboxd_url = normalize_source_uri(cached_entry.get("letterboxd_url")) if isinstance(cached_entry, dict) else ""

    if not letterboxd_url:
        payload = fetch_letterboxd_json(
            f"{LETTERBOXD_BASE_URL}/s/autocompletefilm?q={quote_plus(query)}"
        )
        candidates = ensure_list(payload.get("data"))
        match = choose_letterboxd_match(candidates, title, year, runtime_minutes)

        if match is None and query != title:
            fallback = fetch_letterboxd_json(
                f"{LETTERBOXD_BASE_URL}/s/autocompletefilm?q={quote_plus(title)}"
            )
            candidates = ensure_list(fallback.get("data"))
            match = choose_letterboxd_match(candidates, title, year, runtime_minutes)

        if match is None:
            return {
                "film_key": row["film_key"],
                "status": "not_found",
                "query": query,
                "cache_version": STREAMING_CACHE_VERSION,
                "updated_at": pd.Timestamp.now("UTC").isoformat(),
            }

        slug = normalize_cell(match.get("slug"))
        match_name = normalize_cell(match.get("name"))
        match_year = pd.to_numeric(match.get("releaseYear"), errors="coerce")
        raw_url = normalize_cell(match.get("url"))
        letterboxd_url = normalize_source_uri(
            raw_url if raw_url.startswith("http") else f"{LETTERBOXD_BASE_URL}{raw_url}"
        )

    page_html = fetch_letterboxd_text(letterboxd_url)
    page_metadata = parse_letterboxd_page_metadata(page_html)
    letterboxd_rating = page_metadata["letterboxd_rating"]
    rating_count = page_metadata["letterboxd_rating_count"]
    if letterboxd_rating is None and slug:
        histogram = fetch_letterboxd_text(
            f"{LETTERBOXD_BASE_URL}/csi/film/{slug}/rating-histogram/"
        )
        letterboxd_rating, rating_count = parse_rating_histogram(histogram)

    return {
        "film_key": row["film_key"],
        "status": "matched",
        "query": query,
        "match_name": match_name,
        "match_year": int(match_year) if pd.notna(match_year) else None,
        "slug": slug,
        "letterboxd_url": letterboxd_url,
        "letterboxd_rating": letterboxd_rating,
        "letterboxd_rating_count": rating_count,
        "site_average_rating": page_metadata["site_average_rating"],
        "site_rating_count": page_metadata["site_rating_count"],
        "runtime_minutes": page_metadata["runtime_minutes"],
        "directors": page_metadata["directors"],
        "actors": page_metadata["actors"],
        "genres": page_metadata["genres"],
        "countries": page_metadata["countries"],
        "metadata_title": page_metadata["metadata_title"],
        "imdb_id": page_metadata["imdb_id"],
        "cache_version": STREAMING_CACHE_VERSION,
        "updated_at": pd.Timestamp.now("UTC").isoformat(),
    }


def update_streaming_letterboxd_cache(
    targets: pd.DataFrame,
    cache_path: Path,
    max_new_lookups: int,
    workers: int,
    refresh_cache: bool,
) -> dict[str, Any]:
    cache = load_json_cache(cache_path)
    lookup_frame = targets.copy()
    if not refresh_cache:
        valid_cached_keys = {key for key, entry in cache.items() if is_valid_streaming_cache_entry(entry)}
        lookup_frame = lookup_frame[~lookup_frame["film_key"].isin(valid_cached_keys)]
    if max_new_lookups >= 0:
        lookup_frame = lookup_frame.head(max_new_lookups)
    if lookup_frame.empty:
        return cache

    max_workers = max(1, workers)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(fetch_letterboxd_streaming_entry, row, cache.get(row["film_key"])): row["film_key"]
            for row in lookup_frame.to_dict(orient="records")
        }
        for index, future in enumerate(as_completed(futures), start=1):
            film_key_value = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                result = {
                    "film_key": film_key_value,
                    "status": "error",
                    "error": normalize_cell(exc),
                    "updated_at": pd.Timestamp.now("UTC").isoformat(),
                }
            cache[result["film_key"]] = result
            if index % 50 == 0 or index == len(futures):
                write_json_cache(cache_path, cache)

    write_json_cache(cache_path, cache)
    return cache


def update_streaming_douban_cache(
    targets: pd.DataFrame,
    cache_path: Path,
    max_new_lookups: int,
    workers: int,
    refresh_cache: bool,
) -> dict[str, Any]:
    cache = load_json_cache(cache_path)
    lookup_frame = targets.copy()
    if not refresh_cache:
        lookup_frame = lookup_frame[
            lookup_frame["film_key"].apply(lambda key: not has_streaming_douban_entry(cache.get(key)))
        ]
    if max_new_lookups >= 0:
        lookup_frame = lookup_frame.head(max_new_lookups)
    if lookup_frame.empty:
        return cache

    max_workers = max(1, workers)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(fetch_douban_streaming_entry, row, cache.get(row["film_key"])): row["film_key"]
            for row in lookup_frame.to_dict(orient="records")
        }
        for index, future in enumerate(as_completed(futures), start=1):
            film_key_value = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                existing = cache.get(film_key_value) if isinstance(cache.get(film_key_value), dict) else {}
                result = {
                    **existing,
                    "film_key": film_key_value,
                    "douban_status": "error",
                    "douban_cache_version": DOUBAN_CACHE_VERSION,
                    "douban_error": normalize_cell(exc),
                    "douban_updated_at": pd.Timestamp.now("UTC").isoformat(),
                }
            cache[result["film_key"]] = result
            if index % 50 == 0 or index == len(futures):
                write_json_cache(cache_path, cache)

    write_json_cache(cache_path, cache)
    return cache


def has_watched_douban_entry(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    status = normalize_cell(entry.get("douban_status"))
    rating = pd.to_numeric(entry.get("douban_rating"), errors="coerce")
    if status in {"matched", "historical_removed"}:
        return pd.notna(rating) and float(rating) > 0
    version = pd.to_numeric(entry.get("douban_cache_version"), errors="coerce")
    if pd.isna(version) or int(version) < WATCHED_DOUBAN_CACHE_VERSION:
        return False
    return status in {"not_found", "missing_imdb", "error", "no_rating"}


def fetch_watched_imdb_entry(row: dict[str, Any], cached_entry: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = dict(cached_entry) if isinstance(cached_entry, dict) else {}
    imdb_id = normalize_cell(existing.get("imdb_id"))
    if imdb_id:
        return {**existing, "film_key": row["film_key"], "imdb_status": "matched"}

    source_uri = normalize_source_uri(row.get("canonical_url")) or normalize_source_uri(row.get("letterboxd_uri"))
    if not source_uri:
        return {
            **existing,
            "film_key": row["film_key"],
            "imdb_status": "missing_uri",
            "updated_at": pd.Timestamp.now("UTC").isoformat(),
        }
    try:
        page_html = fetch_letterboxd_text(source_uri)
    except Exception as exc:  # noqa: BLE001
        return {
            **existing,
            "film_key": row["film_key"],
            "imdb_status": "error",
            "imdb_error": normalize_cell(exc),
            "updated_at": pd.Timestamp.now("UTC").isoformat(),
        }
    imdb_match = re.search(r"imdb\.com/title/(tt\d+)", page_html)
    if not imdb_match:
        return {
            **existing,
            "film_key": row["film_key"],
            "imdb_status": "not_found",
            "updated_at": pd.Timestamp.now("UTC").isoformat(),
        }
    return {
        **existing,
        "film_key": row["film_key"],
        "imdb_status": "matched",
        "imdb_id": imdb_match.group(1),
        "updated_at": pd.Timestamp.now("UTC").isoformat(),
    }


def watched_row_for_douban_search(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "film_key": row["film_key"],
        "name": normalize_cell(row.get("Name")),
        "year": row.get("Year"),
        "letterboxd_url": normalize_source_uri(row.get("canonical_url")) or normalize_source_uri(row.get("letterboxd_uri")),
    }


def watched_existing_for_douban_search(row: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    return {
        **existing,
        "film_key": row["film_key"],
        "metadata_title": normalize_cell(row.get("Name")),
        "match_name": normalize_cell(row.get("Name")),
        "match_year": row.get("Year"),
        "letterboxd_url": normalize_source_uri(row.get("canonical_url")) or normalize_source_uri(row.get("letterboxd_uri")),
        "imdb_id": normalize_cell(existing.get("imdb_id")),
    }


def build_douban_result_from_detail(
    existing: dict[str, Any],
    film_key_value: str,
    douban_id: str,
    match_key: str,
) -> dict[str, Any]:
    detail = fetch_douban_detail_resilient(douban_id)
    rating = detail.get("rating") if isinstance(detail.get("rating"), dict) else {}
    rating_value = coerce_douban_rating(rating.get("value"))
    rating_count = pd.to_numeric(rating.get("count"), errors="coerce")
    if rating_value is None:
        raise RuntimeError(f"Douban detail for {douban_id} did not include a numeric rating")
    return {
        **existing,
        "film_key": film_key_value,
        "douban_status": "matched",
        "douban_cache_version": WATCHED_DOUBAN_CACHE_VERSION,
        "douban_id": douban_id,
        "douban_title": normalize_cell(detail.get("title")),
        "douban_url": f"https://movie.douban.com/subject/{douban_id}/",
        "douban_rating": rating_value,
        "douban_rating_count": int(rating_count) if rating_value is not None and pd.notna(rating_count) else None,
        "douban_year": normalize_cell(detail.get("year")),
        "douban_match_key": match_key,
        "douban_source": normalize_cell(detail.get("_source")) or "douban_detail",
        "douban_updated_at": pd.Timestamp.now("UTC").isoformat(),
    }


def build_watched_douban_section(
    ratings_df: pd.DataFrame,
    output_dir: Path,
    max_new_lookups: int,
    workers: int,
    refresh_cache: bool,
) -> tuple[dict[str, Any], pd.DataFrame]:
    cache_path = output_dir / "watched_douban_cache.json"
    cache = load_json_cache(cache_path)
    if not refresh_cache:
        cache = seed_watched_douban_cache_from_published_report(output_dir, cache)
    try:
        public_douban_index = load_public_douban_dataset_index(output_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: public Douban dataset fallback unavailable: {exc}", file=sys.stderr)
        public_douban_index = {"by_imdb": {}, "by_douban_id": {}}
    public_douban_by_imdb = public_douban_index.get("by_imdb", {})
    public_douban_by_id = public_douban_index.get("by_douban_id", {})
    try:
        ptgen_douban_index = load_ptgen_douban_imdb_index(output_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: PtGen Douban fallback unavailable: {exc}", file=sys.stderr)
        ptgen_douban_index = {"by_imdb": {}, "by_douban_id": {}}
    ptgen_douban_by_imdb = ptgen_douban_index.get("by_imdb", {})
    ptgen_douban_by_id = ptgen_douban_index.get("by_douban_id", {})
    targets = ratings_df[
        [
            "film_key",
            "Name",
            "Year",
            "user_rating",
            "Letterboxd URI",
            "canonical_url",
            "site_average_rating",
            "site_rating_count",
        ]
    ].copy()
    targets = targets.rename(columns={"Letterboxd URI": "letterboxd_uri"})
    lookup_frame = targets.copy()
    if not refresh_cache:
        lookup_frame = lookup_frame[
            lookup_frame["film_key"].apply(lambda key: not has_watched_douban_entry(cache.get(key)))
        ]
    if max_new_lookups >= 0:
        lookup_frame = lookup_frame.head(max_new_lookups)

    if not lookup_frame.empty:
        max_workers = max(1, workers)
        imdb_targets = [
            row
            for row in lookup_frame.to_dict(orient="records")
            if not normalize_cell(cache.get(row["film_key"], {}).get("imdb_id"))
        ]
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(fetch_watched_imdb_entry, row, cache.get(row["film_key"])): row["film_key"]
                for row in imdb_targets
            }
            for index, future in enumerate(as_completed(futures), start=1):
                result = future.result()
                cache[result["film_key"]] = result
                if index % 50 == 0 or index == len(futures):
                    write_json_cache(cache_path, cache)

        for row in lookup_frame.to_dict(orient="records"):
            film_key_value = row["film_key"]
            existing = cache.get(film_key_value) if isinstance(cache.get(film_key_value), dict) else {}
            if has_watched_douban_entry(existing):
                continue
            historical_override = WATCHED_DOUBAN_HISTORICAL_RATING_OVERRIDES.get(film_key_value)
            if historical_override:
                cache[film_key_value] = build_douban_result_from_historical_override(
                    existing,
                    film_key_value,
                    historical_override,
                )
                continue
            override = WATCHED_DOUBAN_SUBJECT_OVERRIDES.get(film_key_value)
            if not override:
                continue
            override_id, override_source = override
            ptgen_entry = ptgen_douban_by_id.get(override_id) or {
                "douban_id": override_id,
                "douban_title": normalize_cell(row.get("Name")),
                "douban_year": normalize_cell(row.get("Year")),
            }
            try:
                cache[film_key_value] = build_douban_result_from_ptgen_entry(
                    existing,
                    film_key_value,
                    ptgen_entry,
                    output_dir,
                    f"{override_id}:{override_source}",
                )
            except Exception as exc:  # noqa: BLE001
                cache[film_key_value] = {
                    **existing,
                    "film_key": film_key_value,
                    "douban_id": override_id,
                    "douban_status": "error",
                    "douban_cache_version": WATCHED_DOUBAN_CACHE_VERSION,
                    "douban_error": normalize_cell(exc),
                    "douban_updated_at": pd.Timestamp.now("UTC").isoformat(),
                }
        write_json_cache(cache_path, cache)

        imdb_ids = [
            normalize_cell(cache.get(row["film_key"], {}).get("imdb_id"))
            for row in lookup_frame.to_dict(orient="records")
        ]
        imdb_to_douban = fetch_wikidata_douban_id_map(imdb_ids)
        for row in lookup_frame.to_dict(orient="records"):
            film_key_value = row["film_key"]
            existing = cache.get(film_key_value) if isinstance(cache.get(film_key_value), dict) else {}
            if has_watched_douban_entry(existing):
                continue
            if normalize_cell(existing.get("douban_status")) == "no_rating":
                continue
            imdb_id = normalize_cell(existing.get("imdb_id"))
            if not imdb_id:
                cache[film_key_value] = {
                    **existing,
                    "film_key": film_key_value,
                    "douban_status": "missing_imdb",
                    "douban_cache_version": WATCHED_DOUBAN_CACHE_VERSION,
                    "douban_updated_at": pd.Timestamp.now("UTC").isoformat(),
                }
                continue
            douban_id = imdb_to_douban.get(imdb_id)
            if not douban_id:
                public_entry = public_douban_by_imdb.get(imdb_id)
                if public_entry:
                    cache[film_key_value] = build_douban_result_from_public_entry(
                        existing,
                        film_key_value,
                        public_entry,
                        f"{imdb_id}:public_dataset",
                    )
                    continue
                ptgen_entry = ptgen_douban_by_imdb.get(imdb_id)
                if ptgen_entry:
                    cache[film_key_value] = build_douban_result_from_ptgen_entry(
                        {
                            **existing,
                            "imdb_id": imdb_id,
                        },
                        film_key_value,
                        ptgen_entry,
                        output_dir,
                        f"{imdb_id}:ptgen_imdb_map",
                    )
                    continue
                cache[film_key_value] = {
                    **existing,
                    "film_key": film_key_value,
                    "douban_status": "not_found",
                    "douban_cache_version": WATCHED_DOUBAN_CACHE_VERSION,
                    "douban_error": "No Douban ID found in Wikidata for IMDb ID",
                    "douban_updated_at": pd.Timestamp.now("UTC").isoformat(),
                }
                continue
            public_entry = public_douban_by_id.get(douban_id) or public_douban_by_imdb.get(imdb_id)
            if public_entry:
                cache[film_key_value] = build_douban_result_from_public_entry(
                    {
                        **existing,
                        "imdb_id": imdb_id,
                    },
                    film_key_value,
                    public_entry,
                    f"{imdb_id}:wikidata:public_dataset",
                )
                continue
            ptgen_entry = ptgen_douban_by_id.get(douban_id) or ptgen_douban_by_imdb.get(imdb_id)
            if ptgen_entry:
                cache[film_key_value] = build_douban_result_from_ptgen_entry(
                    {
                        **existing,
                        "imdb_id": imdb_id,
                    },
                    film_key_value,
                    ptgen_entry,
                    output_dir,
                    f"{imdb_id}:wikidata:ptgen_static",
                )
                continue
            cache[film_key_value] = {
                **existing,
                "film_key": film_key_value,
                "imdb_id": imdb_id,
                "douban_id": douban_id,
                "douban_status": "pending_detail",
                "douban_cache_version": WATCHED_DOUBAN_CACHE_VERSION,
            }
        write_json_cache(cache_path, cache)

        detail_targets = [
            key
            for key, entry in cache.items()
            if isinstance(entry, dict)
            and normalize_cell(entry.get("douban_id"))
            and not has_watched_douban_entry(entry)
            and normalize_cell(entry.get("douban_status")) == "pending_detail"
            and key in set(lookup_frame["film_key"])
        ]
        with ThreadPoolExecutor(max_workers=max(1, min(workers, 2))) as pool:
            futures = {
                pool.submit(
                    build_douban_result_from_detail,
                    cache[key],
                    key,
                    normalize_cell(cache[key].get("douban_id")),
                    f"{normalize_cell(cache[key].get('imdb_id'))}:wikidata",
                ): key
                for key in detail_targets
            }
            for index, future in enumerate(as_completed(futures), start=1):
                film_key_value = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    existing = cache.get(film_key_value) if isinstance(cache.get(film_key_value), dict) else {}
                    result = {
                        **existing,
                        "film_key": film_key_value,
                        "douban_status": "error",
                        "douban_cache_version": WATCHED_DOUBAN_CACHE_VERSION,
                        "douban_error": normalize_cell(exc),
                        "douban_updated_at": pd.Timestamp.now("UTC").isoformat(),
                    }
                cache[film_key_value] = result
                if index % 50 == 0 or index == len(futures):
                    write_json_cache(cache_path, cache)

        fallback_targets = []
        lookup_keys = set(lookup_frame["film_key"])
        row_by_key = {row["film_key"]: row for row in lookup_frame.to_dict(orient="records")}
        for film_key_value in lookup_keys:
            entry = cache.get(film_key_value) if isinstance(cache.get(film_key_value), dict) else {}
            status = normalize_cell(entry.get("douban_status"))
            if has_watched_douban_entry(entry):
                continue
            if status in {"pending_detail", "no_rating"}:
                continue
            if film_key_value in row_by_key:
                fallback_targets.append(row_by_key[film_key_value])
        # This is the final rescue path for rows that have neither Wikidata nor
        # PtGen/public-dataset coverage. Search is fragile, so use low concurrency
        # but do not silently skip unresolved watched films.
        with ThreadPoolExecutor(max_workers=max(1, min(workers, 2))) as pool:
            futures = {
                pool.submit(
                    fetch_douban_streaming_entry,
                    watched_row_for_douban_search(row),
                    watched_existing_for_douban_search(
                        row,
                        cache.get(row["film_key"]) if isinstance(cache.get(row["film_key"]), dict) else {},
                    ),
                ): row["film_key"]
                for row in fallback_targets
            }
            for index, future in enumerate(as_completed(futures), start=1):
                film_key_value = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    existing = cache.get(film_key_value) if isinstance(cache.get(film_key_value), dict) else {}
                    result = {
                        **existing,
                        "film_key": film_key_value,
                        "douban_status": "error",
                        "douban_cache_version": WATCHED_DOUBAN_CACHE_VERSION,
                        "douban_error": normalize_cell(exc),
                        "douban_updated_at": pd.Timestamp.now("UTC").isoformat(),
                    }
                result["douban_cache_version"] = WATCHED_DOUBAN_CACHE_VERSION
                cache[result["film_key"]] = result
                if index % 25 == 0 or index == len(futures):
                    write_json_cache(cache_path, cache)

    write_json_cache(cache_path, cache)

    enriched = ratings_df.copy()
    enriched["douban_rating"] = enriched["film_key"].map(lambda key: cache.get(key, {}).get("douban_rating"))
    enriched["douban_url"] = enriched["film_key"].map(lambda key: cache.get(key, {}).get("douban_url"))
    enriched["douban_title"] = enriched["film_key"].map(lambda key: cache.get(key, {}).get("douban_title"))
    enriched["douban_status"] = enriched["film_key"].map(lambda key: cache.get(key, {}).get("douban_status"))
    enriched["imdb_id"] = enriched["film_key"].map(lambda key: cache.get(key, {}).get("imdb_id"))

    rated = enriched[enriched["douban_rating"].notna()].copy()
    rated["douban_gap"] = rated["douban_rating"] / 2 - rated["user_rating"]
    rows = enriched[
        [
            "film_key",
            "Name",
            "Year",
            "user_rating",
            "site_average_rating",
            "douban_rating",
            "douban_url",
            "douban_title",
            "douban_status",
            "genres",
            "countries",
            "directors",
        ]
    ].rename(columns={"Name": "name", "Year": "year"})
    top_gaps = (
        rated.assign(douban_gap_abs=rated["douban_gap"].abs())
        .sort_values(["douban_gap_abs", "douban_rating"], ascending=[False, False])
        [
            [
                "Name",
                "Year",
                "user_rating",
                "site_average_rating",
                "douban_rating",
                "douban_url",
                "douban_gap",
            ]
        ]
        .rename(columns={"Name": "name", "Year": "year"})
        .head(25)
    )
    return (
        {
            "stats": {
                "watched_titles": int(len(enriched)),
                "douban_rated_titles": int(enriched["douban_rating"].notna().sum()),
                "coverage": float(enriched["douban_rating"].notna().mean()) if len(enriched) else 0.0,
                "missing_titles": int(enriched["douban_rating"].isna().sum()),
                "new_lookups_requested": int(min(max_new_lookups, len(lookup_frame))) if max_new_lookups >= 0 else int(len(lookup_frame)),
            },
            "rows": serialize_frame(rows.sort_values(["douban_rating", "user_rating"], ascending=[False, False])),
            "top_gaps": serialize_frame(top_gaps),
        },
        enriched,
    )


def load_list_exports(list_dir: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for path in sorted(list_dir.glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            parsed = list(csv.reader(handle))
        if len(parsed) < 6:
            continue
        list_meta = parsed[2]
        title = normalize_cell(list_meta[1]) if len(list_meta) > 1 else path.stem
        list_tags = split_tags(list_meta[2] if len(list_meta) > 2 else "")
        list_url = normalize_cell(list_meta[3] if len(list_meta) > 3 else "")
        list_description = normalize_cell(list_meta[4] if len(list_meta) > 4 else "")
        for row in parsed[5:]:
            if not row or not normalize_cell(row[0]):
                continue
            rows.append(
                {
                    "list_file": path.name,
                    "list_title": title,
                    "list_tags": list_tags,
                    "list_url": list_url,
                    "list_description": list_description,
                    "position": int(row[0]) if normalize_cell(row[0]).isdigit() else None,
                    "Name": normalize_cell(row[1]) if len(row) > 1 else "",
                    "Year": pd.to_numeric(normalize_cell(row[2]) if len(row) > 2 else "", errors="coerce"),
                    "Letterboxd URI": normalize_cell(row[3]) if len(row) > 3 else "",
                    "entry_description": normalize_cell(row[4]) if len(row) > 4 else "",
                }
            )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["film_key"] = frame.apply(lambda row: film_key(row["Name"], row["Year"]), axis=1)
    return frame


def classify_list(title: str, description: str) -> str:
    text = f"{title} {description}".lower()
    if any(
        phrase in text
        for phrase in [
            "watchlist",
            "want to watch",
            "watch soon",
            "need these",
            "recommended",
            "playlist for too long",
            "will watch",
        ]
    ):
        return "watch_plan"
    if any(
        phrase in text
        for phrase in [
            "top",
            "ranking",
            "favorite",
            "favourite",
            "best",
            "greatest",
            "impacted",
            "worth it",
            "watched 5+ times",
            "personal ranking",
            "all-time",
        ]
    ):
        return "preference"
    return "theme"


def build_runtime_bucket(series: pd.Series) -> pd.Series:
    return pd.cut(
        series,
        bins=[0, 90, 110, 130, 150, 1000],
        labels=["Under 90", "90-109", "110-129", "130-149", "150+"],
        right=False,
    ).astype("string")


def derive_tag_columns(frame: pd.DataFrame, tags_col: str = "tags_list") -> pd.DataFrame:
    derived = frame.copy()

    def lower_tags(tags: list[str]) -> list[str]:
        return [normalize_cell(tag).lower() for tag in ensure_list(tags) if normalize_cell(tag)]

    def companion_names(tags: list[str]) -> list[str]:
        names: list[str] = []
        for tag in ensure_list(tags):
            raw = normalize_cell(tag)
            lowered = raw.lower()
            if not lowered.startswith("with") or lowered == "withppl":
                continue
            name = raw[4:].strip()
            if name:
                names.append(name[:1].upper() + name[1:])
        return unique_preserve_order(names)

    def social_scope(tags: list[str]) -> str:
        tag_set = set(lower_tags(tags))
        if "watchparty" in tag_set or "withppl" in tag_set or companion_names(tags):
            return "Social viewing"
        if "myself" in tag_set:
            return "Solo"
        return "Unspecified"

    def social_detail(tags: list[str]) -> str:
        tag_set = set(lower_tags(tags))
        names = companion_names(tags)
        if "watchparty" in tag_set:
            return "Watchparty (3+)"
        if names:
            return "Named companion"
        if "withppl" in tag_set:
            return "With people"
        if "myself" in tag_set:
            return "Solo"
        return "Unspecified"

    def companion_label(tags: list[str]) -> str | None:
        names = companion_names(tags)
        return ", ".join(names) if names else None

    def venue_label(tags: list[str]) -> str:
        tag_set = set(lower_tags(tags))
        for key, label in VENUE_MAP.items():
            if key in tag_set:
                return label
        return "Home / unspecified"

    def location_label(tags: list[str]) -> str | None:
        tag_set = set(lower_tags(tags))
        for key, label in VENUE_MAP.items():
            if key in tag_set:
                return label
        if any(tag in tag_set for tag in DEVICE_PRIORITY + PLATFORM_TAGS):
            return "Home / personal setup"
        return None

    def device_label(tags: list[str]) -> str:
        tag_set = set(lower_tags(tags))
        if "thearter" in tag_set or "theater" in tag_set:
            return "Theater"
        for device in DEVICE_PRIORITY:
            if device in tag_set:
                if device == "ipad":
                    return "iPad"
                if device == "tv":
                    return "TV"
                return device.capitalize()
        return "Unknown"

    def platform_label(tags: list[str]) -> str:
        tag_set = set(lower_tags(tags))
        for platform in PLATFORM_TAGS:
            if platform in tag_set:
                return PLATFORM_LABEL_OVERRIDES.get(platform, platform.title())
        return "Unknown"

    derived["companion_names"] = derived[tags_col].apply(companion_names)
    derived["social_scope"] = derived[tags_col].apply(social_scope)
    derived["social_context"] = derived[tags_col].apply(social_detail)
    derived["companion"] = derived[tags_col].apply(companion_label)
    derived["venue_context"] = derived[tags_col].apply(venue_label)
    derived["location_context"] = derived[tags_col].apply(location_label)
    derived["device_context"] = derived[tags_col].apply(device_label)
    derived["platform_context"] = derived[tags_col].apply(platform_label)
    derived["is_social"] = derived["social_scope"] == "Social viewing"
    return derived


def weighted_mean(series: pd.Series, weights: pd.Series) -> float:
    if series.empty or weights.empty or float(weights.sum()) == 0:
        return float("nan")
    return float(np.average(series, weights=weights))


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z']+", text.lower())
        if len(token) >= 3 and token not in STOPWORDS
    ]


def discriminative_terms(review_frame: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    positive = review_frame[review_frame["user_rating"] >= 4.0]
    negative = review_frame[review_frame["user_rating"] <= 3.0]

    pos_counts = Counter(token for tokens in positive["tokens"] for token in tokens)
    neg_counts = Counter(token for tokens in negative["tokens"] for token in tokens)
    vocab = {term for term in set(pos_counts) | set(neg_counts) if pos_counts[term] + neg_counts[term] >= 4}
    total_pos = sum(pos_counts.values()) + len(vocab)
    total_neg = sum(neg_counts.values()) + len(vocab)

    scored: list[dict[str, Any]] = []
    for term in vocab:
        pos = pos_counts[term] + 1
        neg = neg_counts[term] + 1
        score = math.log(pos / total_pos) - math.log(neg / total_neg)
        scored.append(
            {
                "term": term,
                "score": round(score, 3),
                "positive_count": int(pos_counts[term]),
                "negative_count": int(neg_counts[term]),
            }
        )

    positive_terms = [
        row for row in sorted(scored, key=lambda item: item["score"], reverse=True) if row["positive_count"] >= 4
    ][:15]
    negative_terms = [
        row for row in sorted(scored, key=lambda item: item["score"]) if row["negative_count"] >= 4
    ][:15]
    return positive_terms, negative_terms


def add_theme_columns(review_frame: pd.DataFrame) -> pd.DataFrame:
    themed = review_frame.copy()
    lowered = themed["Review"].fillna("").astype(str).str.lower()
    for theme, keywords in THEME_KEYWORDS.items():
        themed[theme] = lowered.apply(lambda text: any(keyword in text for keyword in keywords))
    return themed


def build_theme_stats(review_frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    global_positive_share = float((review_frame["user_rating"] >= 4.0).mean())
    for theme in THEME_KEYWORDS:
        scoped = review_frame[review_frame[theme]]
        if scoped.empty:
            continue
        rows.append(
            {
                "theme": theme,
                "mention_count": int(len(scoped)),
                "mention_rate": float(len(scoped) / len(review_frame)),
                "avg_rating": float(scoped["user_rating"].mean()),
                "avg_word_count": float(scoped["word_count"].mean()),
                "positive_lift": float((scoped["user_rating"] >= 4.0).mean() - global_positive_share),
            }
        )
    return pd.DataFrame(rows).sort_values(["mention_count", "avg_rating"], ascending=[False, False])


def make_bonus_lookup(
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
    grouped = scoped.groupby(feature_col).agg(
        films=("film_key", "nunique"),
        avg_rating=("user_rating", "mean"),
    )
    grouped["bonus"] = (
        grouped["avg_rating"] * grouped["films"] + global_mean * prior_weight
    ) / (grouped["films"] + prior_weight) - global_mean
    lookup: dict[str, dict[str, float]] = {}
    for label, row in grouped.reset_index().iterrows():
        value = row[feature_col]
        lookup[value] = {
            "films": int(row["films"]),
            "avg_rating": float(row["avg_rating"]),
            "bonus": float(row["bonus"]),
        }
    return lookup


def build_recommendation_pool(
    ratings_df: pd.DataFrame,
    watchlist_df: pd.DataFrame,
    list_entries_df: pd.DataFrame,
    streaming_section: dict[str, Any],
) -> pd.DataFrame:
    watched_keys = set(ratings_df["film_key"])
    frames: list[pd.DataFrame] = []

    official_watchlist = watchlist_df.copy()
    if not official_watchlist.empty:
        official_watchlist["film_key"] = official_watchlist.apply(lambda row: film_key(row["Name"], row["Year"]), axis=1)
        official_watchlist["watched"] = official_watchlist["film_key"].isin(watched_keys)
        official_watchlist = official_watchlist[~official_watchlist["watched"]].copy()
        official_watchlist["source_uri"] = official_watchlist["Letterboxd URI"].apply(normalize_source_uri)
        official_watchlist["source_list_name"] = "Official Watchlist"
        official_watchlist["list_category"] = "watch_plan"
        official_watchlist["candidate_source"] = "watchlist"
        official_watchlist["list_weight"] = 1.0
        official_watchlist["in_watchlist"] = True
        official_watchlist["in_user_lists"] = False
        official_watchlist["currently_streaming"] = False
        official_watchlist["availability_signal"] = 0.0
        official_watchlist["providers"] = [[] for _ in range(len(official_watchlist))]
        frames.append(official_watchlist)

    user_lists = list_entries_df.copy()
    if not user_lists.empty:
        user_lists["watched"] = user_lists["film_key"].isin(watched_keys)
        user_lists = user_lists[~user_lists["watched"]].copy()
        user_lists["source_uri"] = user_lists["Letterboxd URI"].apply(normalize_source_uri)
        user_lists["source_list_name"] = user_lists["list_title"]
        user_lists["candidate_source"] = "user_list"
        user_lists["list_weight"] = user_lists.apply(
            lambda row: FUTURE_LIST_WEIGHTS.get(
                row["list_title"],
                LIST_CATEGORY_WEIGHTS.get(row["list_category"], 0.55),
            ),
            axis=1,
        )
        user_lists["in_watchlist"] = False
        user_lists["in_user_lists"] = True
        user_lists["currently_streaming"] = False
        user_lists["availability_signal"] = 0.0
        user_lists["providers"] = [[] for _ in range(len(user_lists))]
        frames.append(user_lists)

    streaming_rows = pd.DataFrame(streaming_section.get("rows") or [])
    if not streaming_rows.empty:
        streaming_rows = streaming_rows[~streaming_rows["watched"]].copy()
        streaming_rows = streaming_rows[streaming_rows["source_uri"].fillna("").astype(str) != ""].copy()
        streaming_rows = streaming_rows.rename(columns={"name": "Name", "year": "Year"})
        streaming_rows["Letterboxd URI"] = streaming_rows["source_uri"]
        streaming_rows["site_average_rating"] = streaming_rows["letterboxd_rating"]
        streaming_rows["site_rating_count"] = streaming_rows["letterboxd_rating_count"]
        streaming_rows["source_list_name"] = ""
        streaming_rows["list_category"] = None
        streaming_rows["candidate_source"] = "streaming"
        streaming_rows["list_weight"] = 0.0
        streaming_rows["in_watchlist"] = False
        streaming_rows["in_user_lists"] = False
        streaming_rows["currently_streaming"] = True
        streaming_rows["availability_signal"] = (
            0.48
            + streaming_rows["exclusive"].astype(float) * 0.16
            + streaming_rows["provider_count"].fillna(0).clip(upper=3).astype(float) * 0.04
        )
        frames.append(streaming_rows)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined = combined[~combined["film_key"].isin(watched_keys)].copy()
    combined["group_key"] = combined["source_uri"].fillna("").astype(str)
    combined.loc[combined["group_key"] == "", "group_key"] = combined["film_key"]
    combined = combined.drop_duplicates(
        subset=["group_key", "candidate_source", "source_list_name"],
        keep="first",
    )

    def metadata_richness(record: dict[str, Any]) -> int:
        score = 0
        for key in ["site_average_rating", "site_rating_count", "runtime_minutes", "year", "Year"]:
            if pd.notna(pd.to_numeric(record.get(key), errors="coerce")):
                score += 1
        for key in ["directors", "actors", "genres", "countries"]:
            if ensure_list(record.get(key)):
                score += 2
        if normalize_cell(record.get("Letterboxd URI") or record.get("source_uri")):
            score += 1
        return score

    def numeric_or_zero(value: Any) -> float:
        number = pd.to_numeric(value, errors="coerce")
        return float(number) if pd.notna(number) else 0.0

    pool_rows: list[dict[str, Any]] = []
    for _group_key, grouped in combined.groupby("group_key", dropna=False):
        records = grouped.to_dict(orient="records")
        best = max(records, key=metadata_richness)
        source_lists = sorted(
            {
                normalize_cell(record.get("source_list_name"))
                for record in records
                if normalize_cell(record.get("source_list_name"))
                and normalize_cell(record.get("source_list_name")) != "Official Watchlist"
            }
        )
        list_categories = sorted(
            {
                normalize_cell(record.get("list_category"))
                for record in records
                if normalize_cell(record.get("list_category"))
            },
            key=lambda item: LIST_CATEGORY_ORDER.get(item, 99),
        )
        provider_labels = sorted(
            {
                normalize_cell(provider)
                for record in records
                for provider in ensure_list(record.get("providers"))
                if normalize_cell(provider)
            }
        )
        list_signal = sum(numeric_or_zero(record.get("list_weight")) for record in records)
        if len(source_lists) > 1:
            list_signal += 0.06 * (len(source_lists) - 1)
        availability_signal = max(numeric_or_zero(record.get("availability_signal")) for record in records)
        site_average = next(
            (
                numeric_or_zero(record.get("site_average_rating"))
                for record in sorted(records, key=metadata_richness, reverse=True)
                if pd.notna(pd.to_numeric(record.get("site_average_rating"), errors="coerce"))
            ),
            None,
        )
        site_count = next(
            (
                int(pd.to_numeric(record.get("site_rating_count"), errors="coerce"))
                for record in sorted(records, key=metadata_richness, reverse=True)
                if pd.notna(pd.to_numeric(record.get("site_rating_count"), errors="coerce"))
            ),
            None,
        )

        pool_rows.append(
            {
                "film_key": best.get("film_key"),
                "Name": normalize_cell(best.get("Name") or best.get("name") or best.get("metadata_title")),
                "Year": pd.to_numeric(best.get("Year") or best.get("year"), errors="coerce"),
                "year": pd.to_numeric(best.get("Year") or best.get("year"), errors="coerce"),
                "Letterboxd URI": normalize_source_uri(best.get("Letterboxd URI") or best.get("source_uri")),
                "source_uri": normalize_source_uri(best.get("Letterboxd URI") or best.get("source_uri")),
                "site_average_rating": site_average,
                "site_rating_count": site_count,
                "runtime_minutes": pd.to_numeric(best.get("runtime_minutes"), errors="coerce"),
                "runtime_bucket": best.get("runtime_bucket"),
                "decade_label": best.get("decade_label"),
                "directors": normalize_string_list(best.get("directors")),
                "actors": normalize_string_list(best.get("actors")),
                "genres": normalize_string_list(best.get("genres") or best.get("genre_labels")),
                "countries": normalize_string_list(best.get("countries")),
                "providers": provider_labels,
                "provider_count": len(provider_labels),
                "exclusive_streaming": bool(provider_labels) and len(provider_labels) == 1,
                "currently_streaming": bool(grouped["currently_streaming"].any()),
                "in_watchlist": bool(grouped["in_watchlist"].any()),
                "in_user_lists": bool(grouped["in_user_lists"].any()),
                "source_lists": source_lists,
                "source_count": len(source_lists),
                "list_categories": list_categories,
                "list_signal": round(float(list_signal), 3),
                "availability_signal": round(float(availability_signal), 3),
                "discovery_only": bool(
                    grouped["currently_streaming"].any()
                    and not grouped["in_watchlist"].any()
                    and not grouped["in_user_lists"].any()
                ),
            }
        )

    pool = pd.DataFrame(pool_rows)
    pool = pool[pool["Name"].fillna("").astype(str) != ""].copy()
    return pool


def score_recommendations(
    rated_df: pd.DataFrame,
    candidate_df: pd.DataFrame,
    global_mean: float,
    site_mean: float,
) -> pd.DataFrame:
    if candidate_df.empty:
        return pd.DataFrame(
            columns=[
                "rank",
                "name",
                "year",
                "predicted_rating",
                "priority_score",
                "confidence",
                "site_average_rating",
                "site_rating_count",
                "directors",
                "genres",
                "countries",
                "providers",
                "source_lists",
                "source_count",
                "in_watchlist",
                "in_user_lists",
                "currently_streaming",
                "exclusive_streaming",
                "discovery_only",
                "list_categories",
                "reason",
            ]
        )
    director_bonus = make_bonus_lookup(rated_df, "directors", global_mean, 4, list_like=True)
    genre_bonus = make_bonus_lookup(rated_df, "genres", global_mean, 6, list_like=True)
    country_bonus = make_bonus_lookup(rated_df, "countries", global_mean, 5, list_like=True)
    actor_bonus = make_bonus_lookup(rated_df, "actors", global_mean, 9, list_like=True)
    decade_bonus = make_bonus_lookup(rated_df, "decade_label", global_mean, 7)
    runtime_bonus = make_bonus_lookup(rated_df, "runtime_bucket", global_mean, 8)

    def collect_bonus(
        values: list[str],
        lookup: dict[str, dict[str, float]],
        weight: float,
        min_films: int,
        label: str,
    ) -> tuple[float, float, list[tuple[str, float, int]]]:
        matches: list[tuple[str, float, int]] = []
        for value in values:
            entry = lookup.get(value)
            if not entry or entry["films"] < min_films:
                continue
            matches.append((value, entry["bonus"], int(entry["films"])))
        if not matches:
            return 0.0, 0.0, []
        contribution = weight * float(np.mean([match[1] for match in matches]))
        confidence = min(1.0, sum(min(match[2], 10) for match in matches) / 25.0)
        return contribution, confidence, matches

    scored: list[dict[str, Any]] = []
    for _, row in candidate_df.iterrows():
        reasons: list[tuple[str, float]] = []
        director_part, director_conf, director_hits = collect_bonus(
            ensure_list(row["directors"]), director_bonus, 0.33, 2, "导演"
        )
        genre_part, genre_conf, genre_hits = collect_bonus(
            ensure_list(row["genres"]), genre_bonus, 0.26, 5, "类型"
        )
        country_part, country_conf, country_hits = collect_bonus(
            ensure_list(row["countries"]), country_bonus, 0.12, 3, "国家 / 地区"
        )
        actor_part, actor_conf, actor_hits = collect_bonus(
            ensure_list(row["actors"])[:5], actor_bonus, 0.08, 4, "演员"
        )

        decade_part = 0.0
        decade_conf = 0.0
        if normalize_cell(row["decade_label"]) in decade_bonus:
            item = decade_bonus[normalize_cell(row["decade_label"])]
            if item["films"] >= 8:
                decade_part = 0.09 * item["bonus"]
                decade_conf = min(1.0, item["films"] / 25.0)
                reasons.append((f"年代 {row['decade_label']}", decade_part))

        runtime_part = 0.0
        runtime_conf = 0.0
        if normalize_cell(row["runtime_bucket"]) in runtime_bonus:
            item = runtime_bonus[normalize_cell(row["runtime_bucket"])]
            if item["films"] >= 8:
                runtime_part = 0.05 * item["bonus"]
                runtime_conf = min(1.0, item["films"] / 25.0)
                reasons.append((f"片长 {row['runtime_bucket']}", runtime_part))

        for value, bonus, _count in director_hits:
            reasons.append((f"导演 {value}", 0.33 * bonus))
        for value, bonus, _count in genre_hits:
            reasons.append((f"类型 {value}", 0.26 * bonus))
        for value, bonus, _count in country_hits:
            reasons.append((f"国家 / 地区 {value}", 0.12 * bonus))
        for value, bonus, _count in actor_hits:
            reasons.append((f"演员 {value}", 0.08 * bonus))

        site_part = 0.0
        if pd.notna(row["site_average_rating"]):
            site_part = 0.23 * (float(row["site_average_rating"]) - site_mean)
            reasons.append((f"站内口碑 {float(row['site_average_rating']):.2f}", site_part))

        list_part = 0.10 * float(row["list_signal"])
        if row["source_count"] > 1:
            reasons.append((f"出现在 {int(row['source_count'])} 个自建 lists", list_part))
        elif row["source_lists"]:
            reasons.append((f"来自 {row['source_lists'][0]}", list_part))
        elif row["in_watchlist"]:
            reasons.append(("官方 watchlist 收录", list_part))

        availability_part = 0.08 * float(row.get("availability_signal", 0.0) or 0.0)
        if row.get("currently_streaming"):
            provider_text = ", ".join(ensure_list(row.get("providers"))[:3])
            suffix = " 等" if len(ensure_list(row.get("providers"))) > 3 else ""
            reasons.append((f"加拿大区可看：{provider_text}{suffix}", availability_part))

        predicted_rating = global_mean + director_part + genre_part + country_part + actor_part + decade_part + runtime_part + site_part
        predicted_rating = float(np.clip(predicted_rating, 0.5, 5.0))
        confidence = float(
            np.clip(
                np.mean(
                    [director_conf, genre_conf, country_conf, actor_conf, decade_conf, runtime_conf]
                )
                + (0.12 if pd.notna(row["site_average_rating"]) else 0.0)
                + min(float(row["source_count"]) * 0.04, 0.12),
                0.05,
                1.0,
            )
        )
        priority_score = predicted_rating + confidence * 0.22 + list_part + availability_part
        explanation = "；".join(
            reason for reason, score in sorted(reasons, key=lambda item: item[1], reverse=True) if score > 0.02
        )[:240]

        scored.append(
            {
                "name": row["Name"],
                "year": int(row["Year"]) if pd.notna(row["Year"]) else None,
                "source_uri": row["Letterboxd URI"],
                "predicted_rating": round(predicted_rating, 3),
                "priority_score": round(priority_score, 3),
                "confidence": round(confidence, 3),
                "site_average_rating": round(float(row["site_average_rating"]), 3)
                if pd.notna(row["site_average_rating"])
                else None,
                "site_rating_count": int(row["site_rating_count"]) if pd.notna(row["site_rating_count"]) else None,
                "directors": ensure_list(row["directors"]),
                "genres": ensure_list(row["genres"]),
                "countries": ensure_list(row["countries"]),
                "providers": ensure_list(row.get("providers")),
                "source_lists": row["source_lists"],
                "source_count": int(row["source_count"]),
                "in_watchlist": bool(row["in_watchlist"]),
                "in_user_lists": bool(row.get("in_user_lists")),
                "currently_streaming": bool(row.get("currently_streaming")),
                "exclusive_streaming": bool(row.get("exclusive_streaming")),
                "discovery_only": bool(row.get("discovery_only")),
                "list_categories": ensure_list(row.get("list_categories")),
                "reason": explanation or "历史评分特征、站内口碑与片单覆盖信号",
            }
        )

    recommendations = pd.DataFrame(scored).sort_values(
        ["priority_score", "predicted_rating", "site_average_rating"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    recommendations.insert(0, "rank", np.arange(1, len(recommendations) + 1))
    return recommendations


def build_recommendation_payload(recommendations: pd.DataFrame) -> dict[str, Any]:
    if recommendations.empty:
        return {
            "rows": [],
            "genre_options": [],
            "platform_options": [],
            "stats": {
                "candidate_count": 0,
                "watchlist_titles": 0,
                "list_titles": 0,
                "streaming_titles": 0,
                "discovery_titles": 0,
            },
        }

    genre_rows: list[dict[str, Any]] = []
    exploded_genres = recommendations[["rank", "genres"]].explode("genres")
    exploded_genres = exploded_genres[exploded_genres["genres"].notna()]
    for genre, grouped in exploded_genres.groupby("genres"):
        genre_rows.append(
            {
                "label": genre,
                "titles": int(grouped["rank"].nunique()),
            }
        )
    genre_options = sorted(genre_rows, key=lambda row: (-row["titles"], row["label"]))

    platform_rows: list[dict[str, Any]] = []
    exploded_platforms = recommendations[["rank", "providers"]].explode("providers")
    exploded_platforms = exploded_platforms[exploded_platforms["providers"].notna()]
    for provider, grouped in exploded_platforms.groupby("providers"):
        platform_rows.append(
            {
                "label": provider,
                "titles": int(grouped["rank"].nunique()),
            }
        )
    platform_options = sorted(platform_rows, key=lambda row: (-row["titles"], row["label"]))

    rows = serialize_frame(
        recommendations[
            [
                "rank",
                "name",
                "year",
                "predicted_rating",
                "priority_score",
                "confidence",
                "site_average_rating",
                "site_rating_count",
                "genres",
                "countries",
                "providers",
                "source_lists",
                "source_count",
                "in_watchlist",
                "in_user_lists",
                "currently_streaming",
                "exclusive_streaming",
                "discovery_only",
                "list_categories",
                "reason",
            ]
        ]
    )

    return {
        "rows": rows,
        "genre_options": genre_options,
        "platform_options": platform_options,
        "stats": {
            "candidate_count": int(len(recommendations)),
            "watchlist_titles": int(recommendations["in_watchlist"].sum()),
            "list_titles": int(recommendations["in_user_lists"].sum()),
            "streaming_titles": int(recommendations["currently_streaming"].sum()),
            "discovery_titles": int(recommendations["discovery_only"].sum()),
        },
    }


def build_genre_country_section(ratings_df: pd.DataFrame) -> dict[str, Any]:
    scoped = ratings_df[["film_key", "user_rating", "genres", "countries"]].copy()
    scoped["countries"] = scoped["countries"].apply(lambda values: ensure_list(values) or ["Unknown"])
    scoped["genres"] = scoped["genres"].apply(lambda values: ensure_list(values) or ["Unknown"])
    scoped["country_weight"] = scoped["countries"].apply(lambda values: 1 / max(len(values), 1))

    rows: list[dict[str, Any]] = []
    for _, row in scoped.iterrows():
        for genre in row["genres"]:
            for country in row["countries"]:
                rows.append(
                    {
                        "genre": genre,
                        "country": country,
                        "film_key": row["film_key"],
                        "user_rating": row["user_rating"],
                        "country_weight": row["country_weight"],
                    }
                )
    pairs = pd.DataFrame(rows)

    genre_totals = pairs.groupby("genre").agg(
        genre_films=("film_key", "nunique"),
        genre_weight=("country_weight", "sum"),
    )
    country_totals = pairs.groupby("country").agg(country_films=("film_key", "nunique"))
    pair_stats = pairs.groupby(["genre", "country"]).agg(
        films=("film_key", "nunique"),
        avg_rating=("user_rating", "mean"),
        weighted_units=("country_weight", "sum"),
    )
    pair_stats = pair_stats.reset_index()
    pair_stats = pair_stats.merge(genre_totals.reset_index(), on="genre", how="left")
    pair_stats["share_in_genre"] = pair_stats["weighted_units"] / pair_stats["genre_weight"]
    pair_stats["weighted_score"] = (
        pair_stats["avg_rating"] * pair_stats["films"] + ratings_df["user_rating"].mean() * 4
    ) / (pair_stats["films"] + 4)

    top_genres = (
        genre_totals.sort_values("genre_films", ascending=False).head(10).reset_index()["genre"].tolist()
    )
    top_countries = (
        country_totals.sort_values("country_films", ascending=False).head(10).reset_index()["country"].tolist()
    )

    count_matrix: list[list[float]] = []
    rating_matrix: list[list[float | None]] = []
    for country in top_countries:
        count_row: list[float] = []
        rating_row: list[float | None] = []
        for genre in top_genres:
            subset = pair_stats[(pair_stats["genre"] == genre) & (pair_stats["country"] == country)]
            if subset.empty:
                count_row.append(0)
                rating_row.append(None)
            else:
                count_row.append(float(subset.iloc[0]["films"]))
                rating_row.append(round(float(subset.iloc[0]["avg_rating"]), 3))
        count_matrix.append(count_row)
        rating_matrix.append(rating_row)

    genre_profiles = {}
    for genre in sorted(pair_stats["genre"].unique()):
        genre_profiles[genre] = serialize_frame(
            pair_stats[pair_stats["genre"] == genre]
            .sort_values(["films", "avg_rating"], ascending=[False, False])[
                ["country", "films", "avg_rating", "share_in_genre", "weighted_score"]
            ]
            .head(12)
        )

    top_combos = serialize_frame(
        pair_stats[pair_stats["films"] >= 3]
        .sort_values(["weighted_score", "films"], ascending=[False, False])[
            ["genre", "country", "films", "avg_rating", "share_in_genre", "weighted_score"]
        ]
        .head(25)
    )

    return {
        "top_genres": top_genres,
        "top_countries": top_countries,
        "count_matrix": count_matrix,
        "rating_matrix": rating_matrix,
        "genre_profiles": genre_profiles,
        "top_combos": top_combos,
    }


def build_tag_section(diary_df: pd.DataFrame) -> dict[str, Any]:
    rated_events = diary_df[diary_df["user_rating"].notna()].copy()
    tagged_events = diary_df[diary_df["tags_list"].apply(len).gt(0)].copy()

    def pie_rows(frame: pd.DataFrame, column: str, excluded: set[str] | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        excluded = excluded or set()
        source = frame[frame[column].notna()].copy()
        source = source[~source[column].isin(excluded)]
        if source.empty:
            return []
        grouped = (
            source.groupby(column)
            .agg(
                watches=("film_key", "size"),
                rated_watches=("user_rating", lambda s: int(s.notna().sum())),
                avg_rating=("user_rating", "mean"),
                distinct_films=("film_key", "nunique"),
            )
            .reset_index()
            .rename(columns={column: "label"})
            .sort_values(["watches", "avg_rating"], ascending=[False, False])
        )
        total = grouped["watches"].sum()
        grouped["share"] = grouped["watches"] / total if total else 0
        if limit is not None:
            grouped = grouped.head(limit)
        return serialize_frame(grouped)

    raw_tag_rows: list[dict[str, Any]] = []
    if not tagged_events.empty:
        exploded_tags = tagged_events.explode("tags_list").copy()
        exploded_tags["tag_label"] = exploded_tags["tags_list"].apply(normalize_cell)
        exploded_tags = exploded_tags[exploded_tags["tag_label"] != ""]
        if not exploded_tags.empty:
            grouped_tags = (
                exploded_tags.groupby("tag_label")
                .agg(
                    watches=("film_key", "size"),
                    avg_rating=("user_rating", "mean"),
                    distinct_films=("film_key", "nunique"),
                )
                .reset_index()
                .rename(columns={"tag_label": "label"})
                .sort_values(["watches", "avg_rating"], ascending=[False, False])
                .head(16)
            )
            total_tags = grouped_tags["watches"].sum()
            grouped_tags["share"] = grouped_tags["watches"] / total_tags if total_tags else 0
            raw_tag_rows = serialize_frame(grouped_tags)

    social_stats = serialize_frame(
        rated_events.groupby("social_context").agg(
            watches=("film_key", "size"),
            avg_rating=("user_rating", "mean"),
            distinct_films=("film_key", "nunique"),
            five_star_share=("user_rating", lambda s: float((s >= 4.5).mean())),
        )
        .reset_index()
        .sort_values(["avg_rating", "watches"], ascending=[False, False])
    )

    device_stats = serialize_frame(
        rated_events[rated_events["device_context"] != "Unknown"]
        .groupby("device_context")
        .agg(
            watches=("film_key", "size"),
            avg_rating=("user_rating", "mean"),
            distinct_films=("film_key", "nunique"),
        )
        .reset_index()
        .sort_values(["avg_rating", "watches"], ascending=[False, False])
    )

    platform_stats = serialize_frame(
        rated_events[rated_events["platform_context"] != "Unknown"]
        .groupby("platform_context")
        .agg(
            watches=("film_key", "size"),
            avg_rating=("user_rating", "mean"),
            distinct_films=("film_key", "nunique"),
        )
        .reset_index()
        .sort_values(["avg_rating", "watches"], ascending=[False, False])
    )

    venue_stats = serialize_frame(
        rated_events.groupby("venue_context")
        .agg(
            watches=("film_key", "size"),
            avg_rating=("user_rating", "mean"),
            distinct_films=("film_key", "nunique"),
        )
        .reset_index()
        .sort_values(["avg_rating", "watches"], ascending=[False, False])
    )

    named_companion_events = rated_events.explode("companion_names").copy()
    named_companion_events["companion_name"] = named_companion_events["companion_names"].apply(normalize_cell)
    named_companion_events = named_companion_events[named_companion_events["companion_name"] != ""]
    companion_stats = serialize_frame(
        named_companion_events
        .groupby("companion_name")
        .agg(
            watches=("film_key", "size"),
            avg_rating=("user_rating", "mean"),
        )
        .reset_index()
        .rename(columns={"companion_name": "companion"})
        .sort_values(["watches", "avg_rating"], ascending=[False, False])
        .head(12)
    )
    named_companion_tagged = tagged_events.explode("companion_names").copy()
    named_companion_tagged["companion_name"] = named_companion_tagged["companion_names"].apply(normalize_cell)
    named_companion_tagged = named_companion_tagged[named_companion_tagged["companion_name"] != ""]

    genre_rows: list[dict[str, Any]] = []
    exploded = rated_events.explode("genres")
    exploded = exploded[exploded["genres"].notna()]
    for genre, grouped in exploded.groupby("genres"):
        solo = grouped[grouped["social_context"] == "Solo"]
        social = grouped[grouped["is_social"]]
        if len(solo) < 3 or len(social) < 3:
            continue
        genre_rows.append(
            {
                "genre": genre,
                "solo_avg": float(solo["user_rating"].mean()),
                "social_avg": float(social["user_rating"].mean()),
                "diff": float(social["user_rating"].mean() - solo["user_rating"].mean()),
                "solo_watches": int(len(solo)),
                "social_watches": int(len(social)),
            }
        )
    social_genre_delta = sorted(genre_rows, key=lambda row: abs(row["diff"]), reverse=True)[:18]

    return {
        "social_stats": social_stats,
        "device_stats": device_stats,
        "platform_stats": platform_stats,
        "venue_stats": venue_stats,
        "companion_stats": companion_stats,
        "social_genre_delta": social_genre_delta,
        "tag_pies": {
            "device_context": pie_rows(tagged_events, "device_context", {"Unknown"}),
            "social_scope": pie_rows(tagged_events, "social_scope", {"Unspecified"}),
            "social_context": pie_rows(tagged_events, "social_context", {"Unspecified"}),
            "companion": pie_rows(named_companion_tagged, "companion_name"),
            "location_context": pie_rows(tagged_events, "location_context"),
            "platform_context": pie_rows(tagged_events, "platform_context", {"Unknown"}),
            "raw_tags": raw_tag_rows,
        },
    }


def build_review_section(reviews_df: pd.DataFrame) -> dict[str, Any]:
    review_frame = reviews_df[reviews_df["Review"].fillna("").astype(str).str.strip() != ""].copy()
    review_frame["word_count"] = review_frame["Review"].fillna("").astype(str).str.split().str.len()
    review_frame["tokens"] = review_frame["Review"].fillna("").astype(str).apply(tokenize)
    review_frame = add_theme_columns(review_frame)

    positive_terms, negative_terms = discriminative_terms(review_frame)
    theme_stats = build_theme_stats(review_frame)

    review_length_points = serialize_frame(
        review_frame[["Name", "Year", "user_rating", "word_count"]]
        .rename(columns={"Name": "name", "Year": "year"})
        .sort_values(["user_rating", "word_count"], ascending=[True, False])
    )

    return {
        "review_length_points": review_length_points,
        "positive_terms": positive_terms,
        "negative_terms": negative_terms,
        "theme_stats": serialize_frame(theme_stats),
        "stats": {
            "review_count": int(len(review_frame)),
            "avg_word_count": round(float(review_frame["word_count"].mean()), 1),
            "median_word_count": int(review_frame["word_count"].median()),
        },
    }


def build_list_section(list_entries_df: pd.DataFrame, ratings_df: pd.DataFrame) -> dict[str, Any]:
    if list_entries_df.empty:
        return {
            "list_summary": [],
            "category_summary": [],
            "preference_overlaps": [],
            "preference_country_bias": [],
            "preference_genre_bias": [],
            "watch_plan_overlap": [],
        }

    list_summary = (
        list_entries_df.groupby(["list_title", "list_category"])
        .agg(
            items=("film_key", "nunique"),
            watched_items=("watched", "sum"),
            avg_rating_of_watched=("user_rating", "mean"),
        )
        .reset_index()
    )
    list_summary["unwatched_items"] = list_summary["items"] - list_summary["watched_items"]
    list_summary["list_category_label"] = list_summary["list_category"].map(list_category_label)
    list_summary["category_order"] = list_summary["list_category"].map(LIST_CATEGORY_ORDER).fillna(99)

    category_summary = (
        list_summary.groupby(["list_category", "list_category_label", "category_order"])
        .agg(
            lists=("list_title", "nunique"),
            items=("items", "sum"),
            watched_items=("watched_items", "sum"),
        )
        .reset_index()
        .sort_values(["category_order", "lists", "items"], ascending=[True, False, False])
    )
    category_summary["unwatched_items"] = category_summary["items"] - category_summary["watched_items"]

    preference_entries = list_entries_df[
        (list_entries_df["list_category"] == "preference") & (list_entries_df["watched"])
    ].copy()
    preference_unique = preference_entries.drop_duplicates(subset=["film_key"]).copy()
    preference_overlaps = (
        preference_entries.groupby("film_key")
        .agg(
            name=("Name", "first"),
            year=("Year", "first"),
            appearances=("list_title", "nunique"),
            source_lists=("list_title", lambda values: sorted(set(values))),
            directors=("directors", "first"),
            genres=("genres", "first"),
            countries=("countries", "first"),
        )
        .reset_index()
        .sort_values(["appearances", "year", "name"], ascending=[False, False, True])
        .head(20)
    )

    def bias_table(feature: str, label: str) -> list[dict[str, Any]]:
        if preference_unique.empty:
            return []
        preference_feature = preference_unique[["film_key", feature]].explode(feature)
        preference_feature = preference_feature[preference_feature[feature].notna()]
        preference_feature[feature] = preference_feature[feature].astype(str).str.strip()
        preference_feature = preference_feature[preference_feature[feature] != ""]

        library_feature = ratings_df[["film_key", feature]].explode(feature)
        library_feature = library_feature[library_feature[feature].notna()]
        library_feature[feature] = library_feature[feature].astype(str).str.strip()
        library_feature = library_feature[library_feature[feature] != ""]

        preference_counts = preference_feature.groupby(feature)["film_key"].nunique()
        library_counts = library_feature.groupby(feature)["film_key"].nunique()
        total_preference = max(preference_unique["film_key"].nunique(), 1)
        total_library = max(ratings_df["film_key"].nunique(), 1)

        rows: list[dict[str, Any]] = []
        for item in set(preference_counts.index) | set(library_counts.index):
            preference_count = int(preference_counts.get(item, 0))
            library_count = int(library_counts.get(item, 0))
            if preference_count < 2:
                continue
            preference_share = preference_count / total_preference
            library_share = library_count / total_library
            rows.append(
                {
                    label: item,
                    "preference_count": preference_count,
                    "preference_share": round(preference_share, 4),
                    "library_share": round(library_share, 4),
                    "share_diff": round(preference_share - library_share, 4),
                }
            )
        return sorted(rows, key=lambda row: row["share_diff"], reverse=True)[:12]

    watch_plan_overlap = (
        list_entries_df[(list_entries_df["list_category"] == "watch_plan") & (~list_entries_df["watched"])]
        .groupby("film_key")
        .agg(
            name=("Name", "first"),
            year=("Year", "first"),
            source_count=("list_title", "nunique"),
            source_lists=("list_title", lambda values: sorted(set(values))),
        )
        .reset_index()
        .sort_values(["source_count", "year"], ascending=[False, False])
        .head(20)
    )

    return {
        "list_summary": serialize_frame(
            list_summary.sort_values(["category_order", "items"], ascending=[True, False])[
                [
                    "list_title",
                    "list_category",
                    "list_category_label",
                    "items",
                    "watched_items",
                    "unwatched_items",
                    "avg_rating_of_watched",
                ]
            ]
        ),
        "category_summary": serialize_frame(category_summary),
        "preference_overlaps": serialize_frame(preference_overlaps),
        "preference_country_bias": bias_table("countries", "country"),
        "preference_genre_bias": bias_table("genres", "genre"),
        "watch_plan_overlap": serialize_frame(watch_plan_overlap),
    }


def build_streaming_section(
    ratings_df: pd.DataFrame,
    output_dir: Path,
    max_new_lookups: int,
    max_douban_lookups: int,
    workers: int,
    catalog_timeout: int,
    refresh_cache: bool,
) -> dict[str, Any]:
    try:
        streaming_catalog, provider_warnings = run_with_timeout(
            catalog_timeout,
            lambda: build_streaming_catalog(output_dir),
        )
    except Exception as exc:  # noqa: BLE001
        if should_fallback_to_cached_streaming(exc):
            cached_section = load_cached_streaming_section(output_dir)
            if cached_section is not None:
                cached_section = refresh_cached_streaming_douban_section(
                    cached_section,
                    output_dir=output_dir,
                    max_douban_lookups=max_douban_lookups,
                    workers=max(1, workers // 2),
                    refresh_cache=refresh_cache,
                )
                cached_section = refresh_cached_streaming_watch_state(
                    cached_section,
                    ratings_df=ratings_df,
                    output_dir=output_dir,
                )
                cached_stats = cached_section.setdefault("stats", {})
                cached_stats["fallback_used"] = True
                cached_stats["fallback_reason"] = normalize_cell(exc)
                print(
                    "Streaming catalog fetch failed; falling back to cached streaming data: "
                    f"{normalize_cell(exc)}",
                    file=sys.stderr,
                )
                return cached_section
            print(
                "Streaming catalog fetch failed and no cached streaming snapshot was found; "
                "continuing with an empty streaming section.",
                file=sys.stderr,
            )
            return empty_streaming_section()
        raise

    if streaming_catalog.empty:
        empty_section = empty_streaming_section()
        empty_section["provider_warnings"] = provider_warnings
        return empty_section

    fresh_title_count = int(streaming_catalog["film_key"].nunique()) if "film_key" in streaming_catalog.columns else 0
    cached_for_guard = load_cached_streaming_section(output_dir)
    cached_title_count = int(((cached_for_guard or {}).get("stats") or {}).get("provider_titles") or 0)
    if cached_for_guard and cached_title_count >= 1000 and fresh_title_count < cached_title_count * 0.5:
        cached_section = refresh_cached_streaming_douban_section(
            cached_for_guard,
            output_dir=output_dir,
            max_douban_lookups=max_douban_lookups,
            workers=max(1, workers // 2),
            refresh_cache=refresh_cache,
        )
        cached_section = refresh_cached_streaming_watch_state(
            cached_section,
            ratings_df=ratings_df,
            output_dir=output_dir,
        )
        cached_stats = cached_section.setdefault("stats", {})
        cached_stats["fallback_used"] = True
        cached_stats["fallback_reason"] = (
            f"Fresh streaming catalog had {fresh_title_count} titles; "
            f"cached catalog has {cached_title_count} titles"
        )
        print(
            "Streaming catalog looked incomplete; falling back to cached streaming data: "
            f"{fresh_title_count} fresh titles vs {cached_title_count} cached titles.",
            file=sys.stderr,
        )
        return cached_section

    watched_keys = set(ratings_df["film_key"])
    user_rating_lookup = (
        ratings_df[["film_key", "user_rating"]]
        .drop_duplicates(subset=["film_key"])
        .set_index("film_key")["user_rating"]
        .to_dict()
    )

    aggregated_rows: list[dict[str, Any]] = []
    for streaming_key, grouped in streaming_catalog.groupby("film_key", dropna=False):
        first = grouped.iloc[0]
        provider_links = [
            {
                "provider": row["provider_label"],
                "url": row["justwatch_url"],
            }
            for _, row in (
                grouped.sort_values("provider_label")
                .drop_duplicates(subset=["provider_label"])
                .iterrows()
            )
        ]
        genre_lookup: dict[str, dict[str, Any]] = {}
        for genre_set in grouped["genres"]:
            for genre in ensure_list(genre_set):
                if not isinstance(genre, dict):
                    continue
                code = normalize_cell(genre.get("code"))
                label = normalize_cell(genre.get("label"))
                if not code or not label:
                    continue
                genre_lookup[code] = {
                    "code": code,
                    "slug": normalize_cell(genre.get("slug")),
                    "label": label,
                }
        providers = [item["provider"] for item in provider_links]
        genres = sorted(genre_lookup.values(), key=lambda row: row["label"])
        year = pd.to_numeric(first["year"], errors="coerce")
        aggregated_rows.append(
            {
                "film_key": streaming_key,
                "name": first["name"],
                "year": int(year) if pd.notna(year) else None,
                "runtime_minutes": pd.to_numeric(first["runtime_minutes"], errors="coerce"),
                "genres": genres,
                "genre_labels": [genre["label"] for genre in genres],
                "genre_codes": [genre["code"] for genre in genres],
                "providers": providers,
                "provider_links": provider_links,
                "provider_count": len(providers),
                "exclusive": len(providers) == 1,
                "watched": streaming_key in watched_keys,
                "user_rating": user_rating_lookup.get(streaming_key),
                "imdb_score": pd.to_numeric(grouped["imdb_score"], errors="coerce").max(),
                "imdb_votes": pd.to_numeric(grouped["imdb_votes"], errors="coerce").max(),
                "jw_score": pd.to_numeric(grouped["jw_score"], errors="coerce").max(),
                "tmdb_score": pd.to_numeric(grouped["tmdb_score"], errors="coerce").max(),
                "lookup_priority": (
                    (60 if streaming_key not in watched_keys else 0)
                    + (35 if len(providers) == 1 else 0)
                    + (
                        float(pd.to_numeric(grouped["imdb_score"], errors="coerce").max()) * 100
                        if pd.notna(pd.to_numeric(grouped["imdb_score"], errors="coerce").max())
                        else 0
                    )
                    + (
                        math.log10(float(pd.to_numeric(grouped["imdb_votes"], errors="coerce").max()) + 1) * 8
                        if pd.notna(pd.to_numeric(grouped["imdb_votes"], errors="coerce").max())
                        else 0
                    )
                ),
            }
        )

    streaming_df = pd.DataFrame(aggregated_rows)
    streaming_df = streaming_df.sort_values(
        ["lookup_priority", "imdb_score", "provider_count"],
        ascending=[False, False, True],
    ).reset_index(drop=True)

    cache_path = output_dir / "streaming_letterboxd_cache.json"
    existing_cache = load_json_cache(cache_path)
    valid_cached_keys = {key for key, entry in existing_cache.items() if is_valid_streaming_cache_entry(entry)}
    missing_before = int((~streaming_df["film_key"].isin(valid_cached_keys)).sum())
    lookup_cache = update_streaming_letterboxd_cache(
        streaming_df[["film_key", "name", "year", "runtime_minutes"]],
        cache_path=cache_path,
        max_new_lookups=max_new_lookups,
        workers=workers,
        refresh_cache=refresh_cache,
    )
    lookup_cache = update_streaming_douban_cache(
        streaming_df[["film_key", "name", "year", "runtime_minutes"]],
        cache_path=cache_path,
        max_new_lookups=max_douban_lookups,
        workers=max(1, workers // 2),
        refresh_cache=refresh_cache,
    )

    streaming_df["letterboxd_rating"] = streaming_df["film_key"].map(
        lambda key: lookup_cache.get(key, {}).get("letterboxd_rating")
    )
    streaming_df["letterboxd_rating_count"] = streaming_df["film_key"].map(
        lambda key: lookup_cache.get(key, {}).get("letterboxd_rating_count")
    )
    streaming_df["letterboxd_url"] = streaming_df["film_key"].map(
        lambda key: lookup_cache.get(key, {}).get("letterboxd_url")
    )
    streaming_df["letterboxd_status"] = streaming_df["film_key"].map(
        lambda key: lookup_cache.get(key, {}).get("status", "missing")
    )
    streaming_df["match_name"] = streaming_df["film_key"].map(
        lambda key: lookup_cache.get(key, {}).get("match_name")
    )
    streaming_df["match_year"] = streaming_df["film_key"].map(
        lambda key: lookup_cache.get(key, {}).get("match_year")
    )
    streaming_df["site_average_rating"] = streaming_df["film_key"].map(
        lambda key: lookup_cache.get(key, {}).get("site_average_rating")
    )
    streaming_df["site_rating_count"] = streaming_df["film_key"].map(
        lambda key: lookup_cache.get(key, {}).get("site_rating_count")
    )
    streaming_df["directors"] = streaming_df["film_key"].map(
        lambda key: ensure_list(lookup_cache.get(key, {}).get("directors"))
    )
    streaming_df["actors"] = streaming_df["film_key"].map(
        lambda key: ensure_list(lookup_cache.get(key, {}).get("actors"))
    )
    streaming_df["countries"] = streaming_df["film_key"].map(
        lambda key: ensure_list(lookup_cache.get(key, {}).get("countries"))
    )
    streaming_df["metadata_title"] = streaming_df["film_key"].map(
        lambda key: lookup_cache.get(key, {}).get("metadata_title")
    )
    streaming_df["douban_rating"] = streaming_df["film_key"].map(
        lambda key: lookup_cache.get(key, {}).get("douban_rating")
    )
    streaming_df["douban_rating_count"] = streaming_df["film_key"].map(
        lambda key: lookup_cache.get(key, {}).get("douban_rating_count")
    )
    streaming_df["douban_url"] = streaming_df["film_key"].map(
        lambda key: lookup_cache.get(key, {}).get("douban_url")
    )
    cached_runtime = streaming_df["film_key"].map(
        lambda key: lookup_cache.get(key, {}).get("runtime_minutes")
    )
    streaming_df["runtime_minutes"] = pd.to_numeric(
        cached_runtime.fillna(streaming_df["runtime_minutes"]),
        errors="coerce",
    )
    streaming_df["source_uri"] = streaming_df["letterboxd_url"].apply(normalize_source_uri)
    streaming_df["decade_label"] = (
        streaming_df["year"].dropna().floordiv(10).mul(10).astype("Int64").astype(str) + "s"
    )
    streaming_df.loc[streaming_df["year"].isna(), "decade_label"] = None
    streaming_df["runtime_bucket"] = build_runtime_bucket(streaming_df["runtime_minutes"])
    streaming_df["genres"] = streaming_df.apply(
        lambda row: (
            [
                {
                    "code": genre,
                    "slug": slugify_identifier(genre),
                    "label": genre,
                }
                for genre in normalize_string_list(lookup_cache.get(row["film_key"], {}).get("genres"))
            ]
            if normalize_string_list(lookup_cache.get(row["film_key"], {}).get("genres"))
            else row["genres"]
        ),
        axis=1,
    )
    streaming_df["genre_labels"] = streaming_df["genres"].apply(
        lambda values: [normalize_cell(item.get("label")) for item in ensure_list(values) if isinstance(item, dict)]
    )
    streaming_df["genre_codes"] = streaming_df["genres"].apply(
        lambda values: [normalize_cell(item.get("code")) for item in ensure_list(values) if isinstance(item, dict)]
    )

    def matched_streaming_film_key(row: pd.Series) -> str:
        match_name = normalize_cell(row.get("match_name")) or normalize_cell(row.get("metadata_title")) or normalize_cell(row.get("name"))
        match_year = row.get("match_year")
        if pd.isna(pd.to_numeric(match_year, errors="coerce")):
            match_year = row.get("year")
        return film_key(match_name, match_year)

    def watched_streaming_film_key(row: pd.Series) -> str | None:
        original_key = normalize_cell(row.get("film_key"))
        matched_key = normalize_cell(row.get("matched_film_key"))
        if original_key in watched_keys:
            return original_key
        if matched_key in watched_keys:
            return matched_key
        return None

    streaming_df["matched_film_key"] = streaming_df.apply(matched_streaming_film_key, axis=1)
    streaming_df["watched_film_key"] = streaming_df.apply(watched_streaming_film_key, axis=1)
    streaming_df["watched"] = streaming_df["watched_film_key"].notna()
    streaming_df["user_rating"] = streaming_df["watched_film_key"].map(lambda key: user_rating_lookup.get(key))
    streaming_df["available_on_tracked_platforms"] = True
    streaming_df["availability_status"] = "available"

    represented_watched_keys = {
        normalize_cell(value)
        for value in streaming_df["watched_film_key"].dropna().astype(str).tolist()
        if normalize_cell(value)
    }
    missing_watched_df = ratings_df[~ratings_df["film_key"].isin(represented_watched_keys)].copy()

    def genre_objects_from_labels(values: Any) -> list[dict[str, str]]:
        labels = normalize_string_list(values)
        return [
            {
                "code": label,
                "slug": slugify_identifier(label),
                "label": label,
            }
            for label in labels
        ]

    watched_only_rows: list[dict[str, Any]] = []
    for _, watched_row in missing_watched_df.iterrows():
        watched_key = normalize_cell(watched_row.get("film_key"))
        if not watched_key:
            continue
        watched_year = pd.to_numeric(watched_row.get("Year"), errors="coerce")
        watched_genres = genre_objects_from_labels(watched_row.get("genres"))
        source_uri = normalize_source_uri(watched_row.get("canonical_url")) or normalize_source_uri(watched_row.get("Letterboxd URI"))
        watched_only_rows.append(
            {
                "film_key": watched_key,
                "matched_film_key": watched_key,
                "watched_film_key": watched_key,
                "name": normalize_cell(watched_row.get("Name")),
                "year": int(watched_year) if pd.notna(watched_year) else None,
                "runtime_minutes": pd.to_numeric(watched_row.get("runtime_minutes"), errors="coerce"),
                "genres": watched_genres,
                "genre_labels": [genre["label"] for genre in watched_genres],
                "genre_codes": [genre["code"] for genre in watched_genres],
                "providers": [],
                "provider_links": [],
                "provider_count": 0,
                "exclusive": False,
                "watched": True,
                "user_rating": user_rating_lookup.get(watched_key),
                "imdb_score": None,
                "imdb_votes": None,
                "jw_score": None,
                "tmdb_score": None,
                "lookup_priority": 0,
                "letterboxd_rating": pd.to_numeric(watched_row.get("site_average_rating"), errors="coerce"),
                "letterboxd_rating_count": pd.to_numeric(watched_row.get("site_rating_count"), errors="coerce"),
                "letterboxd_url": source_uri,
                "letterboxd_status": "watched_library",
                "match_name": normalize_cell(watched_row.get("Name")),
                "match_year": int(watched_year) if pd.notna(watched_year) else None,
                "site_average_rating": pd.to_numeric(watched_row.get("site_average_rating"), errors="coerce"),
                "site_rating_count": pd.to_numeric(watched_row.get("site_rating_count"), errors="coerce"),
                "directors": normalize_string_list(watched_row.get("directors")),
                "actors": normalize_string_list(watched_row.get("actors")),
                "countries": normalize_string_list(watched_row.get("countries")),
                "metadata_title": normalize_cell(watched_row.get("Name")),
                "douban_rating": pd.to_numeric(watched_row.get("douban_rating"), errors="coerce"),
                "douban_rating_count": None,
                "douban_url": normalize_source_uri(watched_row.get("douban_url")),
                "source_uri": source_uri,
                "decade_label": normalize_cell(watched_row.get("decade_label")),
                "runtime_bucket": normalize_cell(watched_row.get("runtime_bucket")),
                "available_on_tracked_platforms": False,
                "availability_status": "not_available",
            }
        )

    watched_only_count = len(watched_only_rows)
    if watched_only_rows:
        streaming_df = pd.concat([streaming_df, pd.DataFrame(watched_only_rows)], ignore_index=True, sort=False)

    scored_df = streaming_df[streaming_df["letterboxd_rating"].notna()].copy()
    scored_df = scored_df.sort_values(
        ["letterboxd_rating", "letterboxd_rating_count", "imdb_score"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    scored_df.insert(0, "rank", np.arange(1, len(scored_df) + 1))

    scored_rank_lookup = scored_df.set_index("film_key")["rank"].to_dict()
    streaming_df["rank"] = streaming_df["film_key"].map(scored_rank_lookup)

    genre_rows: list[dict[str, Any]] = []
    exploded_genres = streaming_df[["film_key", "watched", "genres"]].explode("genres")
    exploded_genres = exploded_genres[exploded_genres["genres"].notna()]
    for _, genre_group in exploded_genres.groupby(
        exploded_genres["genres"].apply(
            lambda value: normalize_cell(value.get("label")) or normalize_cell(value.get("code"))
        )
    ):
        sample = genre_group.iloc[0]["genres"]
        label = normalize_cell(sample.get("label")) or normalize_cell(sample.get("code"))
        genre_rows.append(
            {
                "code": label,
                "slug": slugify_identifier(label),
                "label": label,
                "titles": int(genre_group["film_key"].nunique()),
                "watched_titles": int(genre_group[genre_group["watched"]]["film_key"].nunique()),
            }
        )
    genre_options = sorted(genre_rows, key=lambda row: (-row["titles"], row["label"]))

    summary_rows: list[dict[str, Any]] = []
    warning_lookup = {row["provider"]: row["note"] for row in provider_warnings}
    for provider in STREAMING_PROVIDERS:
        scoped = streaming_df[streaming_df["providers"].apply(lambda values: provider["label"] in values)]
        scored_scoped = scoped[scoped["letterboxd_rating"].notna()]
        douban_scoped = scoped[scoped["douban_rating"].notna()]
        watched_scoped = scoped[scoped["watched"] & scoped["user_rating"].notna()]
        summary_rows.append(
            {
                "provider": provider["label"],
                "scope_label": provider.get("scope_label"),
                "catalog_note": warning_lookup.get(provider["label"]),
                "available_titles": int(len(scoped)),
                "indexed_titles": int(len(scored_scoped)),
                "watched_titles": int(scoped["watched"].sum()),
                "unwatched_titles": int((~scoped["watched"]).sum()),
                "exclusive_titles": int(scoped["exclusive"].sum()),
                "avg_letterboxd_rating": round(float(scored_scoped["letterboxd_rating"].mean()), 3)
                if not scored_scoped.empty
                else None,
                "avg_douban_rating": round(float(douban_scoped["douban_rating"].mean()), 3)
                if not douban_scoped.empty
                else None,
                "avg_user_rating": round(float(watched_scoped["user_rating"].mean()), 3)
                if not watched_scoped.empty
                else None,
            }
        )

    row_export = streaming_df[
        [
            "rank",
            "film_key",
            "matched_film_key",
            "watched_film_key",
            "name",
            "year",
            "genres",
            "genre_labels",
            "genre_codes",
            "source_uri",
            "directors",
            "actors",
            "countries",
            "runtime_minutes",
            "runtime_bucket",
            "decade_label",
            "providers",
            "provider_links",
            "provider_count",
            "exclusive",
            "available_on_tracked_platforms",
            "availability_status",
            "watched",
            "user_rating",
            "letterboxd_rating",
            "letterboxd_rating_count",
            "letterboxd_url",
            "letterboxd_status",
            "site_average_rating",
            "site_rating_count",
            "douban_rating",
            "douban_url",
            "imdb_score",
            "imdb_votes",
        ]
    ].sort_values(
        ["letterboxd_rating", "letterboxd_rating_count", "imdb_score"],
        ascending=[False, False, False],
        na_position="last",
    )

    available_mask = streaming_df["available_on_tracked_platforms"].fillna(False).astype(bool)
    provider_scored_count = int((available_mask & streaming_df["letterboxd_rating"].notna()).sum())

    top_unwatched = serialize_frame(
        scored_df[~scored_df["watched"]][["rank", "name", "year", "providers", "letterboxd_rating"]].head(20)
    )

    return {
        "summary": summary_rows,
        "rows": serialize_frame(row_export),
        "genre_options": genre_options,
        "provider_warnings": provider_warnings,
        "stats": {
            "provider_titles": int(available_mask.sum()),
            "indexed_titles": provider_scored_count,
            "scored_titles": int(len(scored_df)),
            "total_rows": int(len(streaming_df)),
            "watched_library_titles": int(len(ratings_df)),
            "watched_not_available_titles": int(watched_only_count),
            "watched_titles": int(streaming_df["watched"].sum()),
            "unwatched_titles": int((~streaming_df["watched"]).sum()),
            "exclusive_titles": int(streaming_df["exclusive"].sum()),
            "warning_count": int(len(provider_warnings)),
            "new_lookups_requested": int(min(max_new_lookups, missing_before)) if max_new_lookups >= 0 else missing_before,
        },
        "top_unwatched": top_unwatched,
    }


def load_cached_daily_signal_section(output_dir: Path) -> dict[str, Any] | None:
    candidate_paths = [
        output_dir / "custom-report-data.json",
        output_dir / "share-site" / "custom-report-data.json",
        Path.cwd() / "custom-report-data.json",
        Path.cwd() / "share-site" / "custom-report-data.json",
    ]
    seen_paths: set[Path] = set()
    for candidate in candidate_paths:
        path = candidate.resolve()
        if path in seen_paths or not path.exists():
            continue
        seen_paths.add(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        daily_signal = payload.get("daily_signal")
        if isinstance(daily_signal, dict) and daily_signal.get("items"):
            return daily_signal
    return None


def clean_html_excerpt(value: Any) -> str:
    text = normalize_cell(value)
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def stable_mean_score(avg: float, count: int, global_mean: float, prior: int = 8) -> float:
    return float((avg * count + global_mean * prior) / (count + prior))


def format_year_value(value: Any) -> str:
    numeric = pd.to_numeric(value, errors="coerce")
    return str(int(numeric)) if pd.notna(numeric) else "unknown year"


def fetch_rss_feed_entries(feed: dict[str, str]) -> list[dict[str, Any]]:
    xml_text = urlopen(
        Request(feed["url"], headers={"User-Agent": "Mozilla/5.0"}),
        timeout=30,
    ).read()
    root = ET.fromstring(xml_text)
    entries: list[dict[str, Any]] = []
    for item in root.findall(".//item")[:10]:
        title = clean_html_excerpt(item.findtext("title"))
        link = normalize_cell(item.findtext("link"))
        description = clean_html_excerpt(item.findtext("description"))
        pub_date = normalize_cell(item.findtext("pubDate"))
        published_at = None
        if pub_date:
            try:
                published_at = parsedate_to_datetime(pub_date).isoformat()
            except (TypeError, ValueError, IndexError, OverflowError):
                published_at = None
        if not title or not link:
            continue
        entries.append(
            {
                "source": feed["label"],
                "title": title,
                "url": link,
                "summary": description,
                "published_at": published_at,
            }
        )
    return entries


def classify_news_entry(row: dict[str, Any]) -> str:
    haystack = normalize_loose_title(" ".join([row.get("title", ""), row.get("summary", "")]))
    if any(token in haystack for token in ["box office", "gross", "record", "opening weekend"]):
        return "票房 / 行业"
    if any(token in haystack for token in ["festival", "cannes", "venice", "berlin", "oscars", "awards", "wins", "winner"]):
        return "奖项 / 影展"
    if any(token in haystack for token in ["director", "filmmaker", "auteur", "sets", "slate", "casts", "starring"]):
        return "导演 / 项目"
    if any(token in haystack for token in ["trailer", "review", "release", "opens", "premiere"]):
        return "近期作品"
    return "行业动态"


def daily_relevance_sentence(signals: list[str]) -> str:
    if not signals:
        return "可作为今天的电影行业观察。"
    return f"相关线索：{'、'.join(signals[:2])}。"


def build_daily_signal_section(
    ratings_df: pd.DataFrame,
    recommendations: pd.DataFrame,
    streaming: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    try:
        global_mean = float(ratings_df["user_rating"].dropna().mean()) if not ratings_df.empty else 3.5
        genre_signal_frame = (
            ratings_df.explode("genres")
            .dropna(subset=["genres"])
            .groupby("genres")
            .agg(avg_rating=("user_rating", "mean"), films=("film_key", "nunique"))
            .reset_index()
        )
        genre_signal_frame["stable_score"] = genre_signal_frame.apply(
            lambda row: stable_mean_score(float(row["avg_rating"]), int(row["films"]), global_mean),
            axis=1,
        )
        top_genres = (
            genre_signal_frame[genre_signal_frame["films"] >= 8]
            .sort_values(["stable_score", "films"], ascending=[False, False])
            .head(6)["genres"]
            .astype(str)
            .tolist()
        )
        region_signal_frame = (
            ratings_df.explode("countries")
            .dropna(subset=["countries"])
            .groupby("countries")
            .agg(avg_rating=("user_rating", "mean"), films=("film_key", "nunique"))
            .reset_index()
        )
        region_signal_frame["stable_score"] = region_signal_frame.apply(
            lambda row: stable_mean_score(float(row["avg_rating"]), int(row["films"]), global_mean),
            axis=1,
        )
        top_regions = (
            region_signal_frame[region_signal_frame["films"] >= 5]
            .sort_values(["stable_score", "films"], ascending=[False, False])
            .head(5)["countries"]
            .astype(str)
            .tolist()
        )
        top_directors = (
            ratings_df.explode("directors")
            .dropna(subset=["directors"])
            .groupby("directors")
            .agg(avg_rating=("user_rating", "mean"), films=("film_key", "nunique"))
            .query("films >= 3")
            .reset_index()
        )
        top_directors["stable_score"] = top_directors.apply(
            lambda row: stable_mean_score(float(row["avg_rating"]), int(row["films"]), global_mean),
            axis=1,
        )
        top_directors = (
            top_directors.sort_values(["stable_score", "films"], ascending=[False, False])
            .head(5)
            ["directors"]
            .astype(str)
            .tolist()
        )
        top_titles = unique_preserve_order(
            recommendations.head(20)["name"].astype(str).tolist()
            + [row["name"] for row in streaming.get("top_unwatched", [])[:10] if normalize_cell(row.get("name"))]
        )

        news_rows: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for feed in NEWS_FEEDS:
            for entry in fetch_rss_feed_entries(feed):
                if entry["url"] in seen_urls:
                    continue
                seen_urls.add(entry["url"])
                news_rows.append(entry)

        scored_rows: list[dict[str, Any]] = []
        for row in news_rows:
            haystack = normalize_loose_title(" ".join([row["title"], row["summary"]]))
            if not haystack:
                continue
            matched_signals: list[str] = []
            score = 0.0

            for title in top_titles:
                normalized = normalize_loose_title(title)
                if normalized and len(normalized) >= 4 and normalized in haystack:
                    matched_signals.append(f"片名: {title}")
                    score += 3.0

            for director in top_directors:
                normalized = normalize_loose_title(director)
                if normalized and normalized in haystack:
                    matched_signals.append(f"创作者: {director}")
                    score += 2.2

            for genre in top_genres:
                normalized = normalize_loose_title(genre)
                if normalized and normalized in haystack:
                    matched_signals.append(f"类型: {genre}")
                    score += 1.6

            for region in top_regions:
                normalized = normalize_loose_title(region)
                if normalized and normalized in haystack:
                    matched_signals.append(f"地区: {region}")
                    score += 1.3

            category = classify_news_entry(row)
            if category in {"奖项 / 影展", "票房 / 行业", "近期作品"}:
                score += 0.9
            if category == "导演 / 项目":
                score += 0.7

            scored_rows.append(
                {
                    **row,
                    "category": category,
                    "match_score": round(score, 2),
                    "matched_signals": unique_preserve_order(matched_signals)[:4],
                }
            )

        scored_rows = sorted(
            scored_rows,
            key=lambda row: (
                row["match_score"],
                normalize_cell(row.get("published_at")),
            ),
            reverse=True,
        )
        selected_rows: list[dict[str, Any]] = []
        seen_categories: set[str] = set()
        for row in scored_rows:
            if row["category"] in seen_categories and len(selected_rows) < 4:
                continue
            selected_rows.append(row)
            seen_categories.add(row["category"])
            if len(selected_rows) >= 4:
                break
        if not selected_rows:
            selected_rows = sorted(
                news_rows,
                key=lambda row: normalize_cell(row.get("published_at")),
                reverse=True,
            )[:4]

        fun_facts: list[str] = []
        if top_directors:
            fun_facts.append(f"导演线索：当前评分样本里最稳定的导演信号包括 {', '.join(top_directors[:3])}。")
        if top_genres:
            fun_facts.append(f"类型线索：按样本量校正后，高分偏好最稳定的类型包括 {', '.join(top_genres[:3])}。")
        if streaming.get("top_unwatched"):
            top_streaming = streaming["top_unwatched"][0]
            providers = ", ".join(ensure_list(top_streaming.get("providers"))[:2])
            fun_facts.append(
                f"补片线索：当前可看未看片里，{top_streaming.get('name')} ({format_year_value(top_streaming.get('year'))}) 的 Letterboxd 分数最高，可在 {providers} 找到。"
            )

        return {
            "generated_at": pd.Timestamp.now("UTC").isoformat(),
            "items": [
                {
                    "category": row.get("category") or classify_news_entry(row),
                    "headline": row["title"],
                    "source": row["source"],
                    "url": row["url"],
                    "published_at": row.get("published_at"),
                    "summary": f"{row['title']}。{daily_relevance_sentence(row.get('matched_signals', []))}",
                    "matched_signals": row.get("matched_signals", []),
                    "match_score": row.get("match_score"),
                }
                for row in selected_rows
            ],
            "fun_facts": fun_facts[:4],
        }
    except Exception as exc:  # noqa: BLE001
        cached = load_cached_daily_signal_section(output_dir)
        if cached is not None:
            cached["fallback_reason"] = normalize_cell(exc)
            return cached
        return {
            "generated_at": pd.Timestamp.now("UTC").isoformat(),
            "items": [],
            "fun_facts": [],
            "fallback_reason": normalize_cell(exc),
        }


def build_custom_insights(
    genre_country: dict[str, Any],
    tags: dict[str, Any],
    reviews: dict[str, Any],
    lists: dict[str, Any],
    streaming: dict[str, Any],
    recommendations: pd.DataFrame,
) -> list[str]:
    insights: list[str] = []

    animation_profile = genre_country["genre_profiles"].get("Animation") or genre_country["genre_profiles"].get("Animated")
    if animation_profile:
        top = animation_profile[0]
        insights.append(
            f"在动画样本中，{top['country']} 是占比最高的来源地区，平均分为 {top['avg_rating']:.1f}。"
        )

    if genre_country["top_combos"]:
        combo = genre_country["top_combos"][0]
        insights.append(
            f"当前加权表现最强的国家 / 地区 × 类型组合之一是 {combo['country']} × {combo['genre']}，样本 {combo['films']} 部，平均分 {combo['avg_rating']:.1f}。"
        )

    if tags["social_stats"]:
        best_social = max(tags["social_stats"], key=lambda row: (row["avg_rating"], row["watches"]))
        insights.append(
            f"在 tags 记录的观影语境里，{best_social['social_context']} 的平均分最高，为 {best_social['avg_rating']:.1f}。"
        )

    social_delta = tags["social_genre_delta"]
    if social_delta:
        top_delta = max(social_delta, key=lambda row: row["diff"])
        if top_delta["diff"] > 0:
            insights.append(
                f"社交观影抬升最明显的类型是 {top_delta['genre']}，比 solo 观影高 {top_delta['diff']:.1f} 分。"
            )
        else:
            insights.append(
                f"当前样本里社交观影未显示稳定加分；最接近持平的类型是 {top_delta['genre']}，与 solo 观影差值 {top_delta['diff']:.1f} 分。"
            )

    if reviews["positive_terms"]:
        pos = reviews["positive_terms"][0]["term"]
        neg = reviews["negative_terms"][0]["term"] if reviews["negative_terms"] else "logic"
        insights.append(f"高分评论中更常出现的词是 {pos}，低分评论中更常出现的词是 {neg}。")

    if reviews["theme_stats"]:
        theme = max(reviews["theme_stats"], key=lambda row: row["avg_rating"])
        insights.append(
            f"提到 {theme['theme']} 的评论在当前样本中的平均分为 {theme['avg_rating']:.1f}。"
        )

    if lists["preference_country_bias"]:
        bias = lists["preference_country_bias"][0]
        insights.append(
            f"偏好声明型 lists 相对整个片库最明显地偏向 {bias['country']}。"
        )

    if streaming["top_unwatched"]:
        top_streaming = streaming["top_unwatched"][0]
        providers = ", ".join(top_streaming["providers"][:2])
        insights.append(
            f"当前可看且评分较高的未看影片里，{top_streaming['name']} ({int(top_streaming['year'])}) 的优先级较高，可在 {providers} 找到。"
        )

    if not recommendations.empty:
        hidden = recommendations[
            (~recommendations["in_watchlist"]) & (~recommendations["in_user_lists"])
        ]
        top_row = hidden.iloc[0] if not hidden.empty else recommendations.iloc[0]
        providers = ", ".join(top_row["providers"][:2])
        source = providers if providers else ", ".join(top_row["source_lists"][:2])
        insights.append(
            f"在 watchlist 和自建 lists 之外，{top_row['name']} ({int(top_row['year'])}) 是当前外部发现池里信号较强的一部，主要线索来自 {source}。"
        )

    return insights


def json_for_html(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def rerank_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        updated = dict(row)
        updated["rank"] = index
        ranked.append(updated)
    return ranked


def format_static_value(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, np.integer)):
        return f"{int(value):,}"
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if abs(number) >= 100 or number.is_integer():
            return f"{number:,.0f}"
        return f"{number:.2f}".rstrip("0").rstrip(".")
    if isinstance(value, list):
        return " / ".join(format_static_value(item) for item in value if format_static_value(item) != "—") or "—"
    return normalize_cell(value) or "—"


def render_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    if not rows:
        return "<p class='muted'>暂无数据。</p>"
    head = "".join(f"<th>{html.escape(label)}</th>" for _, label in columns)
    body_rows = []
    for row in rows:
        body_rows.append(
            "<tr>"
            + "".join(
                f"<td>{html.escape(format_static_value(row.get(key)))}</td>"
                for key, _label in columns
            )
            + "</tr>"
        )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def render_daily_signal_items(signal: dict[str, Any]) -> str:
    items = signal.get("items") or []
    if not items:
        return "<p class='muted'>暂无当日信号。</p>"
    cards = []
    for item in items:
        tags = "".join(
            f"<span class='signal-tag'>{html.escape(tag)}</span>"
            for tag in ensure_list(item.get("matched_signals"))[:4]
        )
        published = normalize_cell(item.get("published_at"))[:10] if normalize_cell(item.get("published_at")) else "最近"
        headline = normalize_cell(item.get("headline")) or normalize_cell(item.get("title")) or "Untitled"
        summary = normalize_cell(item.get("summary"))
        if summary.startswith(headline):
            summary = summary[len(headline):].lstrip("。.:： ")
        cards.append(
            "<article class='signal-card'>"
            f"<div class='signal-meta'>{html.escape(item.get('category', '今日线索'))} · {html.escape(item.get('source', ''))} · {html.escape(published)}</div>"
            f"<h3><a href=\"{html.escape(item.get('url', '#'))}\" target=\"_blank\" rel=\"noopener noreferrer\">{html.escape(headline)}</a></h3>"
            f"<p>{html.escape(summary or '可作为今天的电影行业观察。')}</p>"
            f"<a class='signal-source' href=\"{html.escape(item.get('url', '#'))}\" target=\"_blank\" rel=\"noopener noreferrer\">Source</a>"
            f"<div class='signal-tags'>{tags}</div>"
            "</article>"
        )
    return "".join(cards)


def build_html(payload: dict[str, Any]) -> str:
    username = payload["profile"].get("username") or "Letterboxd"
    share_title = f"{username}'s Letterboxd Custom Report"
    share_description = (
        "A shareable Letterboxd research report focused on genre-region patterns, streaming availability, review language, custom lists, and recommendation signals."
    )
    streaming_provider_labels = "、".join(provider["label"] for provider in STREAMING_PROVIDERS)
    initial_genre = payload["genre_country"]["top_genres"][0] if payload["genre_country"]["top_genres"] else ""
    insights_html = "".join(
        "<article class='insight-card'>"
        f"<div class='kicker'>Signal {index}</div>"
        f"<p>{html.escape(text)}</p>"
        "</article>"
        for index, text in enumerate(payload["custom_insights"], start=1)
    )
    daily_signal_html = render_daily_signal_items(payload.get("daily_signal") or {})
    daily_signal_facts = (payload.get("daily_signal") or {}).get("fun_facts", [])
    daily_signal = payload.get("daily_signal") or {}
    daily_signal_updated = normalize_cell(daily_signal.get("generated_at"))[:10] or "—"
    daily_signal_item_count = len(ensure_list(daily_signal.get("items")))
    daily_signal_fact_count = len(ensure_list(daily_signal.get("fun_facts")))
    watched_douban = payload.get("watched_douban") or {}
    watched_douban_stats = watched_douban.get("stats") or {}
    watched_douban_coverage = f"{float(watched_douban_stats.get('coverage') or 0) * 100:.1f}%"
    daily_signal_fact_html = (
        "".join(
            "<article class='insight-card'>"
            f"<div class='kicker'>Film fact {index}</div>"
            f"<p>{html.escape(text)}</p>"
            "</article>"
            for index, text in enumerate(daily_signal_facts, start=1)
        )
        if daily_signal_facts
        else "<p class='muted'>暂无新的摘要条目。</p>"
    )
    list_summary_html = render_table(
        payload["lists"]["list_summary"][:10],
        [
            ("list_title", "List"),
            ("list_category_label", "Intent"),
            ("items", "Items"),
            ("watched_items", "Watched"),
            ("unwatched_items", "Unwatched"),
        ],
    )
    preference_overlap_html = render_table(
        payload["lists"]["preference_overlaps"][:10],
        [
            ("name", "Film"),
            ("year", "Year"),
            ("appearances", "Preference lists"),
            ("source_lists", "Lists"),
        ],
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(share_title)}</title>
  <meta name="description" content="{html.escape(share_description)}">
  <meta name="theme-color" content="#17233b">
  <meta property="og:type" content="website">
  <meta property="og:title" content="{html.escape(share_title)}">
  <meta property="og:description" content="{html.escape(share_description)}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{html.escape(share_title)}">
  <meta name="twitter:description" content="{html.escape(share_description)}">
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Fraunces:wght@600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
    :root {{
      --bg: #f6f1e7;
      --paper: #fffdf8;
      --ink: #17233b;
      --muted: #5b6472;
      --accent: #c48a3a;
      --accent-soft: #f3e6d2;
      --line: #dcccb4;
      --card: #f9f5ed;
      --teal: #2d6f8e;
      --rose: #b75b49;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Avenir Next", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(196,138,58,0.14), transparent 30%),
        linear-gradient(180deg, #fcfaf6 0%, var(--bg) 100%);
      color: var(--ink);
      overflow-x: hidden;
    }}
    .page {{
      width: min(1380px, calc(100vw - 32px));
      margin: 20px auto 48px;
    }}
    h1, h2, h3, p, li, td, th, label, .metric .label, .metric .value {{
      overflow-wrap: normal;
      word-break: normal;
      hyphens: none;
    }}
    .hero {{
      background: linear-gradient(130deg, #15223b 0%, #1d3357 70%, #25486d 100%);
      color: white;
      border-radius: 24px;
      padding: 28px 30px;
      box-shadow: 0 24px 70px rgba(21,34,59,0.18);
    }}
    .hero h1 {{
      margin: 0 0 8px;
      font-family: "Fraunces", Georgia, serif;
      font-size: clamp(2rem, 4vw, 3.4rem);
      line-height: 0.95;
    }}
    .hero p {{
      max-width: 900px;
      margin: 0;
      color: rgba(255,255,255,0.86);
      font-size: 1rem;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 170px), 1fr));
      gap: 14px;
      margin-top: 20px;
    }}
    .metric {{
      background: rgba(255,255,255,0.08);
      border: 1px solid rgba(255,255,255,0.12);
      border-radius: 18px;
      padding: 14px 16px;
      backdrop-filter: blur(8px);
    }}
    .metric .label {{
      font-size: 0.82rem;
      color: rgba(255,255,255,0.72);
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}
    .metric .value {{
      font-size: 1.7rem;
      font-weight: 700;
      margin-top: 6px;
    }}
    .section .metric {{
      background: #fffaf2;
      border-color: var(--line);
      backdrop-filter: none;
    }}
    .section .metric .label {{
      color: var(--muted);
    }}
    .section .metric .value {{
      color: var(--ink);
    }}
    .section {{
      margin-top: 26px;
      background: var(--paper);
      border: 1px solid rgba(23,35,59,0.06);
      border-radius: 24px;
      padding: 24px;
      box-shadow: 0 12px 36px rgba(23,35,59,0.06);
      overflow: hidden;
    }}
    .section h2 {{
      margin: 0 0 8px;
      font-family: "Fraunces", Georgia, serif;
      font-size: 1.8rem;
      color: var(--ink);
    }}
    .section p.lead {{
      margin: 0 0 16px;
      color: var(--muted);
    }}
    .insights {{
      padding-left: 20px;
      margin: 10px 0 0;
      color: var(--ink);
    }}
    .insights li {{
      margin-bottom: 10px;
      line-height: 1.45;
    }}
    .controls {{
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
      margin: 6px 0 16px;
    }}
    .controls label,
    .filter-group-label,
    .pill-group button,
    .metric .label,
    .metric .value {{
      white-space: nowrap;
    }}
    .controls select, .controls button {{
      border-radius: 999px;
      border: 1px solid var(--line);
      background: var(--card);
      color: var(--ink);
      padding: 10px 14px;
      font-size: 0.95rem;
      cursor: pointer;
      min-width: 0;
      max-width: 100%;
    }}
    .filter-group {{
      display: grid;
      gap: 8px;
      margin: 8px 0 16px;
    }}
    .filter-group-label {{
      font-size: 0.92rem;
      color: var(--muted);
    }}
    .pill-group {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .pill-group button {{
      border-radius: 999px;
      border: 1px solid var(--line);
      background: #fff9ef;
      color: var(--ink);
      padding: 8px 12px;
      font-size: 0.9rem;
      cursor: pointer;
    }}
    .pill-group button.active {{
      background: var(--ink);
      border-color: var(--ink);
      color: white;
    }}
    .grid-2 {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr));
      gap: 18px;
    }}
    .grid-3 {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr));
      gap: 18px;
    }}
    .grid-2 > *,
    .grid-3 > * {{
      min-width: 0;
    }}
    .plot {{
      background: var(--card);
      border: 1px solid rgba(23,35,59,0.07);
      border-radius: 18px;
      min-height: 320px;
      padding: 8px;
      overflow: hidden;
      width: 100%;
      max-width: 100%;
    }}
    .plot > div,
    .js-plotly-plot,
    .plot-container,
    .svg-container {{
      max-width: 100% !important;
    }}
    .mini-card {{
      background: linear-gradient(180deg, #fffaf2 0%, #f7efe2 100%);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
      min-width: 0;
    }}
    .mini-card h3 {{
      margin: 0 0 8px;
      font-size: 1rem;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.92rem;
      table-layout: auto;
    }}
    #streaming-table,
    #watched-douban-table,
    #recommendation-table {{
      min-width: 1180px;
    }}
    #genre-country-table {{
      min-width: 720px;
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid rgba(23,35,59,0.08);
      text-align: left;
      vertical-align: top;
      word-break: normal;
      overflow-wrap: normal;
      white-space: nowrap;
    }}
    #streaming-table th:nth-child(1),
    #streaming-table td:nth-child(1),
    #streaming-table th:nth-child(3),
    #streaming-table td:nth-child(3),
    #streaming-table th:nth-child(6),
    #streaming-table td:nth-child(6),
    #streaming-table th:nth-child(7),
    #streaming-table td:nth-child(7),
    #streaming-table th:nth-child(8),
    #streaming-table td:nth-child(8),
    #streaming-table th:nth-child(10),
    #streaming-table td:nth-child(10),
    #streaming-table th:nth-child(11),
    #streaming-table td:nth-child(11),
    #recommendation-table th:nth-child(1),
    #recommendation-table td:nth-child(1),
    #recommendation-table th:nth-child(3),
    #recommendation-table td:nth-child(3),
    #recommendation-table th:nth-child(5),
    #recommendation-table td:nth-child(5),
    #recommendation-table th:nth-child(6),
    #recommendation-table td:nth-child(6),
    #recommendation-table th:nth-child(7),
    #recommendation-table td:nth-child(7) {{
      white-space: nowrap;
      overflow-wrap: normal;
    }}
    th {{
      background: var(--accent-soft);
      position: sticky;
      top: 0;
      white-space: nowrap;
    }}
    .table-wrap {{
      overflow: auto;
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
      max-width: 100%;
      max-height: 420px;
      border: 1px solid rgba(23,35,59,0.08);
      border-radius: 18px;
      background: var(--paper);
    }}
    .muted {{
      color: var(--muted);
    }}
    .provider-cards {{
      margin-top: 16px;
    }}
    .brief-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr));
      gap: 12px;
      margin-top: 16px;
    }}
    .insight-card {{
      background: #fffaf2;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
      min-height: 0;
    }}
    .insight-card .kicker {{
      color: var(--muted);
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      margin-bottom: 8px;
    }}
    .insight-card p {{
      margin: 0;
      line-height: 1.45;
    }}
    .provider-card-stat {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px 14px;
      margin-top: 10px;
      font-size: 0.92rem;
    }}
    .provider-card-stat strong {{
      display: block;
      font-size: 1.15rem;
      color: var(--ink);
    }}
    .provider-note {{
      margin-top: 10px;
      color: var(--muted);
      font-size: 0.84rem;
      line-height: 1.45;
    }}
    .results-summary {{
      margin: -6px 0 12px;
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .subtle-note {{
      margin: -4px 0 12px;
      color: var(--muted);
      font-size: 0.84rem;
      line-height: 1.45;
    }}
    .signal-card {{
      padding: 14px 0;
      border-bottom: 1px solid rgba(23,35,59,0.08);
    }}
    .daily-meta-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin: 8px 0 10px;
    }}
    .daily-meta-grid div {{
      border: 1px solid rgba(23,35,59,0.08);
      border-radius: 12px;
      background: #fffaf2;
      padding: 8px 10px;
      min-width: 0;
    }}
    .daily-meta-grid strong {{
      display: block;
      color: var(--ink);
      font-size: 1rem;
      white-space: nowrap;
    }}
    .daily-meta-grid span {{
      display: block;
      color: var(--muted);
      font-size: 0.78rem;
      white-space: nowrap;
    }}
    .signal-card:last-child {{
      border-bottom: 0;
      padding-bottom: 0;
    }}
    .signal-card h3 {{
      margin: 4px 0 6px;
      font-size: 1rem;
      line-height: 1.35;
    }}
    .signal-card p {{
      margin: 0;
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.5;
    }}
    .signal-card a {{
      color: var(--ink);
      text-decoration: none;
    }}
    .signal-source {{
      display: inline-block;
      margin-top: 6px;
      color: var(--teal) !important;
      font-size: 0.86rem;
      font-weight: 600;
    }}
    .signal-meta {{
      color: var(--muted);
      font-size: 0.82rem;
      letter-spacing: 0.02em;
      text-transform: uppercase;
    }}
    .signal-tags {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 8px;
    }}
    .signal-tag {{
      display: inline-flex;
      align-items: center;
      padding: 4px 8px;
      border-radius: 999px;
      background: #efe7d9;
      color: var(--ink);
      font-size: 0.8rem;
    }}
    .inline-links a {{
      color: var(--teal);
      text-decoration: none;
      font-weight: 500;
      white-space: nowrap;
    }}
    .language-toggle {{
      position: fixed;
      top: 14px;
      right: 14px;
      z-index: 30;
      display: inline-flex;
      gap: 4px;
      padding: 5px;
      border: 1px solid rgba(255,255,255,0.35);
      border-radius: 999px;
      background: rgba(23,35,59,0.86);
      box-shadow: 0 12px 30px rgba(23,35,59,0.18);
      backdrop-filter: blur(12px);
    }}
    .language-toggle button {{
      border: 0;
      border-radius: 999px;
      padding: 7px 10px;
      background: transparent;
      color: rgba(255,255,255,0.78);
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
    }}
    .language-toggle button.active {{
      background: #fffaf2;
      color: var(--ink);
    }}
    .footer {{
      margin-top: 20px;
      color: var(--muted);
      font-size: 0.92rem;
    }}
    @media (max-width: 768px) {{
      .page {{
        width: min(100vw - 20px, 1380px);
        margin: 10px auto 32px;
      }}
      .hero, .section {{
        padding: 18px;
        border-radius: 20px;
      }}
      .controls {{
        gap: 10px;
      }}
      .controls label {{
        width: auto;
      }}
      .controls select {{
        width: auto;
      }}
      .language-toggle {{
        position: sticky;
        top: 8px;
        float: right;
        margin: 8px 8px -4px 0;
      }}
      .table-wrap {{
        max-height: 360px;
      }}
    }}
  </style>
</head>
<body>
  <div class="language-toggle" role="group" aria-label="Language">
    <button type="button" data-language-choice="zh" class="active">中文</button>
    <button type="button" data-language-choice="en">EN</button>
  </div>
  <div class="page">
    <section class="hero">
      <h1>Letterboxd<br>Custom Research Desk</h1>
      <p data-i18n="heroLead">这个页面汇总的是 Letterboxd 原生会员页之外更适合横向比较的观察维度，包括国家 / 地区 × 类型结构、加拿大流媒体可看范围、观影语境标签、review 用词、lists 意图，以及不限于 watchlist 的候选推荐。</p>
      <div class="metrics">
        <div class="metric"><div class="label" data-i18n="ratedFilms">Rated films</div><div class="value">{payload['metrics']['unique_rated_films']}</div></div>
        <div class="metric"><div class="label" data-i18n="watchEvents">Watch events</div><div class="value">{payload['metrics']['watch_events']}</div></div>
        <div class="metric"><div class="label" data-i18n="taggedWatches">Tagged watches</div><div class="value">{payload['metrics']['tagged_watch_events']}</div></div>
        <div class="metric"><div class="label" data-i18n="writtenReviews">Written reviews</div><div class="value">{payload['reviews']['stats']['review_count']}</div></div>
        <div class="metric"><div class="label" data-i18n="exportedLists">Exported lists</div><div class="value">{payload['metrics']['custom_lists']}</div></div>
        <div class="metric"><div class="label" data-i18n="unseenCandidates">Unseen candidates</div><div class="value">{payload['metrics']['candidate_pool_size']}</div></div>
        <div class="metric"><div class="label" data-i18n="doubanMatched">Douban matched</div><div class="value">{payload['metrics']['douban_rated_titles']}</div></div>
        <div class="metric"><div class="label" data-i18n="streamingIndexed">Streaming indexed</div><div class="value">{payload['metrics']['streaming_indexed_titles']}</div></div>
      </div>
    </section>

    <section class="section">
      <h2 data-i18n="tasteBriefTitle">Today's Taste Brief</h2>
      <p class="lead" data-i18n="tasteBriefLead">本区把最新 Letterboxd 数据、可看片单和电影行业信号压缩成可快速阅读的判断线索。</p>
      <div class="brief-grid">{insights_html}</div>
      <div class="grid-2" style="margin-top:18px;">
        <div class="mini-card">
          <h3 data-i18n="dailyRadarTitle">Daily Film Radar</h3>
          <p class="lead" data-i18n="dailyRadarLead">每天从电影新闻源中提取作品、导演、奖项和产业动态，只保留能提供补片或理解行业的短句。</p>
          <div class="daily-meta-grid">
            <div><strong>{html.escape(daily_signal_updated)}</strong><span>updated</span></div>
            <div><strong>{daily_signal_item_count}</strong><span>signals</span></div>
            <div><strong>{daily_signal_fact_count}</strong><span>facts</span></div>
          </div>
          {daily_signal_html}
        </div>
        <div class="mini-card">
          <h3 data-i18n="filmFactsTitle">Film Facts</h3>
          <p class="lead" data-i18n="filmFactsLead">这些条目来自你的评分、tags、lists 和当前可看目录，会随每日同步更新。</p>
          <div class="brief-grid">{daily_signal_fact_html}</div>
        </div>
      </div>
    </section>

    <section class="section">
      <h2 data-i18n="doubanCoverageTitle">Watched Films: Douban Coverage</h2>
      <p class="lead" data-i18n="doubanCoverageLead">本区为已评分影片补齐豆瓣评分，并将你的评分、Letterboxd 均分与豆瓣 10 分制评分放在同一张表内对照。匹配优先使用 IMDb / Douban subject ID，并以公开豆瓣电影数据索引补齐历史评分；live Douban API 只作为可用时的增量来源。</p>
      <div class="metrics">
        <div class="metric"><div class="label" data-i18n="matchedWatchedFilms">Matched watched films</div><div class="value">{watched_douban_stats.get('douban_rated_titles', 0)}</div></div>
        <div class="metric"><div class="label" data-i18n="coverage">Coverage</div><div class="value">{watched_douban_coverage}</div></div>
        <div class="metric"><div class="label" data-i18n="missingAfterLookup">Missing after lookup</div><div class="value">{watched_douban_stats.get('missing_titles', 0)}</div></div>
      </div>
      <div class="grid-2" style="margin-top:18px;">
        <div id="watched-douban-scatter" class="plot"></div>
        <div id="watched-douban-gap-chart" class="plot"></div>
      </div>
      <div class="table-wrap" style="margin-top:18px;">
        <table id="watched-douban-table"></table>
      </div>
    </section>

    <section class="section">
      <h2 data-i18n="streamingTitle">Canada Streaming Availability</h2>
      <p class="lead" data-i18n="streamingLead">本区只保留能够稳定匹配到英文电影词条的加拿大流媒体目录。榜单优先展示已匹配 Letterboxd 评分的影片，并同步显示可用的豆瓣评分。</p>
      <div class="controls">
        <label for="streaming-provider-filter" data-i18n="providerLabel">平台：</label>
        <select id="streaming-provider-filter"></select>
        <label for="streaming-watch-filter" data-i18n="watchStateLabel">观看状态：</label>
        <select id="streaming-watch-filter">
          <option value="unwatched" data-i18n="unwatchedOption">没看过</option>
          <option value="watched" data-i18n="watchedOption">我看过的</option>
          <option value="all" data-i18n="allOption">全部</option>
        </select>
        <label for="streaming-exclusive-filter" data-i18n="exclusiveLabel">平台独占：</label>
        <select id="streaming-exclusive-filter">
          <option value="all" data-i18n="allOption">全部</option>
          <option value="exclusive" data-i18n="exclusiveOnlyOption">只看独占</option>
          <option value="multi" data-i18n="multiPlatformOption">只看多平台</option>
        </select>
        <label for="streaming-score-filter" data-i18n="scoreMatchLabel">评分匹配：</label>
        <select id="streaming-score-filter">
          <option value="scored" data-i18n="scoredOnlyOption">只看已匹配 Letterboxd 评分</option>
          <option value="all" data-i18n="allTitlesOption">全部标题</option>
        </select>
      </div>
      <div class="filter-group">
        <div class="filter-group-label" data-i18n="includeGenresLabel">只看类型：可多选；不选表示不过滤</div>
        <div id="streaming-genre-include-pills" class="pill-group"></div>
      </div>
      <div class="filter-group">
        <div class="filter-group-label" data-i18n="excludeGenresLabel">排除类型：可多选；不选表示不排除</div>
        <div id="streaming-genre-exclude-pills" class="pill-group"></div>
      </div>
      <p id="streaming-results-summary" class="results-summary"></p>
      <p id="streaming-data-note" class="subtle-note"></p>
      <div class="grid-2">
        <div id="streaming-provider-summary-chart" class="plot"></div>
        <div id="streaming-ranking-chart" class="plot"></div>
      </div>
      <div id="streaming-provider-cards" class="grid-3 provider-cards"></div>
      <div class="table-wrap" style="margin-top:18px;">
        <table id="streaming-table"></table>
      </div>
    </section>

    <section class="section">
      <h2 data-i18n="recommendationsTitle">Recommendations Beyond Watchlist</h2>
      <p class="lead" data-i18n="recommendationsLead">推荐池同时包含 watchlist、导出 lists 与当前流媒体目录里的外部发现条目；筛选器可分别限定 watchlist、lists、平台可看状态与类型范围。</p>
      <div class="controls">
        <label for="recommendation-watchlist-filter" data-i18n="watchlistLabel">Watchlist：</label>
        <select id="recommendation-watchlist-filter">
          <option value="all" data-i18n="allOption">全部</option>
          <option value="in" data-i18n="watchlistInOption">只看在 watchlist 里</option>
          <option value="out" data-i18n="watchlistOutOption">排除 watchlist</option>
        </select>
        <label for="recommendation-list-filter" data-i18n="myListsLabel">我的 lists：</label>
        <select id="recommendation-list-filter">
          <option value="all" data-i18n="allOption">全部</option>
          <option value="in" data-i18n="listsInOption">只看在我的 lists 里</option>
          <option value="out" data-i18n="listsOutOption">排除我的 lists</option>
        </select>
        <label for="recommendation-streaming-filter" data-i18n="streamingAvailableLabel">平台可看：</label>
        <select id="recommendation-streaming-filter">
          <option value="all" data-i18n="allOption">全部</option>
          <option value="in" data-i18n="availableInOption">只看当前可看</option>
          <option value="out" data-i18n="availableOutOption">排除当前可看</option>
        </select>
        <label for="recommendation-provider-filter" data-i18n="providerLabel">平台：</label>
        <select id="recommendation-provider-filter"></select>
        <label for="recommendation-sort-filter" data-i18n="sortLabel">排序：</label>
        <select id="recommendation-sort-filter">
          <option value="priority" data-i18n="sortPriorityOption">按综合优先级</option>
          <option value="predicted" data-i18n="sortPredictedOption">按预测喜欢程度</option>
          <option value="site" data-i18n="sortSiteOption">按站内口碑</option>
        </select>
      </div>
      <div class="filter-group">
        <div class="filter-group-label" data-i18n="includeGenresLabel">只看类型：可多选；不选表示不过滤</div>
        <div id="recommendation-genre-include-pills" class="pill-group"></div>
      </div>
      <div class="filter-group">
        <div class="filter-group-label" data-i18n="excludeGenresLabel">排除类型：可多选；不选表示不排除</div>
        <div id="recommendation-genre-exclude-pills" class="pill-group"></div>
      </div>
      <p id="recommendation-results-summary" class="results-summary"></p>
      <div id="recommendation-priority-chart" class="plot"></div>
      <div class="table-wrap" style="margin-top:18px;">
        <table id="recommendation-table"></table>
      </div>
    </section>

    <section class="section">
      <h2 data-i18n="genreCountryTitle">Genre × Country / Region</h2>
      <p class="lead" data-i18n="genreCountryLead">选择一个类型后，可比较该类型在不同国家 / 地区之间的占比与平均分；展示层对香港、台湾、澳门统一按地区处理。</p>
      <div class="controls">
        <label for="genre-select" data-i18n="genreLabel">类型：</label>
        <select id="genre-select"></select>
      </div>
      <div class="grid-2">
        <div id="genre-country-share" class="plot"></div>
        <div id="genre-country-ratings" class="plot"></div>
      </div>
      <div class="grid-2" style="margin-top:18px;">
        <div id="country-genre-heatmap" class="plot"></div>
        <div id="country-genre-rating-heatmap" class="plot"></div>
      </div>
      <div class="table-wrap" style="margin-top:18px;">
        <table id="genre-country-table"></table>
      </div>
    </section>

    <section class="section">
      <h2 data-i18n="tagsTitle">Viewing Context Tags</h2>
      <p class="lead" data-i18n="tagsLead">本区将 tags 视为观影语境元数据，拆分为社交关系、同伴、观看设备、地点与来源。未标记条目不进入占比图。</p>
      <h3 data-i18n="tagCompositionTitle">Tag Composition</h3>
      <div class="grid-3">
        <div id="tag-device-pie" class="plot"></div>
        <div id="tag-social-pie" class="plot"></div>
        <div id="tag-companion-pie" class="plot"></div>
        <div id="tag-location-pie" class="plot"></div>
        <div id="tag-platform-pie" class="plot"></div>
        <div id="tag-raw-pie" class="plot"></div>
      </div>
      <h3 style="margin-top:18px;" data-i18n="ratingContextTitle">Rating Context</h3>
      <div class="grid-3">
        <div id="social-context-chart" class="plot"></div>
        <div id="device-context-chart" class="plot"></div>
        <div id="platform-context-chart" class="plot"></div>
      </div>
      <div class="grid-2" style="margin-top:18px;">
        <div id="social-genre-delta-chart" class="plot"></div>
        <div class="mini-card">
          <h3 data-i18n="companionSnapshotTitle">Companion Snapshot</h3>
          <div class="table-wrap">{render_table(payload['tags']['companion_stats'], [('companion','Companion'), ('watches','Watches'), ('avg_rating','Avg rating')])}</div>
        </div>
      </div>
    </section>

    <section class="section">
      <h2 data-i18n="reviewsTitle">Review Language Patterns</h2>
      <p class="lead" data-i18n="reviewsLead">本区从评论长度、主题与词汇分布三个角度整理 review 文本特征。</p>
      <div class="grid-2">
        <div id="review-length-chart" class="plot"></div>
        <div id="review-theme-chart" class="plot"></div>
      </div>
      <div class="grid-2" style="margin-top:18px;">
        <div class="mini-card">
          <h3 data-i18n="highRatingVocabularyTitle">High-rating vocabulary</h3>
          <div class="table-wrap">{render_table(payload['reviews']['positive_terms'], [('term','Term'), ('positive_count','High-count'), ('score','Score')])}</div>
        </div>
        <div class="mini-card">
          <h3 data-i18n="lowRatingVocabularyTitle">Low-rating vocabulary</h3>
          <div class="table-wrap">{render_table(payload['reviews']['negative_terms'], [('term','Term'), ('negative_count','Low-count'), ('score','Score')])}</div>
        </div>
      </div>
    </section>

    <section class="section">
      <h2 data-i18n="listsTitle">List Signals</h2>
      <p class="lead" data-i18n="listsLead">本区按待看计划、偏好声明和主题整理三类意图汇总 lists，并重点展示更能代表个人口味的条目。</p>
      <div class="grid-2">
        <div class="mini-card">
          <h3 data-i18n="listInventoryTitle">List Inventory</h3>
          <div class="table-wrap">{list_summary_html}</div>
        </div>
        <div class="mini-card">
          <h3 data-i18n="repeatedPicksTitle">Repeated picks across preference lists</h3>
          <div class="table-wrap">{preference_overlap_html}</div>
        </div>
      </div>
      <div class="grid-2" style="margin-top:18px;">
        <div id="preference-country-bias-chart" class="plot"></div>
        <div id="preference-genre-bias-chart" class="plot"></div>
      </div>
    </section>

    <div class="footer"><span data-i18n="generatedAtLabel">页面生成时间：</span>{html.escape(payload['generated_at'])}<span data-i18n="embeddedDataLabel">。交互图表所需数据已内嵌在当前文件中。</span></div>
  </div>

  <script>
    const data = {json_for_html(payload)};
    const plotConfig = {{responsive: true, displayModeBar: false}};
    const plotLayout = {{
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      margin: {{t: 52, r: 24, b: 56, l: 72}},
      font: {{family: 'IBM Plex Sans, sans-serif', color: '#17233b'}},
      hoverlabel: {{font: {{family: 'IBM Plex Sans, sans-serif'}}}},
    }};
    const I18N = {{
      zh: {{
        heroLead: '这个页面汇总的是 Letterboxd 原生会员页之外更适合横向比较的观察维度，包括国家 / 地区 × 类型结构、加拿大流媒体可看范围、观影语境标签、review 用词、lists 意图，以及不限于 watchlist 的候选推荐。',
        ratedFilms: '已评分影片',
        watchEvents: '观影记录',
        taggedWatches: '带标签观影',
        writtenReviews: '文字评论',
        exportedLists: '导出片单',
        unseenCandidates: '未看候选',
        doubanMatched: '豆瓣已匹配',
        streamingIndexed: '流媒体已索引',
        tasteBriefTitle: 'Today\\'s Taste Brief',
        tasteBriefLead: '本区把最新 Letterboxd 数据、可看片单和电影行业信号压缩成可快速阅读的判断线索。',
        dailyRadarTitle: 'Daily Film Radar',
        dailyRadarLead: '每天从电影新闻源中提取作品、导演、奖项和产业动态，只保留能提供补片或理解行业的短句。',
        filmFactsTitle: 'Film Facts',
        filmFactsLead: '这些条目来自你的评分、tags、lists 和当前可看目录，会随每日同步更新。',
        doubanCoverageTitle: 'Watched Films: Douban Coverage',
        doubanCoverageLead: '本区为已评分影片补齐豆瓣评分，并将你的评分、Letterboxd 均分与豆瓣 10 分制评分放在同一张表内对照。匹配优先使用 IMDb / Douban subject ID，并以公开豆瓣电影数据索引补齐历史评分；live Douban API 只作为可用时的增量来源。',
        matchedWatchedFilms: '已匹配已看影片',
        coverage: '覆盖率',
        missingAfterLookup: '仍缺失',
        streamingTitle: 'Canada Streaming Availability',
        streamingLead: '本区只保留能够稳定匹配到英文电影词条的加拿大流媒体目录。榜单优先展示已匹配 Letterboxd 评分的影片，并同步显示可用的豆瓣评分。',
        recommendationsTitle: 'Recommendations Beyond Watchlist',
        recommendationsLead: '推荐池同时包含 watchlist、导出 lists 与当前流媒体目录里的外部发现条目；筛选器可分别限定 watchlist、lists、平台可看状态与类型范围。',
        genreCountryTitle: 'Genre × Country / Region',
        genreCountryLead: '选择一个类型后，可比较该类型在不同国家 / 地区之间的占比与平均分；展示层对 Hong Kong、Taiwan、Macau 统一按地区处理。',
        tagsTitle: 'Viewing Context Tags',
        tagsLead: '本区将 tags 视为观影语境元数据，拆分为社交关系、同伴、观看设备、地点与来源。未标记条目不进入占比图。',
        tagCompositionTitle: 'Tag Composition',
        ratingContextTitle: 'Rating Context',
        companionSnapshotTitle: 'Companion Snapshot',
        reviewsTitle: 'Review Language Patterns',
        reviewsLead: '本区从评论长度、主题与词汇分布三个角度整理 review 文本特征。',
        highRatingVocabularyTitle: 'High-rating vocabulary',
        lowRatingVocabularyTitle: 'Low-rating vocabulary',
        listsTitle: 'List Signals',
        listsLead: '本区按待看计划、偏好声明和主题整理三类意图汇总 lists，并重点展示更能代表个人口味的条目。',
        listInventoryTitle: 'List Inventory',
        repeatedPicksTitle: 'Repeated picks across preference lists',
        generatedAtLabel: '页面生成时间：',
        embeddedDataLabel: '。交互图表所需数据已内嵌在当前文件中。',
        providerLabel: '平台：',
        watchStateLabel: '观看状态：',
        exclusiveLabel: '平台独占：',
        scoreMatchLabel: '评分匹配：',
        watchlistLabel: 'Watchlist：',
        myListsLabel: '我的 lists：',
        streamingAvailableLabel: '平台可看：',
        sortLabel: '排序：',
        genreLabel: '类型：',
        allOption: '全部',
        unwatchedOption: '没看过',
        watchedOption: '我看过的',
        exclusiveOnlyOption: '只看独占',
        multiPlatformOption: '只看多平台',
        scoredOnlyOption: '只看已匹配 Letterboxd 评分',
        allTitlesOption: '全部标题',
        watchlistInOption: '只看在 watchlist 里',
        watchlistOutOption: '排除 watchlist',
        listsInOption: '只看在我的 lists 里',
        listsOutOption: '排除我的 lists',
        availableInOption: '只看当前可看',
        availableOutOption: '排除当前可看',
        sortPriorityOption: '按综合优先级',
        sortPredictedOption: '按预测喜欢程度',
        sortSiteOption: '按站内口碑',
        includeGenresLabel: '只看类型：可多选；不选表示不过滤',
        excludeGenresLabel: '排除类型：可多选；不选表示不排除',
        allPlatforms: '全部平台',
        allGenres: '全部类型',
        noExclusions: '不排除',
        film: 'Film',
        year: 'Year',
        genres: 'Genres',
        platforms: 'Platforms',
        status: 'Status',
        links: 'Links',
        yourRating: 'Your rating',
        letterboxd: 'Letterboxd',
        douban: 'Douban',
        lbRating: 'LB rating',
        lbRatings: 'LB ratings',
        priority: 'Priority',
        predicted: 'Predicted',
        available: 'Available',
        inYourData: 'In your data',
        reason: 'Reason',
        countryRegion: 'Country / Region',
        films: 'Films',
        avgRating: 'Avg rating',
        shareInGenre: 'Share in genre',
        stableScore: 'Stable score',
      }},
      en: {{
        heroLead: 'A shareable research page for the questions Letterboxd Stats does not answer directly: genre × region patterns, Canadian streaming options, viewing-context tags, review language, list intent, and recommendations beyond the official watchlist.',
        ratedFilms: 'Rated films',
        watchEvents: 'Watch events',
        taggedWatches: 'Tagged watches',
        writtenReviews: 'Written reviews',
        exportedLists: 'Exported lists',
        unseenCandidates: 'Unseen candidates',
        doubanMatched: 'Douban matched',
        streamingIndexed: 'Streaming indexed',
        tasteBriefTitle: 'Today\\'s Taste Brief',
        tasteBriefLead: 'A compact briefing that combines the newest Letterboxd data, watch availability, and film-industry signals into quickly readable clues.',
        dailyRadarTitle: 'Daily Film Radar',
        dailyRadarLead: 'Updated from film-news feeds with short notes about noteworthy works, directors, awards, releases, box office, and industry movement.',
        filmFactsTitle: 'Film Facts',
        filmFactsLead: 'Daily facts drawn from your ratings, tags, lists, and current streaming availability.',
        doubanCoverageTitle: 'Watched Films: Douban Coverage',
        doubanCoverageLead: 'Adds Douban ratings for watched films and compares them with your rating and Letterboxd averages. Matching prioritizes IMDb / Douban subject IDs, public Douban indexes, and live Douban detail pages when available.',
        matchedWatchedFilms: 'Matched watched films',
        coverage: 'Coverage',
        missingAfterLookup: 'Missing after lookup',
        streamingTitle: 'Canada Streaming Availability',
        streamingLead: 'Canadian streaming catalogues matched to stable English film records. Rankings prioritize titles with Letterboxd scores and include Douban ratings when matched.',
        recommendationsTitle: 'Recommendations Beyond Watchlist',
        recommendationsLead: 'The recommendation pool includes watchlist items, exported lists, and outside discoveries from current streaming catalogues. Filters can include or exclude each source.',
        genreCountryTitle: 'Genre × Country / Region',
        genreCountryLead: 'Choose a genre to compare its country / region mix and average ratings. Hong Kong, Taiwan, and Macau are presented as regions.',
        tagsTitle: 'Viewing Context Tags',
        tagsLead: 'Tags are treated as viewing-context metadata: social setting, named companions, device, place, and source. Untagged watches are excluded from share charts.',
        tagCompositionTitle: 'Tag Composition',
        ratingContextTitle: 'Rating Context',
        companionSnapshotTitle: 'Companion Snapshot',
        reviewsTitle: 'Review Language Patterns',
        reviewsLead: 'Review text summarized through length, theme, and vocabulary patterns.',
        highRatingVocabularyTitle: 'High-rating vocabulary',
        lowRatingVocabularyTitle: 'Low-rating vocabulary',
        listsTitle: 'List Signals',
        listsLead: 'Lists are grouped by watch plans, preference statements, and thematic collections, with emphasis on signals that reveal taste.',
        listInventoryTitle: 'List Inventory',
        repeatedPicksTitle: 'Repeated picks across preference lists',
        generatedAtLabel: 'Generated at: ',
        embeddedDataLabel: '. Interactive chart data is embedded in this page.',
        providerLabel: 'Provider:',
        watchStateLabel: 'Watch status:',
        exclusiveLabel: 'Exclusivity:',
        scoreMatchLabel: 'Score match:',
        watchlistLabel: 'Watchlist:',
        myListsLabel: 'My lists:',
        streamingAvailableLabel: 'Streaming:',
        sortLabel: 'Sort:',
        genreLabel: 'Genre:',
        allOption: 'All',
        unwatchedOption: 'Unwatched',
        watchedOption: 'Watched',
        exclusiveOnlyOption: 'Exclusive only',
        multiPlatformOption: 'Multi-platform only',
        scoredOnlyOption: 'Matched Letterboxd scores only',
        allTitlesOption: 'All titles',
        watchlistInOption: 'Only in watchlist',
        watchlistOutOption: 'Exclude watchlist',
        listsInOption: 'Only in my lists',
        listsOutOption: 'Exclude my lists',
        availableInOption: 'Currently available only',
        availableOutOption: 'Exclude current availability',
        sortPriorityOption: 'Overall priority',
        sortPredictedOption: 'Predicted taste fit',
        sortSiteOption: 'Letterboxd reputation',
        includeGenresLabel: 'Include genres: multi-select; empty means no include filter',
        excludeGenresLabel: 'Exclude genres: multi-select; empty means no exclusions',
        allPlatforms: 'All platforms',
        allGenres: 'All genres',
        noExclusions: 'No exclusions',
        film: 'Film',
        year: 'Year',
        genres: 'Genres',
        platforms: 'Platforms',
        status: 'Status',
        links: 'Links',
        yourRating: 'Your rating',
        letterboxd: 'Letterboxd',
        douban: 'Douban',
        lbRating: 'LB rating',
        lbRatings: 'LB ratings',
        priority: 'Priority',
        predicted: 'Predicted',
        available: 'Available',
        inYourData: 'In your data',
        reason: 'Reason',
        countryRegion: 'Country / Region',
        films: 'Films',
        avgRating: 'Avg rating',
        shareInGenre: 'Share in genre',
        stableScore: 'Stable score',
      }}
    }};
    let currentLanguage = localStorage.getItem('letterboxd-report-language') || 'zh';

    function t(key) {{
      return (I18N[currentLanguage] && I18N[currentLanguage][key]) || I18N.zh[key] || key;
    }}

    function applyLanguage(language, refresh = false) {{
      currentLanguage = language === 'en' ? 'en' : 'zh';
      localStorage.setItem('letterboxd-report-language', currentLanguage);
      document.documentElement.lang = currentLanguage === 'en' ? 'en' : 'zh-CN';
      document.querySelectorAll('[data-i18n]').forEach(element => {{
        element.textContent = t(element.dataset.i18n);
      }});
      document.querySelectorAll('[data-language-choice]').forEach(button => {{
        button.classList.toggle('active', button.dataset.languageChoice === currentLanguage);
      }});
      if (refresh && typeof refreshTranslatedViews === 'function') {{
        refreshTranslatedViews();
      }}
    }}

    function formatPct(value) {{
      if (value === null || value === undefined || value === '') return '—';
      const number = Number(value);
      return Number.isFinite(number) ? `${{(number * 100).toFixed(1)}}%` : '—';
    }}

    function formatCount(value) {{
      if (value === null || value === undefined || value === '') return '—';
      const number = Number(value);
      if (!Number.isFinite(number)) return '—';
      return new Intl.NumberFormat(currentLanguage === 'zh' ? 'zh-CN' : 'en-US', {{
        notation: Math.abs(number) >= 10000 ? 'compact' : 'standard',
        maximumFractionDigits: Math.abs(number) >= 10000 ? 1 : 0,
      }}).format(number);
    }}

    function formatRating(value) {{
      if (value === null || value === undefined || value === '') return '—';
      const number = Number(value);
      return Number.isFinite(number) ? number.toFixed(2) : '—';
    }}

    function formatSignedRating(value) {{
      if (value === null || value === undefined || value === '') return '—';
      const number = Number(value);
      if (!Number.isFinite(number)) return '—';
      return `${{number >= 0 ? '+' : ''}}${{number.toFixed(2)}}`;
    }}

    function formatOneDecimal(value) {{
      if (value === null || value === undefined || value === '') return '—';
      const number = Number(value);
      return Number.isFinite(number) ? number.toFixed(1) : '—';
    }}

    function wrapLabel(value, width = 18) {{
      const text = String(value ?? '').trim();
      if (!text) return '—';
      const tokens = text.split(/\\s+/);
      if (tokens.length === 1 && text.length <= width) return text;
      const lines = [];
      let line = '';
      tokens.forEach(token => {{
        if ((line + ' ' + token).trim().length > width) {{
          if (line) lines.push(line);
          line = token;
        }} else {{
          line = (line ? line + ' ' : '') + token;
        }}
      }});
      if (line) lines.push(line);
      return lines.join('<br>');
    }}

    function plotTitle(value, width = window.innerWidth < 640 ? 30 : 52) {{
      return {{
        text: wrapLabel(value, width),
        font: {{size: window.innerWidth < 640 ? 13 : 15}},
      }};
    }}

    function shortenLabel(value, width = 38) {{
      const text = String(value ?? '').trim();
      if (!text) return '—';
      return text.length > width ? `${{text.slice(0, width - 1)}}…` : text;
    }}

    function barChartHeight(count, base = 180, step = 28, max = 620) {{
      return Math.min(max, Math.max(280, base + count * step));
    }}

    function numericValues(rows, key) {{
      return rows
        .map(row => Number(row[key]))
        .filter(value => Number.isFinite(value));
    }}

    function focusedRange(rows, key = 'avg_rating', floor = 0, ceiling = 5) {{
      const values = numericValues(rows, key);
      if (!values.length) return [floor, ceiling];
      let min = Math.min(...values);
      let max = Math.max(...values);
      if (max - min < 0.55) {{
        const center = (min + max) / 2;
        min = center - 0.32;
        max = center + 0.32;
      }}
      return [Math.max(floor, min - 0.18), Math.min(ceiling, max + 0.18)];
    }}

    function renderRatingDotPlot(containerId, rows, labelKey, title, color = '#2d6f8e') {{
      const el = document.getElementById(containerId);
      const source = (rows || []).filter(row => Number.isFinite(Number(row.avg_rating)));
      if (!source.length) {{
        el.innerHTML = `<p class="muted">${{currentLanguage === 'zh' ? '这个类别暂无评分样本。' : 'No rated data in this category.'}}</p>`;
        return;
      }}
      const ordered = [...source].sort((left, right) => Number(left.avg_rating) - Number(right.avg_rating));
      Plotly.newPlot(containerId, [{{
        type: 'scatter',
        mode: 'markers+text',
        x: ordered.map(row => Number(row.avg_rating)),
        y: ordered.map(row => wrapLabel(row[labelKey], 22)),
        text: ordered.map(row => formatRating(row.avg_rating)),
        textposition: 'middle right',
        cliponaxis: false,
        marker: {{
          color,
          size: ordered.map(row => Math.min(28, Math.max(11, 8 + Math.sqrt(Number(row.watches || row.films || row.distinct_films || 1)) * 3))),
          opacity: 0.82,
          line: {{color: '#fffaf2', width: 1.5}},
        }},
        customdata: ordered.map(row => [formatCount(row.watches || row.films || row.distinct_films), formatPct(row.five_star_share)]),
        hovertemplate: 'Average rating: %{{x:.2f}}<br>Count: %{{customdata[0]}}<extra></extra>',
      }}], {{
        ...plotLayout,
        title: plotTitle(title),
        margin: {{t: 52, r: 76, b: 46, l: 124}},
        xaxis: {{range: focusedRange(source), automargin: true, title: 'Average rating'}},
        yaxis: {{automargin: true}},
        height: barChartHeight(ordered.length, 150, 34, 560),
      }}, plotConfig);
    }}

    const streamingGenreIncludeSelection = new Set();
    const streamingGenreExcludeSelection = new Set();
    const recommendationGenreIncludeSelection = new Set();
    const recommendationGenreExcludeSelection = new Set();

    function makeTable(el, columns, rows) {{
      const head = '<thead><tr>' + columns.map(col => `<th>${{col.label}}</th>`).join('') + '</tr></thead>';
      const body = '<tbody>' + rows.map(row => '<tr>' + columns.map(col => `<td>${{row[col.key] ?? ''}}</td>`).join('') + '</tr>').join('') + '</tbody>';
      el.innerHTML = head + body;
    }}

    function renderPillGroup(containerId, options, selection, resetLabel, onChange) {{
      const container = document.getElementById(containerId);
      const buttons = [
        `<button type="button" data-reset="true" class="${{selection.size === 0 ? 'active' : ''}}">${{resetLabel}}</button>`
      ].concat(
        options.map(option => {{
          const value = option.code ?? option.label;
          const label = option.label;
          const count = option.titles ?? 0;
          return `<button type="button" data-value="${{value}}" class="${{selection.has(value) ? 'active' : ''}}">${{label}} (${{formatCount(count)}})</button>`;
        }})
      );
      container.innerHTML = buttons.join('');
      container.querySelectorAll('button').forEach(button => {{
        button.addEventListener('click', () => {{
          const value = button.dataset.value;
          if (button.dataset.reset === 'true') {{
            selection.clear();
          }} else if (value) {{
            if (selection.has(value)) {{
              selection.delete(value);
            }} else {{
              selection.add(value);
            }}
          }}
          renderPillGroup(containerId, options, selection, resetLabel, onChange);
          onChange();
        }});
      }});
    }}

    function renderWatchedDoubanCharts() {{
      const watched = data.watched_douban || {{}};
      const matched = (watched.rows || []).filter(row => row.douban_rating !== null && row.douban_rating !== undefined);
      const scatterRows = matched.filter(row => row.user_rating !== null && row.user_rating !== undefined);
      Plotly.newPlot('watched-douban-scatter', [{{
        type: 'scatter',
        mode: 'markers',
        x: scatterRows.map(row => row.user_rating),
        y: scatterRows.map(row => Number(row.douban_rating) / 2),
        text: scatterRows.map(row => `${{row.name}} (${{row.year ?? '—'}})`),
        customdata: scatterRows.map(row => [formatOneDecimal(row.douban_rating), formatRating(row.site_average_rating)]),
        marker: {{
          color: scatterRows.map(row => Number(row.douban_rating) / 2 - Number(row.user_rating)),
          colorscale: 'RdBu',
          reversescale: true,
          showscale: true,
          colorbar: {{title: 'Douban gap'}},
          size: 8,
          opacity: 0.76,
        }},
        hovertemplate: '%{{text}}<br>Your rating: %{{x:.2f}}<br>Douban / 2: %{{y:.2f}}<br>Douban: %{{customdata[0]}}<br>Letterboxd: %{{customdata[1]}}<extra></extra>',
      }}], {{
        ...plotLayout,
        title: plotTitle('Your rating vs Douban rating'),
        xaxis: {{title: 'Your rating', range: [0, 5.15], automargin: true}},
        yaxis: {{title: 'Douban rating / 2', range: [0, 5.15], automargin: true}},
        height: 420,
      }}, plotConfig);

      const gapRows = (watched.top_gaps || [])
        .filter(row => row.douban_gap !== null && row.douban_gap !== undefined)
        .slice(0, 14)
        .reverse();
      Plotly.newPlot('watched-douban-gap-chart', [{{
        type: 'bar',
        orientation: 'h',
        y: gapRows.map(row => wrapLabel(`${{shortenLabel(row.name, 42)}} (${{row.year ?? '—'}})`, 24)),
        x: gapRows.map(row => row.douban_gap),
        marker: {{color: gapRows.map(row => row.douban_gap >= 0 ? '#2d6f8e' : '#b75b49')}},
        customdata: gapRows.map(row => [formatRating(row.user_rating), formatOneDecimal(row.douban_rating)]),
        hovertemplate: 'Gap: %{{x:.2f}}<br>Your rating: %{{customdata[0]}}<br>Douban: %{{customdata[1]}}<extra></extra>',
      }}], {{
        ...plotLayout,
        title: plotTitle('Largest Douban / personal-rating gaps'),
        xaxis: {{title: 'Douban / 2 minus your rating', zeroline: true, automargin: true}},
        yaxis: {{automargin: true}},
        height: barChartHeight(gapRows.length, 150, 32, 640),
      }}, plotConfig);

      const tableRows = [...matched].sort((left, right) => {{
        if ((right.douban_rating ?? -1) !== (left.douban_rating ?? -1)) return (right.douban_rating ?? -1) - (left.douban_rating ?? -1);
        return (right.user_rating ?? -1) - (left.user_rating ?? -1);
      }}).slice(0, 120);
      makeTable(
        document.getElementById('watched-douban-table'),
        [
          {{key: 'name', label: t('film')}},
          {{key: 'year', label: t('year')}},
          {{key: 'user_rating', label: t('yourRating')}},
          {{key: 'letterboxd', label: t('letterboxd')}},
          {{key: 'douban', label: t('douban')}},
          {{key: 'gap', label: currentLanguage === 'zh' ? '豆瓣差值' : 'Douban gap'}},
          {{key: 'genres', label: t('genres')}},
          {{key: 'links', label: t('links')}},
        ],
        tableRows.map(row => {{
          const gap = row.user_rating === null || row.user_rating === undefined
            ? null
            : Number(row.douban_rating) / 2 - Number(row.user_rating);
          return {{
            name: row.name,
            year: row.year ?? '—',
            user_rating: formatRating(row.user_rating),
            letterboxd: formatRating(row.site_average_rating),
            douban: formatOneDecimal(row.douban_rating),
            gap: formatSignedRating(gap),
            genres: (row.genres || []).join(' / ') || '—',
            links: row.douban_url ? `<div class="inline-links"><a href="${{row.douban_url}}" target="_blank" rel="noopener noreferrer">Douban</a></div>` : '—',
          }};
        }})
      );
    }}

    function drawTagPie(containerId, rows, title) {{
      const el = document.getElementById(containerId);
      if (!rows || rows.length === 0) {{
        el.innerHTML = `<p class="muted">${{currentLanguage === 'zh' ? '这个类别暂无已标记数据。' : 'No tagged data in this category.'}}</p>`;
        return;
      }}
      Plotly.newPlot(containerId, [{{
        type: 'pie',
        labels: rows.map(row => row.label),
        values: rows.map(row => row.watches),
        hole: 0.38,
        textinfo: 'none',
        automargin: true,
        showlegend: true,
        hovertemplate: '%{{label}}<br>Watches: %{{value}}<br>Share: %{{percent}}<extra></extra>',
      }}], {{
        ...plotLayout,
        title: plotTitle(title),
        legend: {{orientation: 'h', y: -0.18, x: 0, font: {{size: 11}}}},
        margin: {{t: 54, r: 16, b: 92, l: 16}},
        height: 420,
      }}, plotConfig);
    }}

    function renderTagPieCharts() {{
      const pies = data.tags.tag_pies || {{}};
      drawTagPie('tag-device-pie', pies.device_context || [], 'Viewing device / display');
      drawTagPie('tag-social-pie', pies.social_scope || [], 'Solo vs social viewing');
      drawTagPie('tag-companion-pie', pies.companion || [], 'Named companion');
      drawTagPie('tag-location-pie', pies.location_context || [], 'Location');
      drawTagPie('tag-platform-pie', pies.platform_context || [], 'Platform / source tag');
      drawTagPie('tag-raw-pie', pies.raw_tags || [], 'Most used raw tags');
    }}

    function renderGenreSelect() {{
      const select = document.getElementById('genre-select');
      select.innerHTML = data.genre_country.top_genres.concat(
        Object.keys(data.genre_country.genre_profiles).filter(g => !data.genre_country.top_genres.includes(g)).sort()
      ).map(genre => `<option value="${{genre}}">${{genre}}</option>`).join('');
      select.value = {json.dumps(initial_genre, ensure_ascii=False)};
      select.addEventListener('change', () => renderGenreCountry(select.value));
    }}

    function renderGenreCountry(genre) {{
      const rows = data.genre_country.genre_profiles[genre] || [];
      const topRows = rows.slice(0, 10);
      Plotly.newPlot('genre-country-share', [{{
        type: 'pie',
        labels: topRows.map(row => row.country),
        values: topRows.map(row => row.share_in_genre),
        hole: 0.4,
        textinfo: 'none',
        automargin: true,
        showlegend: true,
        hovertemplate: '%{{label}}<br>Share: %{{percent}}<extra></extra>',
      }}], {{
        ...plotLayout,
        title: plotTitle(`${{genre}} source share by country / region`),
        legend: {{orientation: 'h', y: -0.2, x: 0, font: {{size: 11}}}},
        margin: {{t: 54, r: 18, b: 104, l: 18}},
        height: 430,
      }}, plotConfig);

      const ratingRows = rows.filter(row => row.films >= 2).slice(0, 10);
      renderRatingDotPlot(
        'genre-country-ratings',
        ratingRows,
        'country',
        `${{genre}} average rating by country / region`,
        '#2d6f8e'
      );

      makeTable(
        document.getElementById('genre-country-table'),
        [
          {{key: 'country', label: t('countryRegion')}},
          {{key: 'films', label: t('films')}},
          {{key: 'avg_rating', label: t('avgRating')}},
          {{key: 'share_in_genre', label: t('shareInGenre')}},
          {{key: 'weighted_score', label: t('stableScore')}},
        ],
        rows.map(row => ({{
          ...row,
          share_in_genre: formatPct(row.share_in_genre),
          avg_rating: formatRating(row.avg_rating),
          weighted_score: formatRating(row.weighted_score),
        }}))
      );
    }}

    function renderHeatmaps() {{
      Plotly.newPlot('country-genre-heatmap', [{{
        type: 'heatmap',
        x: data.genre_country.top_genres,
        y: data.genre_country.top_countries,
        z: data.genre_country.count_matrix,
        colorscale: 'YlOrBr'
      }}], {{
        ...plotLayout,
        title: plotTitle('Genre × country / region: watch count'),
        xaxis: {{tickangle: -28, automargin: true}},
        yaxis: {{automargin: true}},
      }}, plotConfig);

      Plotly.newPlot('country-genre-rating-heatmap', [{{
        type: 'heatmap',
        x: data.genre_country.top_genres,
        y: data.genre_country.top_countries,
        z: data.genre_country.rating_matrix,
        colorscale: 'Teal',
        zmin: 2.5,
        zmax: 5.0,
      }}], {{
        ...plotLayout,
        title: plotTitle('Genre × country / region: average rating'),
        xaxis: {{tickangle: -28, automargin: true}},
        yaxis: {{automargin: true}},
      }}, plotConfig);
    }}

    function renderTagCharts() {{
      const social = data.tags.social_stats;
      renderRatingDotPlot('social-context-chart', social, 'social_context', 'Average rating by social context', '#c48a3a');
      const device = data.tags.device_stats;
      renderRatingDotPlot('device-context-chart', device, 'device_context', 'Average rating by device', '#2d6f8e');
      const platform = data.tags.platform_stats.slice(0, 10);
      renderRatingDotPlot('platform-context-chart', platform, 'platform_context', 'Average rating by platform / source tag', '#b75b49');

      const delta = data.tags.social_genre_delta.slice(0, 12).reverse();
      Plotly.newPlot('social-genre-delta-chart', [{{
        type: 'bar',
        orientation: 'h',
        y: delta.map(row => wrapLabel(row.genre, 18)),
        x: delta.map(row => row.diff),
        marker: {{
          color: delta.map(row => row.diff >= 0 ? '#2d6f8e' : '#b75b49')
        }},
        customdata: delta.map(row => `${{formatRating(row.social_avg)}} / ${{formatRating(row.solo_avg)}}`),
        hovertemplate: 'Delta: %{{x:.2f}}<br>Social / solo: %{{customdata}}<extra></extra>',
      }}], {{
        ...plotLayout,
        title: plotTitle('Social-context lift by genre'),
        yaxis: {{automargin: true}},
        height: barChartHeight(delta.length, 140, 28, 560),
      }}, plotConfig);
    }}

    function renderReviewCharts() {{
      const points = data.reviews.review_length_points;
      const ratingBuckets = [...new Set(points.map(point => point.user_rating))].sort((a, b) => a - b);
      const traces = ratingBuckets.map(rating => ({{
        type: 'box',
        name: String(rating),
        y: points.filter(point => point.user_rating === rating).map(point => point.word_count),
        boxpoints: false,
      }}));
      Plotly.newPlot('review-length-chart', traces, {{
        ...plotLayout,
        title: plotTitle('不同评分下 review 字数分布'),
        yaxis: {{title: 'Words'}},
        xaxis: {{title: 'Rating'}},
      }}, plotConfig);

      const themes = data.reviews.theme_stats;
      Plotly.newPlot('review-theme-chart', [{{
        type: 'bar',
        orientation: 'h',
        y: themes.map(row => wrapLabel(row.theme, 18)).reverse(),
        x: themes.map(row => row.avg_rating).reverse(),
        marker: {{color: '#2d6f8e'}},
        customdata: themes.map(row => row.mention_count).reverse(),
        hovertemplate: 'Average rating: %{{x:.2f}}<br>Mentions: %{{customdata}}<extra></extra>',
      }}], {{
        ...plotLayout,
        title: plotTitle('Average rating by review theme'),
        xaxis: {{range: [0, 5], automargin: true}},
        yaxis: {{automargin: true}},
        height: barChartHeight(themes.length, 140, 28, 560),
      }}, plotConfig);
    }}

    function renderListCharts() {{
      const countryBias = data.lists.preference_country_bias || [];
      Plotly.newPlot('preference-country-bias-chart', [{{
        type: 'bar',
        orientation: 'h',
        y: countryBias.map(row => wrapLabel(row.country, 18)).reverse(),
        x: countryBias.map(row => row.share_diff).reverse(),
        marker: {{color: '#c48a3a'}},
      }}], {{
        ...plotLayout,
        title: plotTitle('Preference lists: country / region tilt'),
        xaxis: {{tickformat: '.0%'}},
        yaxis: {{automargin: true}},
        height: barChartHeight(countryBias.length, 140, 28, 560),
      }}, plotConfig);

      const genreBias = data.lists.preference_genre_bias || [];
      Plotly.newPlot('preference-genre-bias-chart', [{{
        type: 'bar',
        orientation: 'h',
        y: genreBias.map(row => wrapLabel(row.genre, 18)).reverse(),
        x: genreBias.map(row => row.share_diff).reverse(),
        marker: {{color: '#2d6f8e'}},
      }}], {{
        ...plotLayout,
        title: plotTitle('Preference lists: genre tilt'),
        xaxis: {{tickformat: '.0%'}},
        yaxis: {{automargin: true}},
        height: barChartHeight(genreBias.length, 140, 28, 560),
      }}, plotConfig);
    }}

    function initStreamingControls() {{
      const providerSelect = document.getElementById('streaming-provider-filter');
      const selectedProvider = providerSelect.value || 'all';
      providerSelect.innerHTML = `<option value="all">${{t('allPlatforms')}}</option>` + data.streaming.summary
        .map(row => `<option value="${{row.provider}}">${{row.provider}}</option>`)
        .join('');
      providerSelect.value = [...providerSelect.options].some(option => option.value === selectedProvider) ? selectedProvider : 'all';

      renderPillGroup(
        'streaming-genre-include-pills',
        data.streaming.genre_options || [],
        streamingGenreIncludeSelection,
        t('allGenres'),
        renderStreamingSection
      );
      renderPillGroup(
        'streaming-genre-exclude-pills',
        data.streaming.genre_options || [],
        streamingGenreExcludeSelection,
        t('noExclusions'),
        renderStreamingSection
      );

      [
        'streaming-provider-filter',
        'streaming-watch-filter',
        'streaming-exclusive-filter',
        'streaming-score-filter',
      ]
        .forEach(id => {{
          const element = document.getElementById(id);
          if (!element.dataset.bound) {{
            element.addEventListener('change', renderStreamingSection);
            element.dataset.bound = 'true';
          }}
        }});
    }}

    function getFilteredStreamingRows() {{
      const provider = document.getElementById('streaming-provider-filter').value;
      const watchState = document.getElementById('streaming-watch-filter').value;
      const exclusivity = document.getElementById('streaming-exclusive-filter').value;
      const scoreState = document.getElementById('streaming-score-filter').value;
      const includeGenres = [...streamingGenreIncludeSelection];
      const excludeGenres = [...streamingGenreExcludeSelection];

      return data.streaming.rows
        .filter(row => {{
          const genreCodes = row.genre_codes || [];
          if (provider !== 'all' && !(row.providers || []).includes(provider)) return false;
          if (watchState === 'watched' && !row.watched) return false;
          if (watchState === 'unwatched' && row.watched) return false;
          if (exclusivity === 'exclusive' && !row.exclusive) return false;
          if (exclusivity === 'multi' && (row.exclusive || !row.available_on_tracked_platforms)) return false;
          if (scoreState === 'scored' && (row.letterboxd_rating === null || row.letterboxd_rating === undefined)) return false;
          if (includeGenres.length && !includeGenres.some(genre => genreCodes.includes(genre))) return false;
          if (excludeGenres.some(genre => genreCodes.includes(genre))) return false;
          return true;
        }})
        .sort((left, right) => {{
          const leftRating = left.letterboxd_rating ?? -1;
          const rightRating = right.letterboxd_rating ?? -1;
          if (rightRating !== leftRating) return rightRating - leftRating;
          const leftCount = left.letterboxd_rating_count ?? -1;
          const rightCount = right.letterboxd_rating_count ?? -1;
          if (rightCount !== leftCount) return rightCount - leftCount;
          return (right.imdb_score ?? -1) - (left.imdb_score ?? -1);
        }});
    }}

    function renderStreamingProviderCards() {{
      const container = document.getElementById('streaming-provider-cards');
      container.innerHTML = data.streaming.summary.map(row => `
        <div class="mini-card">
          <h3>${{row.provider}}</h3>
          <div class="muted">${{row.scope_label || ''}}</div>
          <div class="provider-card-stat">
            <div><strong>${{formatCount(row.available_titles)}}</strong><span class="muted">${{currentLanguage === 'zh' ? '当前可看电影' : 'Available films'}}</span></div>
            <div><strong>${{formatCount(row.exclusive_titles)}}</strong><span class="muted">${{currentLanguage === 'zh' ? '平台独占' : 'Exclusive titles'}}</span></div>
            <div><strong>${{formatCount(row.watched_titles)}}</strong><span class="muted">${{currentLanguage === 'zh' ? '你已看过' : 'Watched by you'}}</span></div>
            <div><strong>${{formatRating(row.avg_letterboxd_rating)}}</strong><span class="muted">${{currentLanguage === 'zh' ? '已索引片均分' : 'Indexed LB avg'}}</span></div>
            <div><strong>${{formatOneDecimal(row.avg_douban_rating)}}</strong><span class="muted">${{currentLanguage === 'zh' ? '豆瓣均分' : 'Douban avg'}}</span></div>
            <div><strong>${{formatRating(row.avg_user_rating)}}</strong><span class="muted">${{currentLanguage === 'zh' ? '已看样本均分' : 'Your watched avg'}}</span></div>
          </div>
          ${{row.catalog_note ? `<div class="provider-note">${{row.catalog_note}}</div>` : ''}}
        </div>
      `).join('');
    }}

    function renderStreamingProviderSummaryChart() {{
      const summary = data.streaming.summary;
      Plotly.newPlot('streaming-provider-summary-chart', [
        {{
          type: 'bar',
          name: '当前可看',
          x: summary.map(row => wrapLabel(row.provider, 14)),
          y: summary.map(row => row.available_titles),
          marker: {{color: '#2d6f8e'}},
        }},
        {{
          type: 'bar',
          name: '你看过',
          x: summary.map(row => wrapLabel(row.provider, 14)),
          y: summary.map(row => row.watched_titles),
          marker: {{color: '#b75b49'}},
        }},
        {{
          type: 'bar',
          name: '平台独占',
          x: summary.map(row => wrapLabel(row.provider, 14)),
          y: summary.map(row => row.exclusive_titles),
          marker: {{color: '#c48a3a'}},
        }}
      ], {{
        ...plotLayout,
        title: plotTitle('Current catalog comparison by platform'),
        barmode: 'group',
        xaxis: {{automargin: true}},
        height: 360,
      }}, plotConfig);
    }}

    function renderStreamingSection() {{
      const rows = getFilteredStreamingRows();
      const scoredRows = rows.filter(row => row.letterboxd_rating !== null && row.letterboxd_rating !== undefined);
      document.getElementById('streaming-results-summary').textContent =
        currentLanguage === 'zh'
          ? `当前筛选结果 ${{formatCount(rows.length)}} 部；其中 ${{formatCount(scoredRows.length)}} 部已匹配 Letterboxd 评分。平台片单缓存覆盖 ${{formatCount(data.streaming.stats.indexed_titles)}} / ${{formatCount(data.streaming.stats.provider_titles)}} 部；另纳入 ${{formatCount(data.streaming.stats.watched_not_available_titles || 0)}} 部暂未在追踪平台发现的已看影片。`
          : `${{formatCount(rows.length)}} titles match the current filters; ${{formatCount(scoredRows.length)}} have Letterboxd scores. The provider cache covers ${{formatCount(data.streaming.stats.indexed_titles)}} / ${{formatCount(data.streaming.stats.provider_titles)}} catalogue titles, plus ${{formatCount(data.streaming.stats.watched_not_available_titles || 0)}} watched titles not found on tracked platforms.`;
      document.getElementById('streaming-data-note').textContent =
        (data.streaming.provider_warnings || []).map(row => `${{row.provider}}: ${{row.note}}`).join('  ');

      const topRows = scoredRows.slice(0, 10);
      const topPlotRows = [...topRows].reverse();
      Plotly.newPlot('streaming-ranking-chart', [{{
        type: 'scatter',
        mode: 'markers+text',
        y: topPlotRows.map(row => wrapLabel(`${{shortenLabel(row.name, 44)}} (${{row.year ?? '—'}})`, 28)),
        x: topPlotRows.map(row => row.letterboxd_rating),
        text: topPlotRows.map(row => formatRating(row.letterboxd_rating)),
        textposition: 'middle right',
        cliponaxis: false,
        marker: {{
          color: topPlotRows.map(row => row.watched ? '#b75b49' : row.exclusive ? '#c48a3a' : '#2d6f8e'),
          size: topPlotRows.map(row => Math.min(30, Math.max(12, 8 + Math.log10(Number(row.letterboxd_rating_count || 1) + 1) * 4))),
          opacity: 0.84,
          line: {{color: '#fffaf2', width: 1.5}},
        }},
        customdata: topPlotRows.map(row => [
          formatCount(row.letterboxd_rating_count),
          formatOneDecimal(row.douban_rating),
          (row.providers || []).join(', ')
        ]),
        hovertemplate: 'Letterboxd: %{{x:.2f}} (%{{customdata[0]}} ratings)<br>Douban: %{{customdata[1]}}<br>Platforms: %{{customdata[2]}}<extra></extra>',
      }}], {{
        ...plotLayout,
        title: plotTitle('Top filtered titles by Letterboxd score'),
        margin: {{t: 52, r: 76, b: 46, l: 164}},
        xaxis: {{range: focusedRange(topRows, 'letterboxd_rating'), automargin: true, title: 'Letterboxd rating'}},
        yaxis: {{automargin: true}},
        height: barChartHeight(topRows.length, 160, 34, 620),
      }}, plotConfig);

      makeTable(
        document.getElementById('streaming-table'),
        [
          {{key: 'rank', label: '#'}},
          {{key: 'name', label: t('film')}},
          {{key: 'year', label: t('year')}},
          {{key: 'genres', label: t('genres')}},
          {{key: 'providers', label: t('platforms')}},
          {{key: 'letterboxd_rating', label: t('lbRating')}},
          {{key: 'douban_rating', label: t('douban')}},
          {{key: 'letterboxd_rating_count', label: t('lbRatings')}},
          {{key: 'status', label: t('status')}},
          {{key: 'user_rating', label: t('yourRating')}},
          {{key: 'imdb_score', label: 'IMDb'}},
          {{key: 'links', label: t('links')}},
        ],
        rows.slice(0, 80).map(row => ({{
          rank: row.rank ?? '—',
          name: row.name,
          year: row.year ?? '—',
          genres: (row.genre_labels || []).length ? row.genre_labels.join(' / ') : '—',
          providers: row.available_on_tracked_platforms
            ? `<div class="inline-links">${{(row.provider_links || []).map(link => `<a href="${{link.url}}" target="_blank" rel="noopener noreferrer">${{link.provider}}</a>`).join('<br>') || '—'}}</div>`
            : `<span class="muted">${{currentLanguage === 'zh' ? '未在追踪平台发现' : 'Not available on tracked platforms'}}</span>`,
          letterboxd_rating: row.letterboxd_rating === null || row.letterboxd_rating === undefined ? (currentLanguage === 'zh' ? '未匹配' : 'Unmatched') : formatRating(row.letterboxd_rating),
          douban_rating: row.douban_rating === null || row.douban_rating === undefined ? '—' : formatOneDecimal(row.douban_rating),
          letterboxd_rating_count: row.letterboxd_rating_count ? formatCount(row.letterboxd_rating_count) : '—',
          status: row.watched
            ? (!row.available_on_tracked_platforms
              ? (currentLanguage === 'zh' ? '已看 · 暂无平台' : 'Watched · Not available')
              : (row.exclusive ? (currentLanguage === 'zh' ? '已看 · 独占' : 'Watched · Exclusive') : (currentLanguage === 'zh' ? '已看' : 'Watched')))
            : (row.exclusive ? (currentLanguage === 'zh' ? '未看 · 独占' : 'Unwatched · Exclusive') : (currentLanguage === 'zh' ? '未看' : 'Unwatched')),
          user_rating: row.user_rating === null || row.user_rating === undefined ? '—' : formatRating(row.user_rating),
          imdb_score: row.imdb_score === null || row.imdb_score === undefined ? '—' : Number(row.imdb_score).toFixed(1),
          links: `<div class="inline-links">${{[
            row.letterboxd_url ? `<a href="${{row.letterboxd_url}}" target="_blank" rel="noopener noreferrer">Letterboxd</a>` : '',
            row.douban_url ? `<a href="${{row.douban_url}}" target="_blank" rel="noopener noreferrer">Douban</a>` : ''
          ].filter(Boolean).join('<br>') || '—'}}</div>`,
        }}))
      );
    }}

    function initRecommendationControls() {{
      const providerSelect = document.getElementById('recommendation-provider-filter');
      const selectedProvider = providerSelect.value || 'all';
      providerSelect.innerHTML = `<option value="all">${{t('allPlatforms')}}</option>` + (data.recommendations.platform_options || [])
        .map(row => `<option value="${{row.label}}">${{row.label}}</option>`)
        .join('');
      providerSelect.value = [...providerSelect.options].some(option => option.value === selectedProvider) ? selectedProvider : 'all';

      renderPillGroup(
        'recommendation-genre-include-pills',
        data.recommendations.genre_options || [],
        recommendationGenreIncludeSelection,
        t('allGenres'),
        renderRecommendations
      );
      renderPillGroup(
        'recommendation-genre-exclude-pills',
        data.recommendations.genre_options || [],
        recommendationGenreExcludeSelection,
        t('noExclusions'),
        renderRecommendations
      );

      [
        'recommendation-watchlist-filter',
        'recommendation-list-filter',
        'recommendation-streaming-filter',
        'recommendation-provider-filter',
        'recommendation-sort-filter',
      ].forEach(id => {{
        const element = document.getElementById(id);
        if (!element.dataset.bound) {{
          element.addEventListener('change', renderRecommendations);
          element.dataset.bound = 'true';
        }}
      }});
    }}

    function getFilteredRecommendations() {{
      const watchlistFilter = document.getElementById('recommendation-watchlist-filter').value;
      const listFilter = document.getElementById('recommendation-list-filter').value;
      const streamingFilter = document.getElementById('recommendation-streaming-filter').value;
      const providerFilter = document.getElementById('recommendation-provider-filter').value;
      const sortFilter = document.getElementById('recommendation-sort-filter').value;
      const includeGenres = [...recommendationGenreIncludeSelection];
      const excludeGenres = [...recommendationGenreExcludeSelection];

      const rows = (data.recommendations.rows || []).filter(row => {{
        const genres = row.genres || [];
        if (watchlistFilter === 'in' && !row.in_watchlist) return false;
        if (watchlistFilter === 'out' && row.in_watchlist) return false;
        if (listFilter === 'in' && !row.in_user_lists) return false;
        if (listFilter === 'out' && row.in_user_lists) return false;
        if (streamingFilter === 'in' && !row.currently_streaming) return false;
        if (streamingFilter === 'out' && row.currently_streaming) return false;
        if (providerFilter !== 'all' && !(row.providers || []).includes(providerFilter)) return false;
        if (includeGenres.length && !includeGenres.some(genre => genres.includes(genre))) return false;
        if (excludeGenres.some(genre => genres.includes(genre))) return false;
        return true;
      }});

      const sorted = [...rows].sort((left, right) => {{
        if (sortFilter === 'predicted') {{
          if ((right.predicted_rating ?? -1) !== (left.predicted_rating ?? -1)) return (right.predicted_rating ?? -1) - (left.predicted_rating ?? -1);
          return (right.priority_score ?? -1) - (left.priority_score ?? -1);
        }}
        if (sortFilter === 'site') {{
          if ((right.site_average_rating ?? -1) !== (left.site_average_rating ?? -1)) return (right.site_average_rating ?? -1) - (left.site_average_rating ?? -1);
          return (right.site_rating_count ?? -1) - (left.site_rating_count ?? -1);
        }}
        if ((right.priority_score ?? -1) !== (left.priority_score ?? -1)) return (right.priority_score ?? -1) - (left.priority_score ?? -1);
        return (right.predicted_rating ?? -1) - (left.predicted_rating ?? -1);
      }});
      return sorted.map((row, index) => ({{
        ...row,
        filtered_rank: index + 1,
      }}));
    }}

    function renderRecommendations() {{
      const source = getFilteredRecommendations();
      document.getElementById('recommendation-results-summary').textContent =
        currentLanguage === 'zh'
          ? `当前筛选结果 ${{formatCount(source.length)}} 部候选；总池子 ${{formatCount(data.recommendations.stats.candidate_count)}} 部，其中 ${{formatCount(data.recommendations.stats.discovery_titles)}} 部属于 watchlist 和自建 lists 之外的外部发现。`
          : `${{formatCount(source.length)}} candidates match the current filters. The full pool has ${{formatCount(data.recommendations.stats.candidate_count)}} titles, including ${{formatCount(data.recommendations.stats.discovery_titles)}} outside watchlist and exported lists.`;

      const topRows = source.slice(0, 10);
      const topPlotRows = [...topRows].reverse();
      const priorityValues = numericValues(topRows, 'priority_score');
      const priorityRange = priorityValues.length
        ? [Math.max(0, Math.min(...priorityValues) - 1), Math.max(...priorityValues) + 1]
        : [0, 1];
      Plotly.newPlot('recommendation-priority-chart', [{{
        type: 'scatter',
        mode: 'markers+text',
        y: topPlotRows.map(row => wrapLabel(`${{shortenLabel(row.name, 44)}} (${{row.year ?? '—'}})`, 28)),
        x: topPlotRows.map(row => row.priority_score),
        text: topPlotRows.map(row => Number(row.priority_score).toFixed(1)),
        textposition: 'middle right',
        cliponaxis: false,
        marker: {{
          color: topPlotRows.map(row => {{
            if (row.discovery_only) return '#2d6f8e';
            if (row.currently_streaming) return '#c48a3a';
            if (row.in_watchlist) return '#b75b49';
            return '#17233b';
          }}),
          size: topPlotRows.map(row => Math.min(30, Math.max(12, 9 + Number(row.confidence || 0.5) * 14))),
          opacity: 0.84,
          line: {{color: '#fffaf2', width: 1.5}},
        }},
        customdata: topPlotRows.map(row => {{
          const providers = (row.providers || []).slice(0, 2).join(', ');
          return [formatRating(row.predicted_rating), formatRating(row.site_average_rating), providers];
        }}),
        hovertemplate: 'Priority: %{{x:.1f}}<br>Predicted rating: %{{customdata[0]}}<br>Letterboxd: %{{customdata[1]}}<br>Platforms: %{{customdata[2]}}<extra></extra>',
      }}], {{
        ...plotLayout,
        title: plotTitle('Filtered recommendation priority'),
        margin: {{t: 52, r: 76, b: 46, l: 164}},
        xaxis: {{range: priorityRange, automargin: true, title: 'Priority score'}},
        yaxis: {{automargin: true}},
        height: barChartHeight(topRows.length, 160, 34, 620),
      }}, plotConfig);

      makeTable(
        document.getElementById('recommendation-table'),
        [
          {{key: 'rank', label: '#'}},
          {{key: 'name', label: t('film')}},
          {{key: 'year', label: t('year')}},
          {{key: 'genres', label: t('genres')}},
          {{key: 'priority_score', label: t('priority')}},
          {{key: 'predicted_rating', label: t('predicted')}},
          {{key: 'site_average_rating', label: 'LB'}},
          {{key: 'availability', label: t('available')}},
          {{key: 'membership', label: t('inYourData')}},
          {{key: 'reason', label: t('reason')}},
        ],
        source.slice(0, 40).map(row => ({{
          rank: row.filtered_rank,
          name: row.name,
          year: row.year ?? '—',
          genres: (row.genres || []).join(' / ') || '—',
          priority_score: row.priority_score.toFixed ? row.priority_score.toFixed(1) : row.priority_score,
          predicted_rating: row.predicted_rating.toFixed ? row.predicted_rating.toFixed(2) : row.predicted_rating,
          site_average_rating: row.site_average_rating ? formatRating(row.site_average_rating) : '—',
          availability: row.currently_streaming ? ((row.providers || []).join(', ') || 'Yes') : '—',
          membership: [
            row.in_watchlist ? 'Watchlist' : null,
            row.in_user_lists ? 'My lists' : null,
            row.discovery_only ? (currentLanguage === 'zh' ? '外部发现' : 'External discovery') : null,
          ].filter(Boolean).join(' / ') || '—',
          reason: row.reason,
        }}))
      );
    }}

    function refreshTranslatedViews() {{
      renderWatchedDoubanCharts();
      renderGenreCountry(document.getElementById('genre-select').value);
      renderHeatmaps();
      renderTagPieCharts();
      renderTagCharts();
      renderReviewCharts();
      renderListCharts();
      initStreamingControls();
      renderStreamingProviderCards();
      renderStreamingProviderSummaryChart();
      renderStreamingSection();
      initRecommendationControls();
      renderRecommendations();
    }}

    document.querySelectorAll('[data-language-choice]').forEach(button => {{
      button.addEventListener('click', () => applyLanguage(button.dataset.languageChoice, true));
    }});
    applyLanguage(currentLanguage, false);
    renderGenreSelect();
    renderGenreCountry(document.getElementById('genre-select').value);
    renderHeatmaps();
    renderWatchedDoubanCharts();
    renderTagPieCharts();
    renderTagCharts();
    renderReviewCharts();
    renderListCharts();
    initStreamingControls();
    renderStreamingProviderCards();
    renderStreamingProviderSummaryChart();
    renderStreamingSection();
    initRecommendationControls();
    renderRecommendations();
  </script>
</body>
</html>
"""


def build_share_readme() -> str:
    return """# Share Site

This folder is a deployment-ready static site.

## Files

- `index.html`: the shareable page to host
- `custom-report-data.json`: the embedded source data in JSON form
- `.nojekyll`: keeps GitHub Pages from rewriting the site

## Fastest ways to share

### GitHub Pages

1. Create a new GitHub repository.
2. Upload everything in this folder to the repository root.
3. In GitHub, open `Settings` -> `Pages`.
4. Set the source to `Deploy from a branch`, pick `main`, and save.

### Netlify

1. Open Netlify.
2. Drag this whole folder into the deploy area.
3. Netlify will publish it as a static site immediately.

### Local preview

Run this inside the folder:

```bash
python3 -m http.server 8000
```

Then open `http://localhost:8000`.
"""


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_path = output_dir / "film_metadata_cache.json"
    parent_cache_path = output_dir.parent / "film_metadata_cache.json"

    if not cache_path.exists() and parent_cache_path.exists():
        cache_path.write_text(parent_cache_path.read_text(encoding="utf-8"), encoding="utf-8")

    ratings_df = load_csv(input_dir / "ratings.csv")
    diary_df = load_csv(input_dir / "diary.csv")
    reviews_df = load_csv(input_dir / "reviews.csv")
    watchlist_df = load_csv(input_dir / "watchlist.csv")
    profile_df = load_csv(input_dir / "profile.csv")
    list_entries_df = load_list_exports(input_dir / "lists")

    for frame in (ratings_df, diary_df, reviews_df, watchlist_df):
        frame["film_key"] = frame.apply(lambda row: film_key(row.get("Name"), row.get("Year")), axis=1)
    if not list_entries_df.empty:
        list_entries_df["list_category"] = list_entries_df.apply(
            lambda row: classify_list(row["list_title"], row["list_description"]),
            axis=1,
        )

    ratings_df["user_rating"] = pd.to_numeric(ratings_df["Rating"], errors="coerce")
    ratings_df["year"] = pd.to_numeric(ratings_df["Year"], errors="coerce")
    ratings_df["logged_date"] = pd.to_datetime(ratings_df["Date"], errors="coerce")
    ratings_df["decade_label"] = ratings_df["year"].dropna().floordiv(10).mul(10).astype("Int64").astype(str) + "s"
    ratings_df.loc[ratings_df["year"].isna(), "decade_label"] = None

    diary_df["user_rating"] = pd.to_numeric(diary_df["Rating"], errors="coerce")
    diary_df["year"] = pd.to_numeric(diary_df["Year"], errors="coerce")
    diary_df["logged_date"] = pd.to_datetime(diary_df["Date"], errors="coerce")
    diary_df["watched_date"] = pd.to_datetime(diary_df["Watched Date"], errors="coerce")
    diary_df["rewatch"] = diary_df["Rewatch"].fillna("").astype(str).str.strip().ne("")
    diary_df["tags_list"] = diary_df["Tags"].apply(split_tags)

    reviews_df["user_rating"] = pd.to_numeric(reviews_df["Rating"], errors="coerce")
    reviews_df["tags_list"] = reviews_df["Tags"].apply(split_tags)

    watchlist_df["year"] = pd.to_numeric(watchlist_df["Year"], errors="coerce")
    watchlist_df["added_date"] = pd.to_datetime(watchlist_df["Date"], errors="coerce")

    uri_sources = [
        ratings_df[["Letterboxd URI", "Name", "Year"]],
        watchlist_df[["Letterboxd URI", "Name", "Year"]],
        list_entries_df[["Letterboxd URI", "Name", "Year"]] if not list_entries_df.empty else pd.DataFrame(),
    ]
    source_df = pd.concat(uri_sources, ignore_index=True).drop_duplicates(subset=["Letterboxd URI"])
    source_df = source_df[source_df["Letterboxd URI"].fillna("").astype(str) != ""]

    metadata_df = fetch_metadata(
        source_df["Letterboxd URI"].astype(str).tolist(),
        cache_path=cache_path,
        workers=max(1, args.workers),
        refresh_cache=args.refresh_cache,
    )

    def attach_metadata(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame
        merged = frame.merge(metadata_df, how="left", left_on="Letterboxd URI", right_on="source_uri")
        merged["runtime_bucket"] = build_runtime_bucket(merged["runtime_minutes"])
        if "year" in merged.columns:
            merged["decade_label"] = merged["year"].dropna().floordiv(10).mul(10).astype("Int64").astype(str) + "s"
            merged.loc[merged["year"].isna(), "decade_label"] = merged.get("decade_label")
        return merged

    ratings_df = attach_metadata(ratings_df)
    watchlist_df = attach_metadata(watchlist_df)
    for frame in (ratings_df, watchlist_df):
        if "countries" in frame.columns:
            frame["countries"] = frame["countries"].apply(relabel_origin_list)
    watched_douban_section, ratings_df = build_watched_douban_section(
        ratings_df,
        output_dir=output_dir,
        max_new_lookups=max(0, args.watched_douban_lookups),
        workers=max(1, args.workers),
        refresh_cache=args.refresh_cache,
    )
    diary_lookup = ratings_df[
        [
            "film_key",
            "directors",
            "actors",
            "genres",
            "countries",
            "site_average_rating",
            "site_rating_count",
            "runtime_minutes",
            "runtime_bucket",
            "decade_label",
        ]
    ].drop_duplicates(subset=["film_key"])
    diary_df = diary_df.merge(diary_lookup, how="left", on="film_key")
    reviews_df = reviews_df.merge(diary_lookup, how="left", on="film_key")
    for frame in (diary_df, reviews_df):
        if "countries" in frame.columns:
            frame["countries"] = frame["countries"].apply(relabel_origin_list)

    if not list_entries_df.empty:
        list_entries_df = attach_metadata(list_entries_df)
        if "countries" in list_entries_df.columns:
            list_entries_df["countries"] = list_entries_df["countries"].apply(relabel_origin_list)
        watched_keys = set(ratings_df["film_key"])
        list_entries_df["watched"] = list_entries_df["film_key"].isin(watched_keys)
        list_entries_df = list_entries_df.merge(
            ratings_df[["film_key", "user_rating"]],
            how="left",
            on="film_key",
            suffixes=("", "_rated"),
        )

    diary_df = derive_tag_columns(diary_df)
    reviews_df = derive_tag_columns(reviews_df)

    global_mean = float(ratings_df["user_rating"].mean())
    site_mean = float(ratings_df["site_average_rating"].dropna().mean())

    genre_country = build_genre_country_section(ratings_df)
    tags_section = build_tag_section(diary_df)
    review_section = build_review_section(reviews_df)
    list_section = build_list_section(list_entries_df, ratings_df)
    streaming_section = build_streaming_section(
        ratings_df,
        output_dir=output_dir,
        max_new_lookups=max(0, args.streaming_lookups),
        max_douban_lookups=max(0, args.douban_lookups),
        workers=max(1, args.streaming_workers),
        catalog_timeout=max(0, args.streaming_catalog_timeout),
        refresh_cache=args.refresh_cache,
    )
    candidate_pool = build_recommendation_pool(ratings_df, watchlist_df, list_entries_df, streaming_section)
    recommendations = score_recommendations(ratings_df, candidate_pool, global_mean, site_mean)
    recommendation_payload = build_recommendation_payload(recommendations)
    daily_signal_section = build_daily_signal_section(
        ratings_df,
        recommendations,
        streaming_section,
        output_dir=output_dir,
    )

    metrics = {
        "unique_rated_films": int(len(ratings_df)),
        "watch_events": int(len(diary_df)),
        "tagged_watch_events": int(diary_df["tags_list"].apply(len).gt(0).sum()),
        "custom_lists": int(list_entries_df["list_title"].nunique()),
        "candidate_pool_size": int(len(recommendations)),
        "streaming_indexed_titles": int(streaming_section["stats"]["scored_titles"]),
        "douban_rated_titles": int(watched_douban_section["stats"]["douban_rated_titles"]),
    }

    payload = {
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
        "profile": {
            "username": normalize_cell(profile_df.iloc[0]["Username"]) if len(profile_df) else "",
        },
        "metrics": metrics,
        "genre_country": genre_country,
        "tags": tags_section,
        "reviews": review_section,
        "lists": list_section,
        "watched_douban": watched_douban_section,
        "streaming": streaming_section,
        "recommendations": recommendation_payload,
        "daily_signal": daily_signal_section,
    }
    payload["custom_insights"] = build_custom_insights(
        genre_country,
        tags_section,
        review_section,
        list_section,
        streaming_section,
        recommendations,
    )

    json_path = output_dir / "custom-report-data.json"
    html_path = output_dir / "custom-letterboxd-report.html"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    html_content = build_html(payload)
    html_path.write_text(html_content, encoding="utf-8")

    share_dir = output_dir / "share-site"
    share_dir.mkdir(parents=True, exist_ok=True)
    (share_dir / "index.html").write_text(html_content, encoding="utf-8")
    (share_dir / "custom-report-data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (share_dir / "README.md").write_text(build_share_readme(), encoding="utf-8")
    (share_dir / ".nojekyll").write_text("", encoding="utf-8")

    print(share_dir / "index.html")


if __name__ == "__main__":
    main()
