# Letterboxd Custom Report

This repository publishes a shareable Letterboxd analysis site to GitHub Pages and now supports automatic refresh from the public Letterboxd profile for `goorison`.

## What updates automatically

- Public diary entries
- Public reviews and review text
- Public tags attached to diary/review entries
- Public watchlist
- Public custom lists and list contents
- The generated website at `index.html`

## How it works

1. GitHub Actions fetches the public Letterboxd profile pages and RSS feed.
2. The sync script rebuilds a local export-like folder with `ratings.csv`, `diary.csv`, `reviews.csv`, `watchlist.csv`, `profile.csv`, and `lists/*.csv`.
3. The existing custom report generator rebuilds the site.
4. If full-page fetching is challenged, the workflow keeps the last complete analysis and still refreshes `recent-activity.json` from the public RSS feed.
5. The page shows recent public activity separately and identifies the date of the last complete analysis. Changed published files are committed to `main`.

## Schedule

- Every 6 hours: incremental refresh of the newest public activity
- Every Sunday: full refresh of cached diary/review detail pages
- Any time: manual run from the `Actions` tab with `workflow_dispatch`

## Important limitation

This automation is based on public pages and RSS, not on the private Letterboxd export bundle or private API access. That means it can stay hands-off, but it may miss data that only exists in account exports or private content.

Letterboxd sometimes serves a Cloudflare challenge to automated full-page requests. During those periods the RSS panel can stay current, but historical analysis totals, lists, tags, and recommendations remain at the last complete rebuild. A Letterboxd export is needed to reconcile a fully current snapshot if public-page access remains blocked.

## Local run

From the repository root:

```bash
./scripts/run_public_sync.sh
```

## Rebuild from an account export

Keep the Letterboxd ZIP and prepared CSVs outside this public repository. The export may contain deleted or private account data. `prepare_account_export.py` selects current ratings, diary, reviews, watchlist, and lists, and reduces `profile.csv` to the username. Review account visibility before publishing.

```bash
python scripts/prepare_account_export.py /private/path/letterboxd-export.zip /private/path/report-input
python scripts/seed_metadata_cache_from_report.py \
  --report custom-report-data.json \
  --input-dir /private/path/report-input \
  --output /private/path/report-output/film_metadata_cache.json
python scripts/build_custom_letterboxd_report.py \
  --input-dir /private/path/report-input \
  --output-dir /private/path/report-output \
  --streaming-lookups 0 --douban-lookups 0 \
  --watched-douban-lookups 0 --ptgen-detail-lookups 0 \
  --streaming-catalog-timeout 0
python scripts/validate_report_data.py \
  --input-dir /private/path/report-input \
  --report-json /private/path/report-output/custom-report-data.json \
  --index-html /private/path/report-output/share-site/index.html \
  --output /private/path/report-output/share-site/missing_data_report.md
```

After checking the generated files for sensitive content, copy only `share-site/index.html`, `share-site/custom-report-data.json`, and `share-site/missing_data_report.md` to the repository root. The RSS feed and scheduled workflow continue to update recent public activity between full rebuilds.

The scheduled public-page sync keeps the published analysis when its film, diary, review, tag, or list counts are lower than the current report. If you intentionally remove records, rebuild from a new account export to publish that change.

If you ever want to point this at a different public Letterboxd account, change the default username in:

- `.github/workflows/sync-letterboxd-public.yml`
- `scripts/run_public_sync.sh`
