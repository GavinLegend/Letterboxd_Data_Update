from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "refresh_recent_activity.py"
SPEC = importlib.util.spec_from_file_location("refresh_recent_activity", SCRIPT_PATH)
assert SPEC and SPEC.loader
refresh = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(refresh)


class RecentActivityTests(unittest.TestCase):
    def test_parses_public_entry_and_ignores_other_links(self) -> None:
        xml = """<rss xmlns:letterboxd="https://letterboxd.com"><channel>
          <item><link>https://letterboxd.com/goorison/film/example/1/</link>
            <pubDate>Wed, 21 Oct 2026 13:00:00 -0400</pubDate>
            <letterboxd:filmTitle>Example</letterboxd:filmTitle>
            <letterboxd:filmYear>2026</letterboxd:filmYear>
            <letterboxd:watchedDate>2026-10-20</letterboxd:watchedDate>
          </item>
          <item><link>https://other.example/film/</link>
            <pubDate>Wed, 21 Oct 2026 13:00:00 -0400</pubDate></item>
        </channel></rss>"""

        result = refresh.parse_feed(xml)

        self.assertEqual(result["latest_activity_at"], "2026-10-21T17:00:00+00:00")
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["watched_date"], "2026-10-20")


if __name__ == "__main__":
    unittest.main()
