#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

VENDOR_DIR = Path(__file__).resolve().parent.parent / ".vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))

try:
    from curl_cffi import requests as curl_requests
except ImportError as exc:  # pragma: no cover - surfaced at runtime
    raise RuntimeError(
        "Missing dependency: curl_cffi. Install dependencies first or run the existing generator once."
    ) from exc

from lxml import html as lxml_html


LETTERBOXD_BASE_URL = "https://letterboxd.com"
LETTERBOXD_IMPERSONATE = "chrome136"
DEFAULT_TIMEOUT_SECONDS = 30
MONTH_LOOKUP = {
    "Jan": "01",
    "Feb": "02",
    "Mar": "03",
    "Apr": "04",
    "May": "05",
    "Jun": "06",
    "Jul": "07",
    "Aug": "08",
    "Sep": "09",
    "Oct": "10",
    "Nov": "11",
    "Dec": "12",
}

_THREAD_LOCAL = threading.local()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync public Letterboxd pages into a builder-compatible local export."
    )
    parser.add_argument("--username", required=True, help="Letterboxd username")
    parser.add_argument("--output-dir", required=True, help="Directory for generated CSVs")
    parser.add_argument("--cache-dir", required=True, help="Directory for HTML-derived caches")
    parser.add_argument(
        "--workers",
        type=int,
        default=6,
        help="Concurrent requests for individual diary/review entry pages",
    )
    parser.add_argument(
        "--refresh-recent",
        type=int,
        default=60,
        help="Always refresh the newest N diary/review entry pages even if they are cached",
    )
    parser.add_argument(
        "--force-refresh-all-entry-pages",
        action="store_true",
        help="Ignore the cached diary/review entry page details",
    )
    return parser.parse_args()


def normalize_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_whitespace(value: Any) -> str:
    return re.sub(r"\s+", " ", normalize_cell(value)).strip()


def absolute_url(path_or_url: str) -> str:
    raw = normalize_cell(path_or_url)
    if not raw:
        return ""
    return urljoin(f"{LETTERBOXD_BASE_URL}/", raw)


def parse_name_year(display_name: str) -> tuple[str, str]:
    text = normalize_whitespace(display_name)
    match = re.match(r"^(.*?)(?:\s+\((\d{4})\))?$", text)
    if not match:
        return text, ""
    return normalize_whitespace(match.group(1)), normalize_cell(match.group(2))


def parse_star_rating(value: Any) -> str:
    text = normalize_whitespace(value)
    if not text:
        return ""
    numeric_match = re.fullmatch(r"\d+(?:\.\d+)?", text)
    if numeric_match:
        return text
    stars = text.count("★")
    half_stars = text.count("½")
    if stars or half_stars:
        return f"{stars + 0.5 * half_stars:g}"
    return ""


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def get_session() -> Any:
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is None:
        session = curl_requests.Session(impersonate=LETTERBOXD_IMPERSONATE)
        _THREAD_LOCAL.session = session
    return session


def fetch_text(url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = get_session().get(
                absolute_url(url),
                timeout=timeout,
                headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            response.raise_for_status()
            if response.text:
                return response.text
            raise RuntimeError("Empty response text")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(0.75 * (attempt + 1))
    raise RuntimeError(f"Letterboxd request failed for {url}: {normalize_cell(last_error)}")


def parse_html(url: str) -> Any:
    return lxml_html.fromstring(fetch_text(url))


def optional_html(url: str) -> Any | None:
    try:
        return parse_html(url)
    except Exception:  # noqa: BLE001
        return None


def iter_paginated_pages(start_url: str) -> list[tuple[str, Any]]:
    pages: list[tuple[str, Any]] = []
    seen: set[str] = set()
    current_url = absolute_url(start_url)
    while current_url and current_url not in seen:
        seen.add(current_url)
        tree = parse_html(current_url)
        pages.append((current_url, tree))
        next_links = tree.xpath(
            "//a[@rel='next']/@href | "
            "//li[contains(@class,'paginate-nextprev')]//a/@href | "
            "//a[contains(@class,'next')]/@href"
        )
        current_url = absolute_url(next_links[0]) if next_links else ""
    return pages


def parse_iso_date(year_text: str, month_text: str, day_text: str) -> str:
    year = normalize_cell(year_text)
    month = MONTH_LOOKUP.get(normalize_cell(month_text), "")
    day = normalize_cell(day_text).zfill(2)
    if not (year and month and day):
        return ""
    return f"{year}-{month}-{day}"


def parse_profile_name_from_rss(rss_text: str) -> str:
    try:
        root = ET.fromstring(rss_text)
    except ET.ParseError:
        return ""
    title = root.findtext("./channel/title", default="")
    return normalize_whitespace(title.replace("Letterboxd -", "", 1))


def parse_rss_review_links(rss_text: str) -> list[str]:
    try:
        root = ET.fromstring(rss_text)
    except ET.ParseError:
        return []
    links: list[str] = []
    for item in root.findall("./channel/item"):
        link = normalize_cell(item.findtext("link", default=""))
        if link:
            links.append(absolute_url(link))
    return links


def parse_diary_pages(username: str) -> list[dict[str, str]]:
    pages = iter_paginated_pages(f"https://letterboxd.com/{username}/diary/films/")
    rows: list[dict[str, str]] = []
    for _page_url, tree in pages:
        current_month = ""
        current_year = ""
        for row in tree.xpath("//tr[contains(@class,'diary-entry-row')]"):
            poster = row.xpath(".//div[@data-component-class='LazyPoster'][1]")
            if not poster:
                continue
            poster = poster[0]
            name, year = parse_name_year(poster.get("data-item-name"))
            film_uri = absolute_url(poster.get("data-item-link"))
            entry_uri = absolute_url(poster.get("data-target-link"))
            month = normalize_cell(row.xpath("string(.//a[contains(@class,'month')][1])"))
            day = row.xpath("string(.//a[contains(@class,'daydate')][1])")
            year_text = normalize_cell(row.xpath("string(.//a[contains(@class,'year')][1])"))
            if month:
                current_month = month
            if year_text:
                current_year = year_text
            watched_date = parse_iso_date(current_year, current_month, day)
            rating_value = normalize_cell(
                row.xpath("string(.//input[contains(@class,'diary-rating-')]/@value)")
            )
            if rating_value:
                try:
                    rating = f"{float(rating_value) / 2:g}"
                except ValueError:
                    rating = ""
            else:
                rating = parse_star_rating(row.xpath("string(.//span[contains(@class,'rating')][1])"))
            rewatch_class = normalize_whitespace(
                " ".join(row.xpath(".//td[contains(@class,'col-rewatch')][1]/@class"))
            )
            rewatch = "Yes" if row.xpath(".//*[contains(@class,'icon-rewatch')]") and "icon-status-off" not in rewatch_class else ""
            rows.append(
                {
                    "Date": watched_date,
                    "Name": name,
                    "Year": year,
                    "Letterboxd URI": film_uri,
                    "Rating": rating,
                    "Rewatch": rewatch,
                    "Tags": "",
                    "Watched Date": watched_date,
                    "Entry URL": entry_uri or film_uri,
                }
            )
    return rows


def parse_ratings_pages(username: str) -> list[dict[str, str]]:
    pages = iter_paginated_pages(f"https://letterboxd.com/{username}/films/ratings/")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for _page_url, tree in pages:
        for item in tree.xpath("//li[contains(@class,'griditem')]"):
            poster = item.xpath(".//div[@data-component-class='LazyPoster'][1]")
            if not poster:
                continue
            poster = poster[0]
            film_uri = absolute_url(poster.get("data-item-link"))
            if not film_uri or film_uri in seen:
                continue
            seen.add(film_uri)
            name, year = parse_name_year(poster.get("data-item-name"))
            rating = parse_star_rating(item.xpath("string(.//p[contains(@class,'poster-viewingdata')]//span[contains(@class,'rating')][1])"))
            rows.append(
                {
                    "Date": "",
                    "Name": name,
                    "Year": year,
                    "Letterboxd URI": film_uri,
                    "Rating": rating,
                }
            )
    return rows


def parse_watchlist_pages(username: str) -> list[dict[str, str]]:
    pages = iter_paginated_pages(f"https://letterboxd.com/{username}/watchlist/")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for _page_url, tree in pages:
        for item in tree.xpath("//li[contains(@class,'griditem')]"):
            poster = item.xpath(".//div[@data-component-class='LazyPoster'][1]")
            if not poster:
                continue
            poster = poster[0]
            film_uri = absolute_url(poster.get("data-item-link"))
            if not film_uri or film_uri in seen:
                continue
            seen.add(film_uri)
            name, year = parse_name_year(poster.get("data-item-name"))
            rows.append(
                {
                    "Date": "",
                    "Name": name,
                    "Year": year,
                    "Letterboxd URI": film_uri,
                }
            )
    return rows


def parse_reviews_pages(username: str) -> list[dict[str, str]]:
    pages = iter_paginated_pages(f"https://letterboxd.com/{username}/reviews/films/")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for _page_url, tree in pages:
        for article in tree.xpath("//article[contains(@class,'production-viewing')]"):
            review_url = absolute_url(article.xpath("string(.//h2/a[1]/@href)"))
            if not review_url or review_url in seen:
                continue
            seen.add(review_url)
            poster = article.xpath(".//div[@data-component-class='LazyPoster'][1]")
            if not poster:
                continue
            poster = poster[0]
            name, year = parse_name_year(poster.get("data-item-name"))
            film_uri = absolute_url(poster.get("data-item-link"))
            rating = parse_star_rating(article.xpath("string(.//span[contains(@class,'inline-rating')]//title[1])"))
            watched_date = normalize_cell(article.xpath("string(.//time[contains(@class,'timestamp')][1]/@datetime)"))
            rows.append(
                {
                    "Date": watched_date,
                    "Name": name,
                    "Year": year,
                    "Letterboxd URI": film_uri,
                    "Rating": rating,
                    "Review": "",
                    "Tags": "",
                    "Entry URL": review_url,
                }
            )
    return rows


def parse_list_index_pages(username: str) -> list[dict[str, str]]:
    pages = iter_paginated_pages(f"https://letterboxd.com/{username}/lists/")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for _page_url, tree in pages:
        for article in tree.xpath("//article[contains(@class,'list-summary')]"):
            list_url = absolute_url(article.xpath("string(.//a[contains(@class,'poster-list-link')][1]/@href)"))
            if not list_url or list_url in seen:
                continue
            seen.add(list_url)
            title = normalize_whitespace(article.xpath("string(.//h2[1])"))
            texts = [normalize_whitespace(text) for text in article.xpath(".//text()")]
            texts = [text for text in texts if text]
            description = ""
            if texts:
                filtered = [text for text in texts if text not in {title, "Edit list"} and "films" not in text]
                if filtered:
                    description = filtered[-1]
            rows.append(
                {
                    "title": title,
                    "url": list_url,
                    "description": description,
                }
            )
    return rows


def parse_meta_content(tree: Any, property_name: str) -> str:
    return normalize_whitespace(
        tree.xpath(f"string(//meta[@property='{property_name}'][1]/@content)")
        or tree.xpath(f"string(//meta[@name='{property_name}'][1]/@content)")
    )


def parse_list_detail(list_url: str) -> dict[str, Any]:
    pages = iter_paginated_pages(list_url)
    if not pages:
        return {"title": "", "url": list_url, "description": "", "tags": [], "entries": []}

    first_tree = pages[0][1]
    title = parse_meta_content(first_tree, "og:title")
    if title.endswith(", a list of films by Gavin Chen"):
        title = title[: title.rfind(", a list of films by ")]
    description = parse_meta_content(first_tree, "og:description")
    tag_values = [
        normalize_whitespace(tag)
        for tag in first_tree.xpath("//ul[contains(@class,'tags')]//a/text()")
        if normalize_whitespace(tag)
    ]

    entries: list[dict[str, str]] = []
    for _page_url, tree in pages:
        for item in tree.xpath("//ul[contains(@class,'poster-list')]//li[contains(@class,'posteritem')]"):
            poster = item.xpath(".//div[@data-component-class='LazyPoster'][1]")
            if not poster:
                continue
            poster = poster[0]
            name, year = parse_name_year(poster.get("data-item-name"))
            film_uri = absolute_url(poster.get("data-item-link"))
            index_text = normalize_cell(poster.get("data-list-index") or item.get("data-list-index"))
            try:
                position = str(int(index_text) + 1) if index_text else ""
            except ValueError:
                position = ""
            entries.append(
                {
                    "position": position,
                    "Name": name,
                    "Year": year,
                    "Letterboxd URI": film_uri,
                    "entry_description": "",
                }
            )
    return {
        "title": title,
        "url": list_url,
        "description": description,
        "tags": tag_values,
        "entries": entries,
    }


def load_entry_detail_cache(cache_path: Path) -> dict[str, Any]:
    cache = load_json(cache_path)
    return cache if isinstance(cache, dict) else {}


def parse_entry_detail(entry_url: str) -> dict[str, Any]:
    tree = parse_html(entry_url)
    tags = [
        normalize_whitespace(tag)
        for tag in tree.xpath("//ul[contains(@class,'tags')]//a/text()")
        if normalize_whitespace(tag)
    ]
    review_lines = [
        normalize_whitespace(text)
        for text in tree.xpath("//div[contains(@class,'js-review-body')]//text()")
        if normalize_whitespace(text)
    ]
    review_text = " ".join(review_lines).strip()
    return {
        "entry_url": absolute_url(entry_url),
        "tags": tags,
        "review": review_text,
    }


def update_entry_detail_cache(
    entry_urls: list[str],
    force_refresh_urls: set[str],
    cache_path: Path,
    workers: int,
    force_refresh_all: bool,
) -> dict[str, Any]:
    cache = load_entry_detail_cache(cache_path)
    pending = [
        entry_url
        for entry_url in entry_urls
        if entry_url
        and (
            force_refresh_all
            or entry_url in force_refresh_urls
            or entry_url not in cache
            or not isinstance(cache.get(entry_url), dict)
        )
    ]
    if not pending:
        return cache

    max_workers = max(1, workers)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(parse_entry_detail, url): url for url in pending}
        for index, future in enumerate(as_completed(futures), start=1):
            entry_url = futures[future]
            try:
                cache[entry_url] = future.result()
            except Exception as exc:  # noqa: BLE001
                cache[entry_url] = {
                    "entry_url": entry_url,
                    "tags": [],
                    "review": "",
                    "error": normalize_cell(exc),
                }
            if index % 25 == 0 or index == len(futures):
                write_json(cache_path, cache)

    write_json(cache_path, cache)
    return cache


def enrich_diary_rows(rows: list[dict[str, str]], detail_cache: dict[str, Any]) -> list[dict[str, str]]:
    enriched: list[dict[str, str]] = []
    for row in rows:
        detail = detail_cache.get(row["Entry URL"], {})
        copy = row.copy()
        copy["Tags"] = ", ".join(detail.get("tags", [])) if isinstance(detail, dict) else ""
        enriched.append(copy)
    return enriched


def enrich_review_rows(rows: list[dict[str, str]], detail_cache: dict[str, Any]) -> list[dict[str, str]]:
    enriched: list[dict[str, str]] = []
    for row in rows:
        detail = detail_cache.get(row["Entry URL"], {})
        copy = row.copy()
        if isinstance(detail, dict):
            copy["Tags"] = ", ".join(detail.get("tags", []))
            copy["Review"] = normalize_whitespace(detail.get("review"))
        enriched.append(copy)
    return enriched


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_profile_csv(path: Path, username: str, display_name: str) -> None:
    write_csv(
        path,
        ["Username", "Display Name"],
        [{"Username": username, "Display Name": display_name or username}],
    )


def write_list_export(path: Path, title: str, description: str, tags: list[str], list_url: str, entries: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Letterboxd list export"])
        writer.writerow([])
        writer.writerow(["List", title, ", ".join(tags), list_url, description])
        writer.writerow([])
        writer.writerow([])
        for entry in entries:
            writer.writerow(
                [
                    entry.get("position", ""),
                    entry.get("Name", ""),
                    entry.get("Year", ""),
                    entry.get("Letterboxd URI", ""),
                    entry.get("entry_description", ""),
                ]
            )


def slugify_filename(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalize_whitespace(value)).strip("-").lower()
    return slug or "list"


def main() -> None:
    args = parse_args()
    username = normalize_cell(args.username).strip("/")
    output_dir = Path(args.output_dir).expanduser().resolve()
    cache_dir = Path(args.cache_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    rss_text = fetch_text(f"https://letterboxd.com/{username}/rss/")
    display_name = parse_profile_name_from_rss(rss_text)
    rss_links = parse_rss_review_links(rss_text)

    print("Syncing public diary...", file=sys.stderr)
    diary_rows = parse_diary_pages(username)
    print("Syncing public reviews...", file=sys.stderr)
    review_rows = parse_reviews_pages(username)
    print("Syncing public ratings...", file=sys.stderr)
    rating_rows = parse_ratings_pages(username)
    print("Syncing public watchlist...", file=sys.stderr)
    watchlist_rows = parse_watchlist_pages(username)
    print("Syncing public lists...", file=sys.stderr)
    list_index_rows = parse_list_index_pages(username)

    newest_entry_urls = [row["Entry URL"] for row in diary_rows[: max(0, args.refresh_recent)]]
    newest_review_urls = [row["Entry URL"] for row in review_rows[: max(0, args.refresh_recent)]]
    entry_urls = list(
        dict.fromkeys(
            [
                row["Entry URL"]
                for row in diary_rows + review_rows
                if normalize_cell(row.get("Entry URL"))
            ]
        )
    )
    detail_cache_path = cache_dir / "entry_details.json"
    force_refresh_urls = set(rss_links) | set(newest_entry_urls) | set(newest_review_urls)
    detail_cache = update_entry_detail_cache(
        entry_urls=entry_urls,
        force_refresh_urls=force_refresh_urls,
        cache_path=detail_cache_path,
        workers=args.workers,
        force_refresh_all=args.force_refresh_all_entry_pages,
    )

    diary_rows = enrich_diary_rows(diary_rows, detail_cache)
    review_rows = enrich_review_rows(review_rows, detail_cache)

    lists_dir = output_dir / "lists"
    if lists_dir.exists():
        for existing in lists_dir.glob("*.csv"):
            existing.unlink()
    list_summaries: list[dict[str, Any]] = []
    for row in list_index_rows:
        detail = parse_list_detail(row["url"])
        title = detail["title"] or row["title"]
        description = detail["description"] or row["description"]
        filename = f"{slugify_filename(title)}.csv"
        write_list_export(
            lists_dir / filename,
            title=title,
            description=description,
            tags=detail.get("tags", []),
            list_url=row["url"],
            entries=detail.get("entries", []),
        )
        list_summaries.append(
            {
                "title": title,
                "url": row["url"],
                "description": description,
                "entries": len(detail.get("entries", [])),
            }
        )

    write_profile_csv(output_dir / "profile.csv", username=username, display_name=display_name)
    write_csv(
        output_dir / "ratings.csv",
        ["Date", "Name", "Year", "Letterboxd URI", "Rating"],
        rating_rows,
    )
    write_csv(
        output_dir / "diary.csv",
        ["Date", "Name", "Year", "Letterboxd URI", "Rating", "Rewatch", "Tags", "Watched Date", "Entry URL"],
        diary_rows,
    )
    write_csv(
        output_dir / "reviews.csv",
        ["Date", "Name", "Year", "Letterboxd URI", "Rating", "Review", "Tags", "Entry URL"],
        review_rows,
    )
    write_csv(
        output_dir / "watchlist.csv",
        ["Date", "Name", "Year", "Letterboxd URI"],
        watchlist_rows,
    )

    summary = {
        "username": username,
        "display_name": display_name,
        "counts": {
            "ratings": len(rating_rows),
            "diary": len(diary_rows),
            "reviews": len(review_rows),
            "watchlist": len(watchlist_rows),
            "lists": len(list_summaries),
        },
        "rss_links": rss_links,
        "lists": list_summaries,
    }
    write_json(cache_dir / "last_sync_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
