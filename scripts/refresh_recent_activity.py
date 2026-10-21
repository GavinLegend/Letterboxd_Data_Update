#!/usr/bin/env python3
"""Publish the latest public Letterboxd RSS entries without account access."""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.request import Request, urlopen

LETTERBOXD_NS = "https://letterboxd.com"
RSS_URL = "https://letterboxd.com/goorison/rss/"
ENTRY_PREFIX = "https://letterboxd.com/goorison/film/"


def parse_feed(xml_text: str) -> dict:
    root = ET.fromstring(xml_text)
    items = []
    for item in root.findall("./channel/item"):
        link = (item.findtext("link") or "").strip()
        if not link.startswith(ENTRY_PREFIX):
            continue
        published = parsedate_to_datetime(item.findtext("pubDate") or "")
        items.append(
            {
                "title": (item.findtext(f"{{{LETTERBOXD_NS}}}filmTitle") or "").strip(),
                "year": (item.findtext(f"{{{LETTERBOXD_NS}}}filmYear") or "").strip(),
                "rating": (item.findtext(f"{{{LETTERBOXD_NS}}}memberRating") or "").strip(),
                "watched_date": (item.findtext(f"{{{LETTERBOXD_NS}}}watchedDate") or "").strip(),
                "published_at": published.astimezone(timezone.utc).isoformat(timespec="seconds"),
                "url": link,
            }
        )
    if not items:
        raise ValueError("Letterboxd RSS returned no usable public entries")
    return {"source": RSS_URL, "latest_activity_at": items[0]["published_at"], "items": items}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("recent-activity.json"))
    args = parser.parse_args()
    request = Request(RSS_URL, headers={"User-Agent": "GavinLegend-public-report/1.0"})
    with urlopen(request, timeout=30) as response:
        payload = parse_feed(response.read().decode("utf-8"))
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(payload['items'])} recent public entries through {payload['latest_activity_at']}")


if __name__ == "__main__":
    main()
